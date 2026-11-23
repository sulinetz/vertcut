"""Экспорт SRT живёт в шкале готового ролика, а не источника."""
from __future__ import annotations

import re
import unittest
from unittest import mock

from vertcut import main, pipeline, subtitles

CLIP = {
    "id": "c1", "idx": 0, "start": 10.0, "end": 20.0,
    "title": "Клип", "hook": "", "caption": "", "words": [
        {"word": "первое", "start": 10.2, "end": 11.0},
        {"word": "второе", "start": 15.0, "end": 16.0},
    ],
    "settings": {"jump_cuts": True, "speed": 1.0},
}


def _stamps(body: str):
    return re.findall(r"(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})", body)


def _secs(stamp: str) -> float:
    h, m, rest = stamp.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


class SrtTimelineTest(unittest.TestCase):
    def test_jump_cut_srt_is_relative_to_clip(self):
        data = pipeline.clip_timeline(CLIP, CLIP["settings"])
        body = subtitles.to_srt(data["words"], data["base"], data["base"] + data["length"])
        stamps = _stamps(body)
        self.assertTrue(stamps)
        self.assertTrue(all(_secs(a) >= 0 for a, _b in stamps))
        self.assertLess(max(_secs(b) for _a, b in stamps), 2.5)

    def test_speed_compresses_timeline(self):
        clip = {**CLIP, "settings": {"jump_cuts": False, "speed": 1.1}}
        data = pipeline.clip_timeline(clip, clip["settings"])
        body = subtitles.to_srt(data["words"], data["base"], data["base"] + data["length"])
        stamps = _stamps(body)
        self.assertTrue(stamps)
        self.assertLess(max(_secs(b) for _a, b in stamps), 10.0 / 1.1 + 0.05)

    def test_endpoint_uses_clip_timeline(self):
        with mock.patch.object(main.db, "get_clip", lambda _c: dict(CLIP)):
            response = main.clip_srt("c1")
        body = response.body.decode("utf-8")
        stamps = _stamps(body)
        self.assertTrue(stamps)
        self.assertLess(max(_secs(b) for _a, b in stamps), 2.5,
                        "SRT не должен начинаться с 10-й секунды источника")


if __name__ == "__main__":
    unittest.main()