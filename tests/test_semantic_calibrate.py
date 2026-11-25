"""Семантика: проверка индексов по чанку, типы контента и общий рейтинг."""
from __future__ import annotations

import json

import pytest

from vertcut import app_settings, semantic


def _sents(count: int, step: float = 4.0) -> list:
    return [{"start": i * step, "end": (i + 1) * step,
             "text": f"Предложение номер {i} про деньги и ошибки.",
             "words": [{"word": f"слово{i}", "start": i * step, "end": (i + 1) * step}],
             "conf": -0.2}
            for i in range(count)]


def _item(start: int, end: int, score: float = 0.5, **extra) -> dict:
    data = {"from": start, "to": end, "score": score, "mood": "insight",
            "types": ["story"], "title": "Заголовок", "why": "Потому что"}
    data.update(extra)
    return data


def test_prompt_version_bumped():
    assert semantic.PROMPT_VERSION >= 2


def test_indices_from_another_chunk_are_rejected():
    payload = {"clips": [_item(0, 1), _item(40, 41)]}
    cleaned = semantic._clean_items(payload, total=100, limit=60, allowed={0, 1, 2})
    assert [item["from"] for item in cleaned] == [0]


def test_allowed_none_keeps_old_behaviour():
    payload = {"clips": [_item(0, 1), _item(40, 41)]}
    assert len(semantic._clean_items(payload, 100, 60)) == 2


def test_clean_types_whitelist_and_aliases():
    assert semantic._clean_types("история, юмор, мусор") == ["story", "humor"]
    assert semantic._clean_types(["provocation", "nonsense", "insight"]) == [
        "provocation", "insight"]
    assert len(semantic._clean_types(["story", "humor", "conflict", "fact"])) == 3
    assert semantic._clean_types(None) == []


def test_clean_items_carries_types():
    cleaned = semantic._clean_items({"clips": [_item(0, 1, types=["fact", "bad"])]}, 10, 60)
    assert cleaned[0]["types"] == ["fact"]


def test_clean_ranking_parses_and_ignores_out_of_range():
    rows = semantic._clean_ranking(
        {"clips": [{"id": 0, "score": 0.9}, {"id": 99, "score": 0.8},
                   {"id": 2, "score": 1.5}, 3]}, size=4)
    assert [row["id"] for row in rows] == [0, 2, 3]
    assert rows[1]["score"] == 1.0
    assert rows[2]["score"] == -1.0


def test_calibrate_applies_new_scores(monkeypatch, tmp_path):
    sents = _sents(12)
    items = [_item(0, 1, 0.9), _item(2, 3, 0.8), _item(4, 5, 0.7), _item(6, 7, 0.6)]
    answer = {"clips": [{"id": 3, "score": 0.95}, {"id": 0, "score": 0.2},
                        {"id": 1, "score": 0.5}, {"id": 2, "score": 0.4}]}
    monkeypatch.setattr(semantic, "_chat", lambda *a, **kw: (json.dumps(answer), {}))
    out = semantic._calibrate("deepseek", sents, items, 60.0, {}, tmp_path)
    scores = {(item["from"], item["to"]): item["score"] for item in out}
    assert scores[(6, 7)] == 0.95
    assert scores[(0, 1)] == 0.2
    # исходный список не мутируется
    assert items[0]["score"] == 0.9


def test_calibrate_falls_back_on_error(monkeypatch, tmp_path):
    sents = _sents(12)
    items = [_item(0, 1, 0.9), _item(2, 3, 0.8), _item(4, 5, 0.7)]

    def boom(*args, **kwargs):
        raise semantic.LLMError("нет сети", 503)

    monkeypatch.setattr(semantic, "_chat", boom)
    out = semantic._calibrate("deepseek", sents, items, 60.0, {}, tmp_path)
    assert [item["score"] for item in out] == [0.9, 0.8, 0.7]


def test_calibrate_is_cached(monkeypatch, tmp_path):
    sents = _sents(12)
    items = [_item(0, 1, 0.9), _item(2, 3, 0.8), _item(4, 5, 0.7)]
    calls = {"n": 0}

    def once(*args, **kwargs):
        calls["n"] += 1
        return json.dumps({"clips": [{"id": 0, "score": 0.9}]}), {}

    monkeypatch.setattr(semantic, "_chat", once)
    semantic._calibrate("deepseek", sents, items, 60.0, {}, tmp_path)
    semantic._calibrate("deepseek", sents, items, 60.0, {}, tmp_path)
    assert calls["n"] == 1


def test_cache_key_separates_type_filters():
    sents = _sents(6)
    base = {"count": 5, "min_dur": 15, "max_dur": 60, "target_dur": 30}
    key_a = semantic._cache_key("deepseek", sents, 100.0, {**base, "type_filter": []})
    key_b = semantic._cache_key("deepseek", sents, 100.0,
                                {**base, "type_filter": ["story"]})
    assert key_a != key_b


def test_model_for_is_used_in_keys(monkeypatch):
    sents = _sents(6)
    opts = {"count": 5, "min_dur": 15, "max_dur": 60, "target_dur": 30}
    monkeypatch.setattr(app_settings, "model_for", lambda provider: "one")
    key_a = semantic._cache_key("deepseek", sents, 100.0, opts)
    monkeypatch.setattr(app_settings, "model_for", lambda provider: "two")
    key_b = semantic._cache_key("deepseek", sents, 100.0, opts)
    assert key_a != key_b


@pytest.mark.parametrize("size", [0, 1, 2])
def test_calibrate_skips_tiny_lists(size):
    sents = _sents(6)
    items = [_item(i, i + 1, 0.5) for i in range(size)]
    assert semantic._calibrate("deepseek", sents, items, 60.0, {}, None) == items
