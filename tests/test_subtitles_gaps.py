"""Сдвиг строк при межстрочном интервале: караоке не сбивается."""
from __future__ import annotations

import re
import unittest

from vertcut import subtitles


class LineGapKaraokeTest(unittest.TestCase):
    def test_next_line_gets_cumulative_karaoke_prefix(self):
        lines = ["{\\k120}ПЕРВАЯ", "{\\k80}ВТОРАЯ"]
        events = subtitles._line_events(lines, 0, "Sub", 1.0, 4.0, 2, 540, 1500,
                                        60.0, 40.0, "")
        self.assertEqual(len(events), 2)
        self.assertNotIn("{\\k0}", events[0])
        self.assertIn("{\\k120}{\\k80}ВТОРАЯ", events[1])

    def test_three_lines_accumulate_all_previous(self):
        lines = ["{\\k100}А", "{\\k200}Б", "{\\k300}В"]
        events = subtitles._line_events(lines, 0, "Sub", 0.0, 5.0, 2, 540, 1500,
                                        60.0, 40.0, "")
        self.assertIn("{\\k100}{\\k200}Б", events[1])
        self.assertIn("{\\k300}{\\k300}В", events[2])

    def test_no_gap_stays_one_event(self):
        lines = ["{\\k120}ПЕРВАЯ", "{\\k80}ВТОРАЯ"]
        events = subtitles._line_events(lines, 0, "Sub", 1.0, 4.0, 2, 540, 1500,
                                        60.0, 0.0, "")
        self.assertEqual(len(events), 1)
        self.assertIn("\\N", events[0])
        self.assertNotIn("{\\k120}{\\k80}", events[0])

    def test_hook_lines_without_karaoke_are_untouched(self):
        events = subtitles._line_events(["ХУК", "ВТОРАЯ"], 1, "Hook", 0.0, 1.0, 8,
                                        540, 300, 60.0, 40.0, "")
        self.assertEqual(events[1].split(",,", 1)[1].count("{\\k"), 0)


if __name__ == "__main__":
    unittest.main()