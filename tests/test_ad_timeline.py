"""Вставки рекламы в таймлайн: точки, слова и накладки."""
from __future__ import annotations

from vertcut import timeline


def replace(start: float, duration: float, kind: str = "replace") -> dict:
    return {"id": f"{start}-{duration}", "asset": "a", "kind": kind,
            "start": start, "duration": duration}


def test_insert_spans_no_events():
    result = timeline.insert_spans([(0.0, 10.0)], [])
    assert result["inserts"] == []
    assert result["duration"] == 10.0


def test_insert_spans_maps_source_time_with_speed():
    segments = [(0.0, 10.0)]
    result = timeline.insert_spans(segments, [replace(4.0, 2.0)], speed=2.0)
    insert = result["inserts"][0]
    assert insert["at"] == 2.0
    assert insert["final_start"] == 2.0
    assert result["duration"] == 7.0


def test_insert_spans_inside_removed_pause_snaps_forward():
    # Пауза 2..5 вырезана: точка 3.5 прилипает к началу второй части.
    segments = [(0.0, 2.0), (5.0, 8.0)]
    result = timeline.insert_spans(segments, [replace(3.5, 1.0)])
    assert result["inserts"][0]["at"] == 2.0


def test_multiple_inserts_accumulate():
    result = timeline.insert_spans([(0.0, 10.0)],
                                   [replace(2.0, 1.0), replace(5.0, 2.0)])
    first, second = result["inserts"]
    assert first["final_start"] == 2.0
    assert second["at"] == 5.0
    assert second["final_start"] == 6.0
    assert result["duration"] == 13.0


def test_overlay_time_shift_and_crossing():
    inserts = timeline.insert_spans([(0.0, 10.0)], [replace(4.0, 2.0)])["inserts"]
    # Накладка началась раньше и кончилась позже — растягивается на рекламу.
    assert timeline.inserted_time(2.0, inserts, inclusive=True) == 2.0
    assert timeline.inserted_time(6.0, inserts, inclusive=False) == 8.0
    # Начало ровно во вставке — уже после рекламы.
    assert timeline.inserted_time(4.0, inserts, inclusive=True) == 6.0
    # Конец ровно во вставке — до рекламы.
    assert timeline.inserted_time(4.0, inserts, inclusive=False) == 4.0


def test_insert_words_shifts_and_truncates():
    inserts = timeline.insert_spans([(0.0, 10.0)], [replace(4.0, 2.0)])["inserts"]
    words = [
        {"word": "до", "start": 1.0, "end": 2.0},
        {"word": "на", "start": 3.6, "end": 4.4},  # попала на вставку
        {"word": "после", "start": 5.0, "end": 6.0},
    ]
    out = timeline.insert_words(words, inserts)
    assert out[0] == {"word": "до", "start": 1.0, "end": 2.0}
    assert out[1]["start"] == 3.6
    assert out[1]["end"] == 4.0
    assert out[2]["start"] == 7.0
    assert out[2]["end"] == 8.0


def test_insert_words_without_events_unchanged():
    words = [{"word": "а", "start": 0.0, "end": 1.0}]
    assert timeline.insert_words(words, []) == words
