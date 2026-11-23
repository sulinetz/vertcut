"""Возможности ffmpeg и микс музыки без просадки громкости."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vertcut import config, render


class FakeProc:
    def __init__(self, cmd, **_kwargs):
        self.cmd = cmd
        self.returncode = 0
        self.stdout = iter(["out_time_us=1000000\n"])
        self.stderr = iter([])
        target = Path(cmd[-1])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x" * 20000)

    def wait(self):
        return 0

    def poll(self):
        return 0

    def kill(self):
        self.returncode = -1


def _probe(_path):
    return {"width": 1920, "height": 1080, "duration": 60.0, "fps": 30.0,
            "has_audio": True, "sample_rate": 48000, "audio_streams": []}


class CapabilitiesTest(unittest.TestCase):
    def setUp(self):
        config._caps_cache = None
        self.old = config._caps_cache

    def tearDown(self):
        config._caps_cache = self.old

    def _caps(self, version: str, filters: str):
        done = subprocess.CompletedProcess([], 0, version + "\n", "")
        found = subprocess.CompletedProcess([], 0, filters + "\n", "")
        with mock.patch.object(config, "ffmpeg", lambda: "ffmpeg"), \
             mock.patch("subprocess.run", side_effect=[done, found]):
            return config.ffmpeg_capabilities()

    def test_modern_ffmpeg_has_normalize(self):
        caps = self._caps(
            "ffmpeg version 9.0.2-essentials",
            " TSC ass               V->V       Render ASS subtitles\n"
            " ..A loudnorm          A->A       EBU R128 loudness normalization")
        self.assertTrue(caps["amix_normalize"])
        self.assertTrue(caps["ass"])
        self.assertTrue(caps["loudnorm"])
        self.assertIn("9.0.2", caps["version"])

    def test_old_ffmpeg_lacks_normalize(self):
        caps = self._caps("ffmpeg version 4.3.1 Copyright", " TSC ass V->V")
        self.assertFalse(caps["amix_normalize"])
        self.assertTrue(caps["ass"])
        self.assertFalse(caps["loudnorm"])


class AmixFilterTest(unittest.TestCase):
    def test_normalize_zero_when_supported(self):
        filt = render._amix_filter(True)
        self.assertIn("amix=inputs=2:duration=first:dropout_transition=0", filt)
        self.assertIn("normalize=0", filt)
        self.assertNotIn("loudnorm", filt)

    def test_weights_and_loudnorm_on_old_ffmpeg(self):
        filt = render._amix_filter(False)
        self.assertIn("weights='1 1'", filt)
        self.assertIn("loudnorm=I=-14", filt)

    def test_render_command_uses_capability(self):
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            src = workdir / "src.mp4"
            src.write_bytes(b"x" * 100)
            music = workdir / "music.mp3"
            music.write_bytes(b"x" * 100)
            for supported, expected in ((True, "normalize=0"), (False, "weights='1 1'")):
                with mock.patch.object(render, "probe", _probe), \
                     mock.patch.object(render, "probe_audio", lambda _p: {"has_audio": True,
                                                                           "duration": 60.0}), \
                     mock.patch.object(render, "_measure_loudness", lambda *a, **k: None), \
                     mock.patch.object(render, "hw_encoder", lambda: None), \
                     mock.patch.object(render, "ffmpeg_capabilities",
                                       lambda: {"amix_normalize": supported}), \
                     mock.patch.object(render, "subprocess") as sub:
                    sub.Popen.side_effect = FakeProc
                    sub.PIPE = -1
                    render.render_clip(src, 0.0, 10.0, workdir / "out.mp4",
                                       music_path=music)
                    graph = sub.Popen.call_args.args[0]
                    graph = graph[graph.index("-filter_complex") + 1]
                self.assertIn(expected, graph)


if __name__ == "__main__":
    unittest.main()