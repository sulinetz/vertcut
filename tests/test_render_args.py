"""Команда ffmpeg: метаданные, битрейт, склейки, скорость, ADHD и откат энкодера."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vertcut import render


class FakeProc:
    """Подменяет ffmpeg: записывает команду и создаёт файл на месте выхода."""

    def __init__(self, cmd, fail=False, **_kwargs):
        self.cmd = cmd
        self.returncode = 1 if fail else 0
        self.stdout = iter(["out_time_us=1000000\n"])
        self.stderr = iter([])
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
    return {"width": 1920, "height": 1080, "duration": 60.0, "fps": 30.0,
            "has_audio": True, "height_ok": True}


class RenderCommandTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.src = self.dir / "src.mp4"
        self.src.write_bytes(b"x" * 100)
        self.out = self.dir / "out.mp4"

    def tearDown(self):
        self.tmp.cleanup()

    def _render(self, **kwargs):
        made = []

        def fake(cmd, **kw):
            proc = FakeProc(cmd, **kw)
            made.append(proc.cmd)
            return proc

        with mock.patch.object(render, "probe", _probe), \
             mock.patch.object(render, "_measure_loudness", lambda *a, **k: None), \
             mock.patch.object(render, "hw_encoder", lambda: None), \
             mock.patch.object(render, "subprocess") as sub:
            sub.Popen.side_effect = fake
            sub.PIPE = -1
            render.render_clip(self.src, 0.0, 10.0, self.out, **kwargs)
        return made[0]

    def test_metadata_stripped(self):
        cmd = self._render()
        self.assertIn("-map_metadata", cmd)
        self.assertEqual(cmd[cmd.index("-map_metadata") + 1], "-1")
        self.assertIn("-map_chapters", cmd)

    def test_jump_cut_filters(self):
        cmd = self._render(segments=[(0.0, 2.0), (5.0, 7.0)], speed=1.0)
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("trim=start=0.000:end=2.000", graph)
        self.assertIn("concat=n=2", graph)
        self.assertIn("atrim", graph)

    def test_speed_and_pitch(self):
        cmd = self._render(speed=1.05, pitch=1.02)
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("setpts=PTS/1.050000", graph)
        self.assertIn("asetrate=48000*1.02000", graph)
        self.assertIn("atempo=", graph)

    def test_adhd_vstack(self):
        bg = self.dir / "bg.mp4"
        bg.write_bytes(b"x" * 100)
        cmd = self._render(layout="adhd", bg_path=bg, split_ratio=0.5)
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("vstack=inputs=2", graph)
        self.assertIn("[1:v]", graph)
        # фон без звука: единственная звуковая дорожка — исходник
        self.assertIn("[0:a]", graph)

    def test_nvenc_bitrate(self):
        args = render._hw_args("h264_nvenc", 21)
        self.assertEqual(args[1], "h264_nvenc")
        # cap добавляется в render_clip, а не в _hw_args
        self.assertNotIn("-maxrate", args)

    def test_fallback_keeps_command_tail(self):
        cmd_holder = {"calls": 0}

        def fake(cmd, **kwargs):
            cmd_holder["calls"] += 1
            if cmd_holder["calls"] == 1:
                return FakeProc(cmd, fail=True)
            cmd_holder["cmd"] = list(cmd)
            return FakeProc(cmd, fail=False)

        with mock.patch.object(render, "probe", _probe), \
             mock.patch.object(render, "_measure_loudness", lambda *a, **k: None), \
             mock.patch.object(render, "hw_encoder", lambda: "h264_nvenc"), \
             mock.patch.object(render, "subprocess") as sub:
            sub.Popen.side_effect = fake
            sub.PIPE = -1
            render.render_clip(self.src, 0.0, 10.0, self.out, bitrate=12)

        fallback = cmd_holder["cmd"]
        self.assertIn("libx264", fallback)
        self.assertNotIn("h264_nvenc", fallback)
        self.assertIn("-map_metadata", fallback)
        self.assertTrue(fallback[-1].endswith("out.mp4"))
        self.assertIn("-movflags", fallback)
        self.assertIn("-maxrate", fallback)


class AtempoTest(unittest.TestCase):
    def test_splits_out_of_range(self):
        chain = render._atempo_chain(3.0)
        self.assertTrue(all("atempo=" in item for item in chain))
        self.assertGreater(len(chain), 1)

    def test_single_step(self):
        self.assertEqual(render._atempo_chain(1.0), [])
        self.assertAlmostEqual(float(render._atempo_chain(1.05)[0].split("=")[1]), 1.05, places=4)


if __name__ == "__main__":
    unittest.main()
