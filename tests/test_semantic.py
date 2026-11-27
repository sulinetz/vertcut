"""Выбор моментов нейросетью: мок-ответы, валидация, кэш и откат."""
from __future__ import annotations

import json

import pytest

from vertcut import analyze, app_settings, semantic


def _segment(text: str, start: float, step: float = 0.4) -> dict:
    words = []
    for i, token in enumerate(text.split()):
        words.append({
            "word": token,
            "start": round(start + i * step, 3),
            "end": round(start + (i + 1) * step, 3),
        })
    return {
        "start": words[0]["start"],
        "end": words[-1]["end"],
        "text": text,
        "words": words,
    }


@pytest.fixture
def segments() -> list:
    return [
        _segment("Привет, сегодня поговорим о деньгах.", 0.0),
        _segment("Я потерял всё за один день.", 6.0),
        _segment("Это была самая большая ошибка в моей жизни.", 10.0),
        _segment("Но именно она научила меня главному.", 15.0),
        _segment("Хочешь узнать, что я понял?", 19.0),
        _segment("Подписывайтесь на канал и ставьте лайк.", 23.0),
    ]


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings, "FILE", tmp_path / "app_settings.json")
    for name in ("DEEPSEEK_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
                 "GEMINI_PROXY", "HTTPS_PROXY", "HTTP_PROXY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(app_settings, "api_key", lambda provider: "test-key")
    monkeypatch.setattr(app_settings, "model_for", lambda provider: "test-model")
    monkeypatch.setattr(app_settings, "proxy_for", lambda provider: "")
    yield


def _reply(clips: list) -> dict:
    return {"choices": [{"message": {"content": json.dumps({"clips": clips})}}],
            "usage": {}}


def test_maps_sentences_to_clips(segments, tmp_path, monkeypatch):
    monkeypatch.setattr(semantic, "_post_json", lambda *a, **k: _reply([
        {"from": 1, "to": 3, "score": 0.84, "mood": "sad",
         "title": "Потерял всё за день", "why": "сильная история",
         "hook": 0.8, "conflict": 0.7, "emotion": 0.9, "payoff": 0.8},
    ]))
    opts = {"picker": "deepseek", "count": 1, "min_dur": 5, "max_dur": 40,
            "target_dur": 20, "mood_filter": [], "min_score": 0.0,
            "platform": "shorts"}
    found = semantic.find_segments(segments, tmp_path / "video.mp4", 30.0,
                                   opts=opts, workdir=tmp_path)
    assert found and len(found) == 1
    clip = found[0]
    assert clip["mood"] == "sad"
    assert clip["source"] == "deepseek"
    assert 5.0 <= clip["duration"] <= 40.0
    assert clip["start"] <= segments[1]["start"] + 0.01
    assert clip["title"] == "Потерял всё за день"
    assert clip["parts"]["hook"] == 0.8
    assert clip["caption"]


def test_rejects_out_of_range_and_reversed(segments, tmp_path, monkeypatch):
    monkeypatch.setattr(semantic, "_post_json", lambda *a, **k: _reply([
        {"from": 0, "to": 99, "score": 0.9},
        {"from": 3, "to": 1, "score": 0.9},
        {"from": -2, "to": 2, "score": 0.9},
    ]))
    opts = {"picker": "deepseek", "count": 5, "min_dur": 5, "max_dur": 60,
            "target_dur": 20, "mood_filter": [], "min_score": 0.0}
    assert semantic.find_segments(segments, tmp_path / "v.mp4", 30.0,
                                  opts=opts, workdir=tmp_path) is None


def test_mood_filter_and_min_score(segments, tmp_path, monkeypatch):
    replies = _reply([
        {"from": 1, "to": 2, "score": 0.9, "mood": "funny"},
        {"from": 2, "to": 3, "score": 0.3, "mood": "sad"},
        {"from": 3, "to": 4, "score": 0.8, "mood": "insight"},
    ])
    monkeypatch.setattr(semantic, "_post_json", lambda *a, **k: replies)
    opts = {"picker": "deepseek", "count": 5, "min_dur": 4, "max_dur": 60,
            "target_dur": 20, "mood_filter": ["sad", "insight"], "min_score": 0.5}
    found = semantic.find_segments(segments, tmp_path / "v.mp4", 30.0,
                                   opts=opts, workdir=tmp_path)
    assert found and [clip["mood"] for clip in found] == ["insight"]


def test_cache_prevents_second_request(segments, tmp_path, monkeypatch):
    calls = {"n": 0}

    def fake(*args, **kwargs):
        calls["n"] += 1
        return _reply([{"from": 1, "to": 3, "score": 0.8, "mood": "drama"}])

    monkeypatch.setattr(semantic, "_post_json", fake)
    opts = {"picker": "deepseek", "count": 3, "min_dur": 5, "max_dur": 60,
            "target_dur": 20, "mood_filter": [], "min_score": 0.0}
    first = semantic.find_segments(segments, tmp_path / "v.mp4", 30.0,
                                   opts=opts, workdir=tmp_path)
    second = semantic.find_segments(segments, tmp_path / "v.mp4", 30.0,
                                    opts=opts, workdir=tmp_path)
    assert first and second
    assert calls["n"] == 1
    assert second[0]["mood"] == first[0]["mood"]


def test_network_error_falls_back_to_none(segments, tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise semantic.LLMError("Сеть недоступна")

    monkeypatch.setattr(semantic, "_post_json", boom)
    opts = {"picker": "deepseek", "count": 3, "min_dur": 5, "max_dur": 60,
            "target_dur": 20, "mood_filter": [], "min_score": 0.0}
    assert semantic.find_segments(segments, tmp_path / "v.mp4", 30.0,
                                  opts=opts, workdir=tmp_path) is None


def test_local_picker_never_calls_network(segments, tmp_path, monkeypatch):
    monkeypatch.setattr(semantic, "_post_json",
                        lambda *a, **k: pytest.fail("сеть не должна вызываться"))
    assert semantic.find_segments(segments, tmp_path / "v.mp4", 30.0,
                                  opts={"picker": "local"}, workdir=tmp_path) is None


def test_auto_picker_skips_provider_without_key(segments, tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings, "api_key",
                        lambda provider: "key" if provider == "gemini" else "")
    used = {}

    def fake(url, payload, key, proxy="", timeout=0):
        used["key"] = key
        return _reply([{"from": 1, "to": 3, "score": 0.8, "mood": "funny"}])

    monkeypatch.setattr(semantic, "_post_json", fake)
    opts = {"picker": "auto", "count": 2, "min_dur": 5, "max_dur": 60,
            "target_dur": 20, "mood_filter": [], "min_score": 0.0}
    found = semantic.find_segments(segments, tmp_path / "v.mp4", 30.0,
                                   opts=opts, workdir=tmp_path)
    assert found and found[0]["source"] == "gemini"
    assert used["key"] == "key"


def test_polza_picker_calls_polza_endpoint(segments, tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings, "api_key",
                        lambda provider: "polza-key" if provider == "polza" else "")
    called = {}

    def fake(url, payload, key, proxy="", timeout=0):
        called["url"] = url
        called["key"] = key
        return _reply([{"from": 1, "to": 3, "score": 0.85, "mood": "insight"}])

    monkeypatch.setattr(semantic, "_post_json", fake)
    for picker_mode in ("polza", "auto"):
        called.clear()
        opts = {"picker": picker_mode, "count": 2, "min_dur": 5, "max_dur": 60,
                "target_dur": 20, "mood_filter": [], "min_score": 0.0}
        found = semantic.find_segments(segments, tmp_path / f"v_{picker_mode}.mp4", 30.0,
                                       opts=opts, workdir=tmp_path / picker_mode)
        assert found and found[0]["source"] == "polza"
        assert called["url"] == "https://polza.ai/api/v1/chat/completions"
        assert called["key"] == "polza-key"


def test_mood_aliases_and_bad_json(segments):
    assert semantic._clean_mood("весёлое") == "funny"
    assert semantic._clean_mood("unknown") == ""
    with pytest.raises(semantic.LLMError):
        semantic._extract_json("совсем не json")


def test_clean_items_limits():
    payload = {"clips": [{"from": 0, "to": 1, "score": 2, "mood": "FUNNY"}]}
    items = semantic._clean_items(payload, total=5, limit=1)
    assert items[0]["score"] == 1.0
    assert items[0]["mood"] == "funny"


def test_build_sentences_still_used(segments):
    assert len(analyze.build_sentences(segments)) == len(segments)
