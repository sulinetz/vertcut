"""Тесты оптимизаций рендера: hw_decode, фоллбэки, loudnorm, make_preview, _bg_chain, воркеры и reframe."""
from __future__ import annotations

import inspect
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vertcut import config, pipeline, reframe, render, utils


class FakeProc:
    """Подменяет subprocess.Popen для render_clip."""

    def __init__(self, cmd, fail=False, **_kwargs):
        self.cmd = list(cmd)
        self.returncode = 1 if fail else 0
        self.stdout = iter(["out_time_us=1000000\n"])
        self.stderr = iter(["mocked ffmpeg error\n"] if fail else [])
        if not fail:
            target = Path(cmd[-1])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"x" * 20000)

    def wait(self):
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        self.returncode = -1


def _probe(_path):
    return {
        "width": 1920,
        "height": 1080,
        "duration": 60.0,
        "fps": 30.0,
        "has_audio": True,
        "sample_rate": 48000,
        "audio_streams": [],
    }


def _make_synthetic_mp4(path: Path, size: str = "640x360", duration: float = 1.0) -> None:
    proc = utils.run([
        config.ffmpeg(), "-y", "-hide_banner", "-v", "error",
        "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=25:duration={duration}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
    ], timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(f"failed to generate synthetic mp4: {proc.stderr}")


class HwDecodeProbeTest(unittest.TestCase):
    def setUp(self):
        render._HW_CACHE.clear()
        render._HW_DECODE_CACHE.clear()

    def tearDown(self):
        render._HW_CACHE.clear()
        render._HW_DECODE_CACHE.clear()

    def test_env_disable_values_skip_probe(self):
        for val in ("0", "false", "no", "off", "FALSE", " Off "):
            render._HW_DECODE_CACHE.clear()
            with mock.patch.dict(os.environ, {"VERTCUT_HW_DECODE": val}), \
                 mock.patch.object(render, "run") as run_mock:
                self.assertIsNone(render.hw_decode())
                run_mock.assert_not_called()
                self.assertIn("value", render._HW_DECODE_CACHE)
                self.assertIsNone(render._HW_DECODE_CACHE["value"])

    def test_auto_succeeds_and_caches_cuda(self):
        hwaccels = subprocess.CompletedProcess([], 0, "Hardware acceleration methods:\ncuda\ndxva2\n", "")
        ok = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.dict(os.environ, {"VERTCUT_HW_DECODE": "auto"}), \
             mock.patch.object(render, "run", side_effect=[hwaccels, ok, ok]) as run_mock:
            self.assertEqual(render.hw_decode(), "cuda")
            self.assertEqual(run_mock.call_count, 3)
            self.assertEqual(render.hw_decode(), "cuda")
            self.assertEqual(run_mock.call_count, 3)

    def test_failed_decode_probe_is_cached_as_none(self):
        # 1) Non-zero return code on decode probe
        hwaccels = subprocess.CompletedProcess([], 0, "cuda\n", "")
        gen_ok = subprocess.CompletedProcess([], 0, "", "")
        dec_fail = subprocess.CompletedProcess([], 1, "", "No device")
        with mock.patch.dict(os.environ, {"VERTCUT_HW_DECODE": "auto"}), \
             mock.patch.object(render, "run", side_effect=[hwaccels, gen_ok, dec_fail]) as run_mock:
            self.assertIsNone(render.hw_decode())
            self.assertEqual(run_mock.call_count, 3)
            self.assertIsNone(render.hw_decode())
            self.assertEqual(run_mock.call_count, 3)

        # 2) Return code 0 but silent cuvid/lacking error on stderr (FFmpeg 9.0.2 quirk)
        render._HW_DECODE_CACHE.clear()
        silent_fail = subprocess.CompletedProcess(
            [], 0, "", "[h264 @ 0x1] Hardware is lacking required capabilities\nFailed setup for format cuda\n"
        )
        with mock.patch.dict(os.environ, {"VERTCUT_HW_DECODE": "auto"}), \
             mock.patch.object(render, "run", side_effect=[hwaccels, gen_ok, silent_fail]) as run_mock:
            self.assertIsNone(render.hw_decode())
            self.assertEqual(run_mock.call_count, 3)
            self.assertIsNone(render.hw_decode())
            self.assertEqual(run_mock.call_count, 3)

        # 3) Missing cuda in -hwaccels
        render._HW_DECODE_CACHE.clear()
        no_cuda = subprocess.CompletedProcess([], 0, "dxva2\nd3d11va\n", "")
        with mock.patch.dict(os.environ, {"VERTCUT_HW_DECODE": "auto"}), \
             mock.patch.object(render, "run", return_value=no_cuda) as run_mock:
            self.assertIsNone(render.hw_decode())
            self.assertEqual(run_mock.call_count, 1)
            self.assertIsNone(render.hw_decode())
            self.assertEqual(run_mock.call_count, 1)

    def test_probe_exception_returns_none_safely(self):
        for exc in (OSError("no ffmpeg"), subprocess.TimeoutExpired(["ffmpeg"], 15)):
            render._HW_DECODE_CACHE.clear()
            with mock.patch.dict(os.environ, {"VERTCUT_HW_DECODE": "auto"}), \
                 mock.patch.object(render, "run", side_effect=exc):
                self.assertIsNone(render.hw_decode())
                self.assertIn("value", render._HW_DECODE_CACHE)
                self.assertIsNone(render._HW_DECODE_CACHE["value"])


class RenderHwDecodeFallbackTest(unittest.TestCase):
    def setUp(self):
        render._HW_CACHE.clear()
        render._HW_DECODE_CACHE.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.src = self.dir / "src.mp4"
        self.src.write_bytes(b"x" * 100)
        self.out = self.dir / "out.mp4"

    def tearDown(self):
        self.tmp.cleanup()
        render._HW_CACHE.clear()
        render._HW_DECODE_CACHE.clear()

    def test_hw_decode_places_hwaccel_before_input_without_output_format(self):
        made = []

        def fake(cmd, **kw):
            proc = FakeProc(cmd, **kw)
            made.append(proc.cmd)
            return proc

        with mock.patch.object(render, "probe", _probe), \
             mock.patch.object(render, "_measure_loudness", lambda *a, **k: None), \
             mock.patch.object(render, "hw_decode", lambda: "cuda"), \
             mock.patch.object(render, "hw_encoder", lambda: "h264_nvenc"), \
             mock.patch.object(render, "subprocess") as sub:
            sub.Popen.side_effect = fake
            sub.PIPE = -1
            res = render.render_clip(self.src, 0.0, 10.0, self.out)

        cmd = made[0]
        self.assertIn("-hwaccel", cmd)
        hw_idx = cmd.index("-hwaccel")
        self.assertEqual(cmd[hw_idx + 1], "cuda")
        self.assertLess(hw_idx, cmd.index("-i"))
        self.assertNotIn("-hwaccel_output_format", cmd)
        self.assertEqual(res["hw_decode"], "cuda")
        self.assertEqual(res["encoder"], "h264_nvenc")
        self.assertFalse(res["fallback"])

    def test_two_step_fallback_step1_drops_hwaccel_keeps_hw_encode(self):
        calls = []

        def fake(cmd, **kw):
            calls.append(list(cmd))
            return FakeProc(cmd, fail=(len(calls) == 1), **kw)

        with mock.patch.object(render, "probe", _probe), \
             mock.patch.object(render, "_measure_loudness", lambda *a, **k: None), \
             mock.patch.object(render, "hw_decode", lambda: "cuda"), \
             mock.patch.object(render, "hw_encoder", lambda: "h264_nvenc"), \
             mock.patch.object(render, "subprocess") as sub:
            sub.Popen.side_effect = fake
            sub.PIPE = -1
            res = render.render_clip(self.src, 0.0, 10.0, self.out, bitrate=12)

        self.assertEqual(len(calls), 2)
        self.assertIn("-hwaccel", calls[0])
        self.assertIn("h264_nvenc", calls[0])

        cmd2 = calls[1]
        self.assertNotIn("-hwaccel", cmd2)
        self.assertNotIn("cuda", cmd2)
        self.assertIn("h264_nvenc", cmd2)
        self.assertEqual(cmd2.count("-t"), 2)
        self.assertIn("-map_metadata", cmd2)
        self.assertIn("-map_chapters", cmd2)
        self.assertIn("-movflags", cmd2)
        self.assertIn("-shortest", cmd2)
        self.assertIn("-maxrate", cmd2)
        self.assertTrue(cmd2[-1].endswith("out.mp4"))

        self.assertEqual(res["encoder"], "h264_nvenc")
        self.assertIsNone(res["hw_decode"])
        self.assertTrue(res["fallback"])

    def test_two_step_fallback_step2_falls_back_to_libx264(self):
        calls = []
        progress = []

        def fake(cmd, **kw):
            calls.append(list(cmd))
            return FakeProc(cmd, fail=(len(calls) <= 2), **kw)

        with mock.patch.object(render, "probe", _probe), \
             mock.patch.object(render, "_measure_loudness", lambda *a, **k: None), \
             mock.patch.object(render, "hw_decode", lambda: "cuda"), \
             mock.patch.object(render, "hw_encoder", lambda: "h264_nvenc"), \
             mock.patch.object(render, "subprocess") as sub:
            sub.Popen.side_effect = fake
            sub.PIPE = -1
            res = render.render_clip(
                self.src, 0.0, 10.0, self.out, bitrate=12, speed=1.05,
                on_progress=progress.append,
            )

        self.assertEqual(len(calls), 3)
        self.assertIn("-hwaccel", calls[0])
        self.assertIn("h264_nvenc", calls[0])
        self.assertNotIn("-hwaccel", calls[1])
        self.assertIn("h264_nvenc", calls[1])

        cmd3 = calls[2]
        self.assertNotIn("-hwaccel", cmd3)
        self.assertIn("libx264", cmd3)
        self.assertNotIn("h264_nvenc", cmd3)
        self.assertEqual(cmd3.count("-t"), 2)
        self.assertEqual(
            cmd3[cmd3.index("-t", cmd3.index("-filter_complex")) + 1],
            f"{10.0 / 1.05:.3f}",
        )
        self.assertIn("-map_metadata", cmd3)
        self.assertIn("-map_chapters", cmd3)
        self.assertIn("-movflags", cmd3)
        self.assertIn("-maxrate", cmd3)
        self.assertIn("-shortest", cmd3)
        self.assertTrue(cmd3[-1].endswith("out.mp4"))

        self.assertEqual(res["encoder"], "libx264")
        self.assertIsNone(res["hw_decode"])
        self.assertTrue(res["fallback"])
        self.assertEqual(progress[-1], 1.0)
        self.assertEqual(sum(1 for p in progress if 0.0 < p < 1.0), 3)

    def test_hw_decode_with_cpu_encoder_falls_back_to_plain_libx264(self):
        calls = []

        def fake(cmd, **kw):
            calls.append(list(cmd))
            return FakeProc(cmd, fail=(len(calls) == 1), **kw)

        with mock.patch.object(render, "probe", _probe), \
             mock.patch.object(render, "_measure_loudness", lambda *a, **k: None), \
             mock.patch.object(render, "hw_decode", lambda: "cuda"), \
             mock.patch.object(render, "hw_encoder", lambda: None), \
             mock.patch.object(render, "subprocess") as sub:
            sub.Popen.side_effect = fake
            sub.PIPE = -1
            res = render.render_clip(self.src, 0.0, 10.0, self.out)

        self.assertEqual(len(calls), 2)
        self.assertIn("-hwaccel", calls[0])
        self.assertIn("libx264", calls[0])
        self.assertNotIn("-hwaccel", calls[1])
        self.assertIn("libx264", calls[1])
        self.assertIsNone(res["hw_decode"])
        self.assertEqual(res["encoder"], "libx264")
        self.assertTrue(res["fallback"])


class MeasureLoudnessFlagsTest(unittest.TestCase):
    def test_loudnorm_disables_video_subs_data_before_af(self):
        payload = json.dumps({
            "input_i": "-16.5",
            "input_tp": "-2.1",
            "input_lra": "6.0",
            "input_thresh": "-27.0",
            "target_offset": "2.5",
        })
        proc = subprocess.CompletedProcess([], 0, "", f"info\n{payload}\n")
        with mock.patch.object(render.subprocess, "run", return_value=proc) as run_mock:
            out = render._measure_loudness(Path("video.mp4"), 1.5, 8.0, audio_track=1)

        self.assertIsNotNone(out)
        self.assertEqual(out["input_i"], "-16.5")
        cmd = run_mock.call_args.args[0]
        af_idx = cmd.index("-af")
        for flag in ("-vn", "-sn", "-dn"):
            self.assertIn(flag, cmd)
            self.assertLess(cmd.index(flag), af_idx)
        map_idx = cmd.index("-map")
        self.assertEqual(cmd[map_idx + 1], "0:a:1")


class MakePreviewGpuTest(unittest.TestCase):
    def setUp(self):
        render._HW_CACHE.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.clip = self.dir / "clip.mp4"
        self.clip.write_bytes(b"x" * 100)
        self.out = self.dir / "prev.mp4"

    def tearDown(self):
        self.tmp.cleanup()
        render._HW_CACHE.clear()

    def test_make_preview_uses_nvenc_fast_preset(self):
        calls = []

        def fake_run(cmd, **_kw):
            calls.append(list(cmd))
            Path(cmd[-1]).write_bytes(b"ok")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with mock.patch.object(render, "hw_encoder", lambda: "h264_nvenc"), \
             mock.patch.object(render, "run", side_effect=fake_run):
            res = render.make_preview(self.clip, self.out)

        self.assertEqual(res, self.out)
        self.assertEqual(len(calls), 1)
        cmd = calls[0]
        self.assertEqual(cmd[cmd.index("-c:v") + 1], "h264_nvenc")
        self.assertEqual(cmd[cmd.index("-preset") + 1], "p4")
        self.assertEqual(cmd[cmd.index("-rc") + 1], "vbr")
        self.assertEqual(cmd[cmd.index("-cq") + 1], "30")
        self.assertEqual(cmd[cmd.index("-b:v") + 1], "0")

    def test_make_preview_falls_back_to_libx264_on_gpu_error(self):
        calls = []

        def fake_run(cmd, **_kw):
            calls.append(list(cmd))
            if len(calls) == 1:
                return subprocess.CompletedProcess(cmd, 1, "", "nvenc failed")
            Path(cmd[-1]).write_bytes(b"ok")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with mock.patch.object(render, "hw_encoder", lambda: "h264_nvenc"), \
             mock.patch.object(render, "run", side_effect=fake_run):
            res = render.make_preview(self.clip, self.out)

        self.assertEqual(res, self.out)
        self.assertEqual(len(calls), 2)
        cmd2 = calls[1]
        self.assertEqual(cmd2[cmd2.index("-c:v") + 1], "libx264")
        self.assertEqual(cmd2[cmd2.index("-preset") + 1], "veryfast")
        self.assertEqual(cmd2[cmd2.index("-crf") + 1], "30")

    def test_make_preview_cpu_when_no_hw_encoder_and_returns_none_on_failure(self):
        calls = []

        def fake_run(cmd, **_kw):
            calls.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 1, "", "error")

        with mock.patch.object(render, "hw_encoder", lambda: None), \
             mock.patch.object(render, "run", side_effect=fake_run):
            res = render.make_preview(self.clip, self.out)

        self.assertIsNone(res)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][calls[0].index("-c:v") + 1], "libx264")


