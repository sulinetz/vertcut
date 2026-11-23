"""Ручное количество нарезок: сервер принимает и 1, и «все»."""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from vertcut import analyze, pipeline


class ManualCountTest(unittest.TestCase):
    def test_one_clip_is_allowed(self):
        self.assertEqual(pipeline.normalize_options({"count": 1})["count"], 1)

    def test_zero_means_all(self):
        self.assertEqual(pipeline.normalize_options({"count": 0})["count"], 0)

    def test_limit_is_200(self):
        self.assertEqual(pipeline.normalize_options({"count": 999})["count"], 200)

    def test_even_split_with_one_clip(self):
        found = pipeline._even_segments(60.0, {"count": 1, "target_dur": 30,
                                               "max_dur": 60, "min_dur": 15}, None)
        self.assertEqual(len(found), 1)
        self.assertAlmostEqual(found[0]["end"] - found[0]["start"], 60.0, places=1)

    def test_smart_search_honours_one(self):
        words = [{"word": "слово", "start": float(i), "end": float(i) + 0.5}
                 for i in range(0, 80, 2)]
        segments = [{"start": 0.0, "end": 80.0, "text": "тест", "words": words}]
        with mock.patch.object(analyze, "energy_curve", lambda *_a, **_k: ([], -30.0)):
            found = analyze.find_segments(segments, Path("x.mp4"),
                                          duration=80.0, count=1, min_dur=8,
                                          max_dur=60, target_dur=20)
        self.assertLessEqual(len(found), 1)
        self.assertEqual(len(found), 1)


if __name__ == "__main__":
    unittest.main()