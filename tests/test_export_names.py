"""Имена файлов и порядок экспорта клипов."""
from __future__ import annotations

import unittest

from vertcut import pipeline, utils


class SafeFilenameTest(unittest.TestCase):
    def test_keeps_cyrillic_and_spaces(self):
        self.assertEqual(utils.safe_filename("Как насчёт среды?"), "Как насчёт среды")

    def test_strips_forbidden_characters_and_extension(self):
        self.assertEqual(utils.safe_filename('a<b>c:d"e/f\\g|h?i*.mp4'), "a b c d e f g h i")

    def test_reserved_windows_name(self):
        self.assertEqual(utils.safe_filename("CON"), "_CON")
        self.assertEqual(utils.safe_filename("con.mp4"), "_con")

    def test_empty_and_long_names(self):
        self.assertEqual(utils.safe_filename("   ...   "), "clip")
        long_name = "Очень длинное название " * 10
        self.assertLessEqual(len(utils.safe_filename(long_name)), 80)


class NamedExportsTest(unittest.TestCase):
    def setUp(self):
        self.clips = [
            {"id": "a", "idx": 2, "start": 10.0, "score": 0.9,
             "title": "Почему оно такое соленое?"},
            {"id": "b", "idx": 0, "start": 1.0, "score": 0.2,
             "title": "Как насчёт следующей среды?"},
            {"id": "c", "idx": 1, "start": 5.0, "score": 0.5,
             "title": "Почему оно такое соленое?"},
        ]

    def test_chronological_order(self):
        names = utils.named_exports(self.clips, "chrono")
        self.assertEqual([c["id"] for c, _ in names], ["b", "c", "a"])
        self.assertEqual(names[0][1], "01 — Как насчёт следующей среды.mp4")
        self.assertEqual(names[1][1], "02 — Почему оно такое соленое.mp4")
        self.assertEqual(names[2][1], "03 — Почему оно такое соленое.mp4")

    def test_score_order(self):
        names = utils.named_exports(self.clips, "score")
        self.assertEqual([c["id"] for c, _ in names], ["a", "c", "b"])
        self.assertEqual(names[0][1], "01 — Почему оно такое соленое.mp4")
        self.assertEqual(names[1][1], "02 — Почему оно такое соленое.mp4")

    def test_normalize_export_order(self):
        self.assertEqual(pipeline.normalize_options({"export_order": "score"})["export_order"], "score")
        self.assertEqual(pipeline.normalize_options({"export_order": "bad"})["export_order"], "chrono")
        self.assertEqual(pipeline.normalize_options({})["export_order"], "chrono")


if __name__ == "__main__":
    unittest.main()