class BgChainFilterTest(unittest.TestCase):
    def test_bg_chain_downscales_4x_blurs_8_5_and_upscales_bilinear(self):
        graph = render._bg_chain(1080, 1920)
        self.assertIn("scale=270:480:force_original_aspect_ratio=increase:flags=bicubic", graph)
        self.assertIn("crop=270:480", graph)
        self.assertIn("gblur=sigma=8.5:steps=2", graph)
        self.assertNotIn("gblur=sigma=34", graph)
        self.assertIn("scale=1080:1920:flags=bilinear[bgb]", graph)
        self.assertIn("[fg]scale=1080:-2:flags=bicubic[fgs]", graph)

        sharp_graph = render._bg_chain(1080, 1920, sharpen=True)
        self.assertIn("[fg]scale=1080:-2:flags=lanczos,unsharp=", sharp_graph)

    def test_bg_chain_forces_even_small_dimensions(self):
        graph = render._bg_chain(1080, 1350)
        self.assertIn("scale=270:336:", graph)
        self.assertIn("crop=270:336", graph)
        self.assertNotIn("337", graph)

        tiny = render._bg_chain(6, 6)
        self.assertIn("scale=2:2:", tiny)
        self.assertIn("crop=2:2", tiny)


class RenderWorkersTest(unittest.TestCase):
    def test_workers_capped_on_gpu(self):
        for cpus, expected in ((4, 1), (8, 1), (16, 2), (32, 2), (None, 1)):
            with mock.patch.dict(os.environ, {"VERTCUT_RENDER_WORKERS": ""}), \
                 mock.patch.object(pipeline.render, "hw_encoder", lambda: "h264_nvenc"), \
                 mock.patch.object(pipeline.os, "cpu_count", lambda c=cpus: c):
                self.assertEqual(pipeline._render_workers(), expected)

    def test_workers_cpu_formula_without_gpu(self):
        for cpus, expected in ((4, 1), (6, 2), (9, 3), (16, 3), (None, 1)):
            with mock.patch.dict(os.environ, {"VERTCUT_RENDER_WORKERS": ""}), \
                 mock.patch.object(pipeline.render, "hw_encoder", lambda: None), \
                 mock.patch.object(pipeline.os, "cpu_count", lambda c=cpus: c):
                self.assertEqual(pipeline._render_workers(), expected)

    def test_workers_env_override_and_invalid_values(self):
        for raw, expected in (("5", 5), ("99", 8), ("0", 1), ("invalid", 1)):
            with mock.patch.dict(os.environ, {"VERTCUT_RENDER_WORKERS": raw}), \
                 mock.patch.object(pipeline.render, "hw_encoder", lambda: "h264_nvenc"), \
                 mock.patch.object(pipeline.os, "cpu_count", lambda: 8):
                self.assertEqual(pipeline._render_workers(), expected)


class ReframeOptimizationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.src = self.dir / "src.mp4"
        _make_synthetic_mp4(self.src, size="640x360", duration=1.0)

    def tearDown(self):
        self.tmp.cleanup()

    def test_reframe_default_max_width_is_640(self):
        self.assertEqual(
            inspect.signature(reframe.detect_facecam).parameters["max_width"].default,
            640,
        )
        self.assertEqual(
            inspect.signature(reframe.build_crop_path).parameters["max_width"].default,
            640,
        )

    def test_reframe_skips_probe_when_info_passed(self):
        info = {"width": 640, "height": 360}
        with mock.patch.object(
            reframe.utils, "probe",
            mock.Mock(side_effect=AssertionError("probe must not be called")),
        ):
            self.assertIsNone(reframe.detect_facecam(self.src, 0.0, 1.0, info=info))
            crop = reframe.build_crop_path(self.src, 0.0, 1.0, info=info)
        self.assertIsNotNone(crop)
        self.assertIn("crop_w", crop)
        self.assertIn("crop_h", crop)
        self.assertIn("times", crop)

    def test_reframe_probes_when_info_is_none(self):
        with mock.patch.object(reframe.utils, "probe", wraps=utils.probe) as probe_mock:
            reframe.detect_facecam(self.src, 0.0, 0.5)
            reframe.build_crop_path(self.src, 0.0, 0.5)
        self.assertEqual(probe_mock.call_count, 2)

    def test_render_one_probes_source_once_across_facecam_crop_and_render(self):
        clip = {
            "id": "c1", "idx": 0, "project_id": "p1",
            "start": 0.0, "end": 1.0, "title": "t", "hook": "",
            "words": [], "settings": {},
        }
        seen_facecam_info = []
        seen_crop_info = []
        seen_render_info = []

        orig_detect = reframe.detect_facecam
        orig_build = reframe.build_crop_path

        def wrapped_detect(source, start, end, **kwargs):
            seen_facecam_info.append(kwargs.get("info"))
            orig_detect(source, start, end, **kwargs)
            return {"x": 10.0, "y": 10.0, "w": 120.0, "h": 90.0,
                    "share": 0.9, "source": [640, 360]}

        def wrapped_build(source, start, end, **kwargs):
            seen_crop_info.append(kwargs.get("info"))
            return orig_build(source, start, end, **kwargs)

        def fake_render(source, clip_start, clip_end, out_path, **kwargs):
            seen_render_info.append(kwargs.get("info"))
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"x" * 20000)
            return {"path": out_path, "duration": 1.0, "width": 1080, "height": 1920,
                    "encoder": "libx264", "hw_decode": None, "fallback": False}

        with mock.patch.object(utils, "probe", wraps=utils.probe) as probe_mock, \
             mock.patch.object(render, "probe", side_effect=AssertionError("render.probe must not be called")), \
             mock.patch.object(reframe, "detect_facecam", side_effect=wrapped_detect), \
             mock.patch.object(reframe, "build_crop_path", side_effect=wrapped_build), \
             mock.patch.object(render, "render_clip", side_effect=fake_render), \
             mock.patch.object(render, "make_thumb", lambda *a, **k: None), \
             mock.patch.object(render, "make_preview", lambda *a, **k: None), \
             mock.patch.object(pipeline.db, "update_clip", lambda *a, **k: None):
            pipeline._render_one(
                self.src, self.dir / "work1", clip,
                {"mode": "auto", "layout": "band", "subtitles": False},
            )
            self.assertEqual(probe_mock.call_count, 1)

        self.assertIsNotNone(seen_facecam_info[0])
        self.assertIsNotNone(seen_crop_info[0])
        self.assertIsNotNone(seen_render_info[0])

        # Also verify real render_clip skips render.probe when info is passed from _render_one
        with mock.patch.object(utils, "probe", wraps=utils.probe) as probe_mock2, \
             mock.patch.object(render, "probe", side_effect=AssertionError("render.probe must not be called")), \
             mock.patch.object(render, "_measure_loudness", lambda *a, **k: None), \
             mock.patch.object(render, "hw_decode", lambda: None), \
             mock.patch.object(render, "hw_encoder", lambda: None), \
             mock.patch.object(render, "subprocess") as sub, \
             mock.patch.object(render, "make_thumb", lambda *a, **k: None), \
             mock.patch.object(render, "make_preview", lambda *a, **k: None), \
             mock.patch.object(pipeline.db, "update_clip", lambda *a, **k: None):
            sub.Popen.side_effect = FakeProc
            sub.PIPE = -1
            pipeline._render_one(
                self.src, self.dir / "work2", clip,
                {"mode": "auto", "layout": "", "subtitles": False},
            )
            self.assertEqual(probe_mock2.call_count, 1)


if __name__ == "__main__":
    unittest.main()
