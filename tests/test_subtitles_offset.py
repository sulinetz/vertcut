"""Сдвиг субтитров: от нижнего края кадра до верхнего, но не за кадр."""
from __future__ import annotations

import re
import unittest

from vertcut import main, pipeline, subtitles


class OffsetRangeTest(unittest.TestCase):
    def test_normalize_options_accepts_full_frame(self):
        self.assertEqual(pipeline.normalize_options({"sub_offset": 9999})["sub_offset"], 1600)
        self.assertEqual(pipeline.normalize_options({"sub_offset": -9999})["sub_offset"], -1600)

    def test_clip_edit_accepts_full_frame(self):
        data = main._clean_clip_edit(main.ClipEdit(sub_offset=9999))
        self.assertEqual(data["sub_offset"], 1600)
        data = main._clean_clip_edit(main.ClipEdit(sub_offset=-9999))
        self.assertEqual(data["sub_offset"], -1600)

    def test_any_position_stays_inside_frame(self):
        for position in subtitles.POSITIONS:
            for offset in (-1600, -800, 0, 800, 1600):
                _anchor, _x, y = subtitles._pos_parts(position, offset, "universal")
                self.assertGreaterEqual(y, 40, (position, offset))
                self.assertLessEqual(y, subtitles.PLAY_H - 40, (position, offset))

    def test_bottom_position_reaches_both_edges(self):
        _a, _x, low = subtitles._pos_parts("bottom", -1600, "universal")
        _a, _x, high = subtitles._pos_parts("bottom", 1600, "universal")
        self.assertGreater(low, high)
        self.assertLessEqual(high, 120, "положительный сдвиг обязан довести до верха")
        self.assertGreaterEqual(low, 1700, "отрицательный сдвиг обязан довести до низа")

    def test_top_position_reaches_bottom(self):
        _a, _x, low = subtitles._pos_parts("top", -1600, "universal")
        self.assertGreaterEqual(low, 1700)

    def test_ass_event_uses_clamped_y(self):
        words = [{"word": "привет", "start": 0.0, "end": 1.0}]
        body = subtitles.build_ass(words, 0.0, 2.0, sub_size=118, position="bottom",
                                   offset=1600, show_hook=False)
        positions = [int(m.group(2)) for m in re.finditer(r"\\pos\((\d+),(\d+)\)", body)]
        self.assertTrue(positions)
        self.assertTrue(all(0 < y < subtitles.PLAY_H for y in positions), positions)


if __name__ == "__main__":
    unittest.main()