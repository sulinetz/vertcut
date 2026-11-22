"""Межстрочный интервал в ASS-субтитрах."""
from __future__ import annotations

import re
import unittest

from vertcut import subtitles


def words(n: int = 12):
    return [{"word": f"слово{i}", "start": i * 0.25, "end": i * 0.25 + 0.22}
            for i in range(n)]


def sub_events(ass: str):
    return [ln for ln in ass.splitlines() if ln.startswith("Dialogue: 0,")]


def pos_y(line: str) -> int:
    m = re.search(r"\\pos\(\d+,(-?\d+)\)", line)
    return int(m.group(1)) if m else 0


class LineGapTest(unittest.TestCase):
    def test_default_keeps_single_event(self):
        ass = subtitles.build_ass(words(), 0.0, 4.0, sub_size=180,
                                  show_hook=False, line_gap=0)
        events = sub_events(ass)
        self.assertTrue(events)
        self.assertTrue(any("\\N" in e for e in events))

    def test_gap_splits_lines_with_different_y(self):
        ass = subtitles.build_ass(words(), 0.0, 4.0, sub_size=180,
                                  show_hook=False, line_gap=40)
        events = sub_events(ass)
        self.assertGreaterEqual(len(events), 2)
        ys = {pos_y(e) for e in events}
        self.assertGreaterEqual(len(ys), 2)
        self.assertFalse(any("\\N" in e for e in events))

    def test_gap_is_clamped(self):
        ass = subtitles.build_ass(words(), 0.0, 4.0, sub_size=180,
                                  show_hook=False, line_gap=1000)
        self.assertIn("Dialogue", ass)


class LineGapOptionsTest(unittest.TestCase):
    def test_normalize_clamps(self):
        from vertcut import pipeline

        self.assertEqual(pipeline.normalize_options({})["line_gap"], 0)
        self.assertEqual(pipeline.normalize_options({"line_gap": 30})["line_gap"], 30)
        self.assertEqual(pipeline.normalize_options({"line_gap": 999})["line_gap"], 120)
        self.assertEqual(pipeline.normalize_options({"line_gap": -5})["line_gap"], 0)


if __name__ == "__main__":
    unittest.main()
