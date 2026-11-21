"""Готовые субтитры и ровная нарезка."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from vertcut import pipeline, utils


class SubtitleParseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_srt(self):
        path = self.dir / "a.srt"
        path.write_text(
            "1\n00:00:01,000 --> 00:00:03,500\nПривет мир\n\n"
            "2\n00:00:04,000 --> 00:00:06,000\nВторой текст\n",
            encoding="utf-8")
        segs = utils.parse_srt(path)
        self.assertEqual(len(segs), 2)
        self.assertEqual(segs[0]["text"], "Привет мир")
        self.assertAlmostEqual(segs[0]["start"], 1.0)
        self.assertAlmostEqual(segs[0]["end"], 3.5)
        self.assertEqual([w["word"] for w in segs[0]["words"]], ["Привет", "мир"])
        self.assertLess(segs[0]["words"][0]["end"], segs[0]["words"][1]["end"])

    def test_ass(self):
        path = self.dir / "a.ass"
        path.write_text(
            "[Script Info]\nScriptType: v4.00+\n\n[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            "Dialogue: 0,0:00:02.50,0:00:05.00,Default,,0,0,0,,{\\i1}Японский текст{\\i0}\n",
            encoding="utf-8")
        segs = utils.parse_ass(path)
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0]["text"], "Японский текст")
        self.assertAlmostEqual(segs[0]["start"], 2.5)
        self.assertAlmostEqual(segs[0]["end"], 5.0)

    def test_dispatch_by_content(self):
        path = self.dir / "unknown.txt"
        path.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nТест\n", encoding="utf-8")
        segs = utils.parse_subtitles(path)
        self.assertTrue(segs)
        self.assertEqual(segs[0]["text"], "Тест")


class EvenSplitTest(unittest.TestCase):
    def test_equal_parts(self):
        found = pipeline._even_segments(120.0, {"count": 4, "target_dur": 30,
                                                "min_dur": 5, "max_dur": 60}, None)
        self.assertEqual(len(found), 4)
        self.assertAlmostEqual(found[0]["start"], 0.0)
        self.assertAlmostEqual(found[0]["end"], 30.0)
        self.assertAlmostEqual(found[-1]["end"], 120.0)
        self.assertEqual(found[0]["title"], "Часть 1")

    def test_respects_max_duration(self):
        found = pipeline._even_segments(600.0, {"count": 2, "target_dur": 30,
                                                "min_dur": 5, "max_dur": 60}, None)
        for clip in found:
            self.assertLessEqual(clip["end"] - clip["start"], 60.5)

    def test_words_are_sliced_from_transcript(self):
        transcript = {"segments": [
            {"start": 0.0, "end": 25.0, "text": "a",
             "words": [{"word": "a", "start": 1.0, "end": 2.0}]},
            {"start": 40.0, "end": 50.0, "text": "b",
             "words": [{"word": "b", "start": 41.0, "end": 42.0}]},
        ]}
        found = pipeline._even_segments(60.0, {"count": 2, "target_dur": 30,
                                              "min_dur": 5, "max_dur": 60}, transcript)
        self.assertEqual([w["word"] for w in found[0]["words"]], ["a"])
        self.assertEqual([w["word"] for w in found[1]["words"]], ["b"])


class SelectOptionTest(unittest.TestCase):
    def test_default_and_validation(self):
        self.assertEqual(pipeline.normalize_options({})["select"], "smart")
        self.assertEqual(pipeline.normalize_options({"select": "even"})["select"], "even")
        self.assertEqual(pipeline.normalize_options({"select": "bogus"})["select"], "smart")

    def test_subtitle_source_validation(self):
        self.assertEqual(pipeline.normalize_options({})["subtitle_source"], "auto")
        self.assertEqual(pipeline.normalize_options(
            {"subtitle_source": "whisper"})["subtitle_source"], "whisper")
        self.assertEqual(pipeline.normalize_options(
            {"subtitle_source": "x"})["subtitle_source"], "auto")


if __name__ == "__main__":
    unittest.main()
