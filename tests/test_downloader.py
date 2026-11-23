"""Загрузчик: выбор формата, готовые субтитры, прямая загрузка файла."""
from __future__ import annotations

import unittest

from vertcut import downloader

FORMATS = [
    {"format_id": "18", "ext": "mp4", "height": 360, "vcodec": "avc1.42001E",
     "acodec": "mp4a.40.2", "tbr": 600},
    {"format_id": "137", "ext": "mp4", "height": 1080, "vcodec": "avc1.640028",
     "acodec": "none", "tbr": 4500},
    {"format_id": "136", "ext": "mp4", "height": 720, "vcodec": "avc1.4d401f",
     "acodec": "none", "tbr": 2500},
    {"format_id": "140", "ext": "m4a", "height": None, "vcodec": "none",
     "acodec": "mp4a.40.2", "abr": 128},
]


class PickFormatTest(unittest.TestCase):
    def test_height_beats_muxed_audio(self):
        # 18 — 360p со звуком, но нужен 1080p и отдельная дорожка звука
        fmt, height = downloader._pick_format({"formats": FORMATS}, 1080)
        self.assertEqual(fmt, "137+140")
        self.assertEqual(height, 1080)

    def test_limit_picks_best_below_cap(self):
        fmt, height = downloader._pick_format({"formats": FORMATS}, 720)
        self.assertEqual(fmt, "136+140")
        self.assertEqual(height, 720)

    def test_avc1_wins_at_same_height(self):
        formats = list(FORMATS) + [
            {"format_id": "248", "ext": "webm", "height": 1080, "vcodec": "vp9",
             "acodec": "none", "tbr": 4000},
        ]
        fmt, _height = downloader._pick_format({"formats": formats}, 1080)
        self.assertEqual(fmt, "137+140")


if __name__ == "__main__":
    unittest.main()
