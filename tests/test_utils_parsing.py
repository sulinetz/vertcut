"""Парсеры субтитров и дорожек: цифры в тексте, MM:SS, «плывущие» строки."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vertcut import utils


class SrtTest(unittest.TestCase):
    def test_numeric_lines_survive(self):
        raw = ("1\n00:00:01,000 --> 00:00:02,000\n1990\n\n"
               "2\n00:00:03,000 --> 00:00:04,500\n42\nи ещё\n")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.srt"
            path.write_text(raw, encoding="utf-8")
            segs = utils.parse_srt(path)
        self.assertEqual(len(segs), 2)
        self.assertEqual(segs[0]["text"], "1990")
        self.assertEqual(segs[1]["text"], "42 и ещё")


class VttTest(unittest.TestCase):
    def test_short_timestamps_and_rolling_lines(self):
        raw = ("WEBVTT\n\n"
               "00:01.000 --> 00:03.000\nпривет\n\n"
               "00:02.500 --> 00:04.500\nпривет мир\n\n"
               "00:04.000 --> 00:06.000\nпривет мир как дела\n")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.vtt"
            path.write_text(raw, encoding="utf-8")
            segs = utils.parse_vtt(path)
        self.assertEqual(len(segs), 1, f"плывущие строки не схлопнулись: {segs}")
        self.assertEqual(segs[0]["text"], "привет мир как дела")
        self.assertAlmostEqual(segs[0]["start"], 1.0, places=2)
        self.assertAlmostEqual(segs[0]["end"], 6.0, places=2)
        words = [w["word"] for w in segs[0]["words"]]
        self.assertEqual(words, ["привет", "мир", "как", "дела"])

    def test_classic_hours_still_parse(self):
        raw = "WEBVTT\n\n00:00:01.500 --> 00:00:02.000\nтекст\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "b.vtt"
            path.write_text(raw, encoding="utf-8")
            segs = utils.parse_vtt(path)
        self.assertEqual(len(segs), 1)
        self.assertAlmostEqual(segs[0]["start"], 1.5, places=2)


class SubtitleStreamTest(unittest.TestCase):
    def test_language_after_hex_tag(self):
        text = (
            "  Stream #0:1[0x2](rus): Subtitle: subrip (default)\n"
            "  Stream #0:2[0x3]: Subtitle: hdmv_pgs_subtitle\n"
        )
        proc = mock.Mock(returncode=0, stdout="", stderr=text)
        with mock.patch.object(utils, "run", return_value=proc):
            tracks = utils.subtitle_streams(Path("x.mkv"))
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]["language"], "rus")
        self.assertEqual(tracks[0]["index"], 0)


if __name__ == "__main__":
    unittest.main()