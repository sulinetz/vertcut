"""Чёрные окна вставок: субтитры не висят над рекламой."""
from __future__ import annotations

import re

from vertcut import subtitles


def _times(text: str):
    out = []
    for line in text.splitlines():
        if not line.startswith("Dialogue: 0"):
            continue
        parts = line.split(",", 3)
        start = parts[1]
        end = parts[2]
        def sec(stamp):
            h, m, s = stamp.split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
        out.append((sec(start), sec(end)))
    return out


def test_blackout_hides_subtitles():
    words = [{"word": "до", "start": 0.2, "end": 1.2},
             {"word": "после", "start": 2.2, "end": 3.2}]
    text = subtitles.build_ass(words, 0.0, 6.0, show_hook=False,
                               blackouts=[(2.0, 4.0)])
    for start, end in _times(text):
        assert not (start < 4.0 and end > 2.0), (start, end)


def test_no_blackouts_keeps_old_output():
    words = [{"word": "слово", "start": 0.2, "end": 1.2}]
    a = subtitles.build_ass(words, 0.0, 6.0, show_hook=False)
    b = subtitles.build_ass(words, 0.0, 6.0, show_hook=False, blackouts=[])
    assert a == b
