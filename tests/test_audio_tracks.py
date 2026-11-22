"""Выбор вшитых аудиодорожек: парсинг ffmpeg и команды рендера."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vertcut import utils

SAMPLE = """
Input #0, matroska,webm, from 'source.mkv':
  Duration: 00:01:38.10, start: 0.000000, bitrate: 5432 kb/s
  Stream #0:0: Video: h264 (High), yuv420p(progressive), 1920x1080, 23.98 fps
  Stream #0:1(jpn): Audio: flac, 48000 Hz, stereo, s32 (24 bit)
  Stream #0:2(rus): Audio: aac (LC), 44100 Hz, stereo, fltp (default)
"""


class AudioStreamParseTest(unittest.TestCase):
    def test_parses_languages_and_tracks(self):
        tracks = utils.parse_audio_streams(SAMPLE)
        self.assertEqual(len(tracks), 2)
        self.assertEqual(tracks[0]["index"], 0)
        self.assertEqual(tracks[0]["stream"], 1)
        self.assertEqual(tracks[0]["language"], "jpn")
        self.assertEqual(tracks[0]["codec"], "flac")
        self.assertEqual(tracks[0]["sample_rate"], 48000)
        self.assertFalse(tracks[0]["default"])
        self.assertEqual(tracks[1]["index"], 1)
        self.assertEqual(tracks[1]["language"], "rus")
        self.assertEqual(tracks[1]["sample_rate"], 44100)
        self.assertTrue(tracks[1]["default"])

    def test_default_falls_back_to_first_track(self):
        tracks = utils.parse_audio_streams(
            "  Stream #0:1(jpn): Audio: flac, 48000 Hz, stereo\n")
        self.assertTrue(tracks[0]["default"])

    def test_probe_uses_default_track_sample_rate(self):
        proc = subprocess.CompletedProcess([], 0, "", SAMPLE)
        with mock.patch.object(utils, "run", return_value=proc):
            info = utils.probe(Path("source.mkv"))
        self.assertTrue(info["has_audio"])
        self.assertEqual(info["sample_rate"], 44100)
        self.assertEqual(len(info["audio_streams"]), 2)

    def test_asr_extraction_maps_selected_track(self):
        calls = []

        def fake(cmd, timeout=None):
            calls.append(cmd)
            Path(cmd[-1]).write_bytes(b"x" * 32)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        with tempfile.TemporaryDirectory() as tmp:
            dst = Path(tmp) / "audio.wav"
            with mock.patch.object(utils, "run", side_effect=fake):
                utils.extract_asr_audio(Path("source.mkv"), dst, audio_track=1)
        self.assertTrue(calls)
        cmd = calls[0]
        self.assertIn("-map", cmd)
        self.assertEqual(cmd[cmd.index("-map") + 1], "0:a:1")


if __name__ == "__main__":
    unittest.main()
