"""Фильтры локального отбора: настроение, тип контента и min_score.

Пустые фильтры обязаны давать прежний список, иначе старые проекты изменятся.
"""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from vertcut import analyze


def make_segment(sentences, step=0.32, pause=0.45, start_at=0.0):
    words = []
    t = start_at
    for sentence in sentences:
        for token in sentence.split():
            dur = max(0.16, step * (1 + 0.05 * len(token)))
            words.append({"word": token, "start": round(t, 3), "end": round(t + dur, 3)})
            t += dur
        t += pause
    return [{"start": words[0]["start"], "end": words[-1]["end"],
             "text": " ".join(w["word"] for w in words), "words": words}]


SENTENCES = [
    "Сегодня поговорим про запуск продукта.",
    "Это было смешно, честная шутка про команду.",
    "Оказывается, я понял главный вывод за неделю.",
    "Мы потеряли всё за один день, это была драма.",
    "Никто не ожидал такого шока и безумного результата.",
    "Мы выросли в десять раз за месяц.",
    "И знаете, что самое важное?",
    "Мы не потратили ни рубля на рекламу.",
    "Однажды я рассказал эту историю другу.",
    "В итоге всё закончилось хорошо.",
    "Вот почему мы переписали приложение с нуля.",
    "Результат превзошёл ожидания.",
]


def _find(**kwargs):
    raw = make_segment(SENTENCES)
    duration = raw[0]["end"] + 1
    with mock.patch.object(analyze, "energy_curve", return_value=([], -30.0)):
        return analyze.find_segments(
            raw, Path("dummy.mp4"), duration,
            count=6, min_dur=8, max_dur=40, target_dur=18, **kwargs)


def test_empty_filters_keep_the_old_result():
    baseline = _find()
    assert baseline
    for kwargs in ({"min_score": 0.0},
                   {"mood_filter": []},
                   {"type_filter": []},
                   {"mood_filter": [], "type_filter": [], "min_score": 0.0}):
        assert _find(**kwargs) == baseline


def test_min_score_rejects_everything_above_the_best():
    baseline = _find()
    best = max(clip["score"] for clip in baseline)
    assert _find(min_score=min(1.0, best + 0.01)) == []
    assert _find(min_score=0.0) == baseline


def test_mood_filter_keeps_only_matching_clips():
    baseline = _find()
    present = {clip["mood"] for clip in baseline if clip["mood"]}
    assert present, "хотя бы один клип должен получить настроение"
    wanted = sorted(present)[0]
    filtered = _find(mood_filter=[wanted])
    assert filtered
    assert all(clip["mood"] == wanted for clip in filtered)
    absent = sorted(set(analyze.MOODS) - present)
    if absent:
        assert _find(mood_filter=[absent[0]]) == []


def test_type_filter_keeps_only_matching_clips():
    baseline = _find()
    present = {kind for clip in baseline for kind in clip["content_types"]}
    assert present, "тип контента должен определяться локально"
    wanted = sorted(present)[0]
    filtered = _find(type_filter=[wanted])
    assert filtered
    assert all(wanted in clip["content_types"] for clip in filtered)


def test_unknown_filter_values_are_ignored():
    baseline = _find()
    assert _find(mood_filter=["нет-такого"]) == baseline
    assert _find(type_filter=["нет-такого"]) == baseline


def test_candidates_carry_description_fields():
    for clip in _find():
        assert clip["mood"] in ("", *analyze.MOODS)
        assert isinstance(clip["content_types"], list)
        assert len(clip["content_types"]) <= 3
        assert set(clip["content_types"]) <= set(analyze.CONTENT_TYPES)
        assert clip["why"].strip()


@pytest.mark.parametrize("text,expected", [
    ("Это было смешно, шутка за шуткой", "funny"),
    ("Оказывается, я понял главный вывод", "insight"),
    ("Это был конфликт и громкий скандал", "drama"),
    ("Мы потеряли всё, было очень грустно", "sad"),
    ("Обычная фраза без маркеров", ""),
])
def test_classify_mood(text, expected):
    assert analyze._classify_mood(text) == expected


def test_classify_types_caps_at_three():
    kinds = analyze._classify_types(
        "Однажды я рассказал историю, это была шутка про конфликт и вывод.")
    assert 1 <= len(kinds) <= 3
    assert set(kinds) <= set(analyze.CONTENT_TYPES)


def test_old_positional_call_still_works():
    raw = make_segment(SENTENCES)
    with mock.patch.object(analyze, "energy_curve", return_value=([], -30.0)):
        clips = analyze.find_segments(raw, Path("dummy.mp4"), raw[0]["end"] + 1,
                                      6, 8, 40, 18, "tiktok")
    assert clips
    assert all(clip["caption"] for clip in clips)


def test_platform_does_not_change_existing_output():
    """`platform` уже применяется к безопасным зонам субтитров, но не к подписи.

    Пробрасываем его ради полноты: поведение для старых проектов не меняется.
    """
    assert _find(platform="tiktok") == _find(platform="shorts") == _find()


def test_normalize_options_validates_type_filter():
    from vertcut import pipeline

    opts = pipeline.normalize_options(
        {"type_filter": ["story", "мусор", "HUMOR", "story"]})
    assert opts["type_filter"] == ["story", "humor"]
    assert pipeline.normalize_options({})["type_filter"] == []
    assert pipeline.normalize_options({"type_filter": "story, fact"})["type_filter"] == [
        "story", "fact"]

