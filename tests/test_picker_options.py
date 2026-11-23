"""Настройки выбора моментов: валидация picker, настроений и порога."""
from __future__ import annotations

from vertcut import pipeline, semantic


def test_defaults_keep_local_picker():
    opts = pipeline.normalize_options({})
    assert opts["picker"] == "local"
    assert opts["mood_filter"] == []
    assert opts["min_score"] == 0.0


def test_picker_validation():
    assert pipeline.normalize_options({"picker": "deepseek"})["picker"] == "deepseek"
    assert pipeline.normalize_options({"picker": "gemini"})["picker"] == "gemini"
    assert pipeline.normalize_options({"picker": "auto"})["picker"] == "auto"
    assert pipeline.normalize_options({"picker": "gpt"})["picker"] == "local"


def test_mood_filter_accepts_list_and_string():
    assert pipeline.normalize_options(
        {"mood_filter": ["funny", "sad"]})["mood_filter"] == ["funny", "sad"]
    assert pipeline.normalize_options(
        {"mood_filter": "funny, shock"})["mood_filter"] == ["funny", "shock"]
    # Неизвестные метки отбрасываются, дубликаты не ломают фильтр.
    assert pipeline.normalize_options(
        {"mood_filter": ["funny", "nonsense"]})["mood_filter"] == ["funny"]
    assert set(semantic.MOODS) >= {"funny", "sad", "drama", "shock"}


def test_min_score_clamped():
    assert pipeline.normalize_options({"min_score": 2})["min_score"] == 1.0
    assert pipeline.normalize_options({"min_score": -1})["min_score"] == 0.0
    assert pipeline.normalize_options({"min_score": "0,7"})["min_score"] == 0.0
    assert pipeline.normalize_options({"min_score": 0.65})["min_score"] == 0.65


def test_selection_settings_not_in_clip_settings():
    """Настройки выбора не должны попадать в рендер-настройки клипа."""
    opts = pipeline.normalize_options({"picker": "deepseek", "mood_filter": ["funny"]})
    clip = pipeline._clip_settings(opts)
    assert "picker" not in clip
    assert "mood_filter" not in clip
