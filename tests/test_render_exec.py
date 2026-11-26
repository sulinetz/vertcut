"""Запуск ffmpeg: watchdog по прогрессу, откат энкодера и лимит длительности."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from vertcut import render


def _probe(_path):
    return {"width": 1920, "height": 1080, "duration": 60.0, "fps": 30.0,
            "has_audio": False, "sample_rate": 48000, "audio_streams": []}


class FakeProc:
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


class RunnerTest(unittest.TestCase):
    def test_watchdog_kills_silent_process(self):
        started = time.time()
        result = render._run_ffmpeg(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            duration=10.0, stall=1.0)
        elapsed = time.time() - started
        self.assertIn("прогресс", result["killed"])
        self.assertNotEqual(result["returncode"], 0)
        self.assertLess(elapsed, 10.0, "watchdog должен срабатывать по простою, а не по общему таймеру")

    def test_slow_but_alive_process_is_not_killed(self):
        script = ("import time\n"
                  "for _ in range(6):\n"
                  "    print('out_time_us=500000', flush=True)\n"
                  "    time.sleep(0.25)\n")
        result = render._run_ffmpeg([sys.executable, "-c", script],
                                    duration=10.0, stall=1.0)
        self.assertEqual(result["killed"], "")
        self.assertEqual(result["returncode"], 0)

    def test_stdout_is_drained_in_fallback(self):
        calls = {"n": 0}
        progress = []

        def fake(cmd, **kwargs):
            calls["n"] += 1
            return FakeProc(cmd, fail=calls["n"] == 1, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            src = workdir / "src.mp4"
            src.write_bytes(b"x" * 100)
            with mock.patch.object(render, "probe", _probe), \
                 mock.patch.object(render, "_measure_loudness", lambda *a, **k: None), \
                 mock.patch.object(render, "hw_decode", lambda: None), \
                 mock.patch.object(render, "hw_encoder", lambda: "h264_nvenc"), \
                 mock.patch.object(render, "subprocess") as sub:
                sub.Popen.side_effect = fake
                sub.PIPE = -1
                render.render_clip(src, 0.0, 10.0, workdir / "out.mp4",
                                   on_progress=progress.append)
        self.assertEqual(calls["n"], 2)
        self.assertEqual(progress.count(0.1), 2,
                         "второй запуск тоже обязан читать stdout, а не только stderr")
        self.assertEqual(progress[-1], 1.0)

    def test_output_duration_is_limited(self):
        made = []

        def fake(cmd, **kwargs):
            made.append(list(cmd))
            return FakeProc(cmd, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            src = workdir / "src.mp4"
            src.write_bytes(b"x" * 100)
            with mock.patch.object(render, "probe", _probe), \
                 mock.patch.object(render, "_measure_loudness", lambda *a, **k: None), \
                 mock.patch.object(render, "hw_decode", lambda: None), \
                 mock.patch.object(render, "hw_encoder", lambda: None), \
                 mock.patch.object(render, "subprocess") as sub:
                sub.Popen.side_effect = fake
                sub.PIPE = -1
                render.render_clip(src, 5.0, 20.0, workdir / "out.mp4", speed=1.05)
        cmd = made[0]
        self.assertEqual(cmd.count("-t"), 2)
        self.assertEqual(cmd[cmd.index("-t", cmd.index("-filter_complex")) + 1],
                         f"{15.0 / 1.05:.3f}")


class HwProbeTest(unittest.TestCase):
    def setUp(self):
        render._HW_CACHE.clear()

    def tearDown(self):
        render._HW_CACHE.clear()

    def test_failed_test_encode_is_cached(self):
        encoders = subprocess.CompletedProcess([], 0, " V....D h264_nvenc ...", "")
        failed = subprocess.CompletedProcess([], 1, "", "no device")
        with mock.patch.object(render, "run", side_effect=[encoders, failed]) as run:
            self.assertIsNone(render.hw_encoder())
            self.assertEqual(run.call_count, 2)
            self.assertIsNone(render.hw_encoder())
            self.assertEqual(run.call_count, 2, "неудача должна кешироваться")

    def test_working_encoder_survives_test_encode(self):
        ok = subprocess.CompletedProcess([], 0, " V....D h264_nvenc ...", "")
        with mock.patch.object(render, "run", return_value=ok):
            self.assertEqual(render.hw_encoder(), "h264_nvenc")


if __name__ == "__main__":
    unittest.main()
