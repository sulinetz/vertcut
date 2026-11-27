"""Сквозная проверка 14 настроек promo_* через composition, pipeline, live и main."""
from __future__ import annotations

from unittest import mock

import pytest
from fastapi import HTTPException

from vertcut import composition, live, main, pipeline

PROMO_KEYS = (
    "promo_footage",
    "promo_mode",
    "promo_scale",
    "promo_pos",
    "promo_x",
    "promo_y",
    "promo_fill",
    "promo_key_color",
    "promo_timing",
    "promo_start_sec",
    "promo_duration_sec",
    "promo_period_sec",
    "promo_audio_vol",
    "promo_split_ratio",
)


def test_promo_settings_in_spec_defaults_clip_keys_and_live():
    for key in PROMO_KEYS:
        assert key in composition.SPEC
        assert composition.SPEC[key].layer == "ads"
        assert composition.SPEC[key].clip is True
        assert key in pipeline.DEFAULT_OPTIONS
        assert key in pipeline.CLIP_SETTING_KEYS
        assert key in live._settings({})
        assert key in main.ClipEdit.model_fields

    schema = composition.schema()
    schema_keys = {item["key"] for item in schema["settings"]}
    for key in PROMO_KEYS:
        assert key in schema_keys


def test_promo_clamping_parity_across_composition_pipeline_and_clip_edit():
    numeric_raw = {
        "promo_scale": 999,
        "promo_x": -2.0,
        "promo_y": 5.0,
        "promo_start_sec": -10.0,
        "promo_duration_sec": 0.05,
        "promo_period_sec": 0.5,
        "promo_audio_vol": 250,
        "promo_split_ratio": 0.1,
    }
    norm = pipeline.normalize_options(numeric_raw)
    edit = main._clean_clip_edit(main.ClipEdit(**numeric_raw))
    for key, value in numeric_raw.items():
        expected = composition.clamp_value(key, value)
        assert norm[key] == expected, key
        assert edit[key] == expected, key

    choice_raw = {
        "promo_mode": "invalid",
        "promo_pos": "nowhere",
        "promo_fill": "stretch",
        "promo_key_color": "blue",
        "promo_timing": "always",
    }
    norm_choices = pipeline.normalize_options(choice_raw)
    for key, value in choice_raw.items():
        assert norm_choices[key] == composition.clamp_value(key, value)
        with pytest.raises(HTTPException) as exc:
            main._clean_clip_edit(main.ClipEdit(**{key: value}))
        assert exc.value.status_code == 400

    assert edit["promo_scale"] == 100
    assert edit["promo_x"] == 0.0
    assert edit["promo_y"] == 1.0
    assert edit["promo_duration_sec"] == 0.5
    assert edit["promo_period_sec"] == 2.0
    assert edit["promo_audio_vol"] == 100
    assert edit["promo_split_ratio"] == 0.4


def test_promo_footage_validation_in_clean_clip_edit():
    assert main._clean_clip_edit(main.ClipEdit(promo_footage=""))["promo_footage"] == ""
    assert main._clean_clip_edit(main.ClipEdit(promo_footage="random"))["promo_footage"] == "random"

    with mock.patch.object(main.ads, "get_asset", return_value={"id": "p1"}):
        assert main._clean_clip_edit(main.ClipEdit(promo_footage="p1"))["promo_footage"] == "p1"

    with mock.patch.object(main.ads, "get_asset", return_value=None):
        with pytest.raises(HTTPException) as exc:
            main._clean_clip_edit(main.ClipEdit(promo_footage="missing_id"))
        assert exc.value.status_code == 400


def test_layers_and_promo_plan_activation():
    layers = {item["name"]: item for item in composition.layers({
        "promo_footage": "p1", "promo_mode": "split_bottom", "ads_enabled": True,
    })}
    assert layers["ads"]["active"] is True
    assert layers["ads"]["promo"] == {"mode": "split_bottom", "asset": "p1"}

    disabled = {item["name"]: item for item in composition.layers({
        "promo_footage": "p1", "promo_mode": "overlay", "ads_enabled": False,
    })}
    assert disabled["ads"]["active"] is False
    assert disabled["ads"]["promo"] is None
