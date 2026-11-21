"""Безопасные зоны площадок: субтитры и лицо не должны попадать под интерфейс."""
from __future__ import annotations

import re
import unittest

from vertcut import platforms, subtitles


class ZonesTest(unittest.TestCase):
    def test_unknown_platform_falls_back_to_universal(self):
        self.assertEqual(platforms.zones("nope"), platforms.zones(platforms.DEFAULT_PLATFORM))
        self.assertFalse(platforms.is_known("nope"))
        self.assertTrue(platforms.is_known("tiktok"))

    def test_universal_reserves_both_platforms(self):
        z = platforms.zones("universal")
        self.assertGreaterEqual(z["bottom"], platforms.zones("tiktok")["bottom"])
        self.assertGreaterEqual(z["bottom"], platforms.zones("shorts")["bottom"])
        self.assertGreaterEqual(z["right"], platforms.zones("shorts")["right"])

    def test_safe_rect_inside_frame(self):
        x0, y0, x1, y1 = platforms.safe_rect("tiktok")
        self.assertGreaterEqual(x0, 0)
        self.assertGreaterEqual(y0, 0)
        self.assertLessEqual(x1, platforms.PLAY_W)
        self.assertLessEqual(y1, platforms.PLAY_H)
        self.assertEqual(y1, platforms.PLAY_H - platforms.zones("tiktok")["bottom"])

    def test_bottom_text_is_above_interface(self):
        for key in ("universal", "shorts", "tiktok", "reels"):
            y = platforms.bottom_text_y(key)
            limit = platforms.PLAY_H - platforms.zones(key)["bottom"]
            self.assertLessEqual(y, limit, key)
            self.assertGreater(y, 0, key)

    def test_face_box_stays_in_safe_area(self):
        for key in ("universal", "shorts", "tiktok", "reels"):
            x, y, size = platforms.face_box(key, 360)
            _, y0, x1, y1 = platforms.safe_rect(key)
            self.assertGreaterEqual(x, 0, key)
            self.assertGreaterEqual(y, y0, key)
            self.assertLessEqual(x + size, x1, key)
            self.assertLessEqual(y + size, y1, key)


class SubtitlePositionTest(unittest.TestCase):
    words = [{"word": "привет", "start": 0.0, "end": 0.4},
             {"word": "мир", "start": 0.4, "end": 0.9}]

    def _pos_y(self, platform: str, position: str = "bottom") -> int:
        ass = subtitles.build_ass(self.words, 0.0, 2.0, position=position,
                                  platform=platform, show_hook=False)
        match = re.search(r"\\an\d\\pos\(\d+,(\d+)\)", ass)
        self.assertIsNotNone(match, ass[-200:])
        return int(match.group(1))

    def test_tiktok_raises_subtitles_higher_than_none(self):
        self.assertLess(self._pos_y("tiktok"), self._pos_y("none"))

    def test_universal_is_at_least_as_strict_as_shorts(self):
        self.assertLessEqual(self._pos_y("universal"), self._pos_y("shorts"))

    def test_platform_does_not_affect_middle(self):
        self.assertEqual(self._pos_y("tiktok", "middle"), self._pos_y("none", "middle"))


class OptionsTest(unittest.TestCase):
    def test_normalize_defaults_and_validates_platform(self):
        from vertcut import pipeline

        opts = pipeline.normalize_options({})
        self.assertEqual(opts["platform"], platforms.DEFAULT_PLATFORM)
        self.assertEqual(pipeline.normalize_options({"platform": "tiktok"})["platform"], "tiktok")
        self.assertEqual(pipeline.normalize_options({"platform": "bogus"})["platform"],
                         platforms.DEFAULT_PLATFORM)


if __name__ == "__main__":
    unittest.main()
