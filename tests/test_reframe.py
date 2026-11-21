"""Тесты кадрирования: лицо в кадре, границы окна, плавность и фолбэк без лиц."""
from __future__ import annotations

import unittest
from pathlib import Path

from viralcut import reframe

STOCK = Path("docs/promo/live-action/stock")


class CropPathTest(unittest.TestCase):
    def _path(self, name: str, duration: float = 6.0):
        src = STOCK / name
        if not src.exists():
            self.skipTest(f"нет файла {src}")
        return reframe.build_crop_path(src, 0.0, duration, aspect="9:16")

    def test_bounds_and_shape(self):
        path = self._path("52175-1080.mp4")
        self.assertIsNotNone(path)
        self.assertGreater(len(path["x"]), 3)
        self.assertEqual(len(path["x"]), len(path["y"]))
        self.assertEqual(len(path["x"]), len(path["times"]))
        src_w, src_h = path["source"]
        for x, y in zip(path["x"], path["y"]):
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x + path["crop_w"], src_w + 0.5)
            self.assertLessEqual(y + path["crop_h"], src_h + 0.5)

    def test_detects_faces(self):
        path = self._path("52175-1080.mp4")
        self.assertGreater(path["coverage"], 0.6, "лица в этом клипе видны почти всегда")

    def test_smooth_on_multi_person_shot(self):
        path = self._path("2948-1080.mp4", duration=20.0)
        jumps = [abs(path["x"][i + 1] - path["x"][i]) for i in range(len(path["x"]) - 1)]
        self.assertLess(max(jumps), 120.0, "окно не должно перескакивать между людьми")

    def test_no_faces_center_fallback(self):
        path = self._path("308-1080.mp4")
        self.assertEqual(path["coverage"], 0.0)
        xs = set(path["x"])
        self.assertEqual(len(xs), 1, "без лиц окно стоит по центру")


if __name__ == "__main__":
    unittest.main(verbosity=2)
