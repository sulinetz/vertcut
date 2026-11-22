"""Чистый экспорт, частота кадров и дедупликация повторов."""
from __future__ import annotations

import unittest

from vertcut import analyze, pipeline


class DedupTest(unittest.TestCase):
    def test_same_chorus_is_detected(self):
        self.assertTrue(analyze._text_similar(
            "Girls, big girls, if we do what we want",
            "girls big girls if we do what we want"))

    def test_different_text_is_kept(self):
        self.assertFalse(analyze._text_similar(
            "Почему люди боятся начать своё дело",
            "Сегодня поговорим про монтаж и цветокоррекцию"))

    def test_empty_is_not_similar(self):
        self.assertFalse(analyze._text_similar("", "что-то"))


class ExportFpsOptionsTest(unittest.TestCase):
    def test_defaults(self):
        opts = pipeline.normalize_options({})
        self.assertTrue(opts["keep_fps"])
        self.assertFalse(opts["export_subs"])

    def test_switches(self):
        opts = pipeline.normalize_options({"keep_fps": False, "export_subs": True})
        self.assertFalse(opts["keep_fps"])
        self.assertTrue(opts["export_subs"])


class StyleOptionsTest(unittest.TestCase):
    def test_defaults(self):
        opts = pipeline.normalize_options({})
        self.assertEqual(opts["look"], "none")
        self.assertEqual(opts["zoom"], 100)
        self.assertFalse(opts["vignette"])

    def test_clamps(self):
        self.assertEqual(pipeline.normalize_options({"zoom": 500})["zoom"], 120)
        self.assertEqual(pipeline.normalize_options({"zoom": 50})["zoom"], 100)
        self.assertEqual(pipeline.normalize_options({"music_volume": 99})["music_volume"], 50)
        self.assertEqual(pipeline.normalize_options({"look": "bogus"})["look"], "none")


if __name__ == "__main__":
    unittest.main()
