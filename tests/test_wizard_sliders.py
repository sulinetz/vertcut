"""Ползунки мастера: число не должно уходить в настройку как false."""
from __future__ import annotations

import re
from pathlib import Path

from vertcut import pipeline

WEB = Path(__file__).resolve().parents[1] / "web"


def _wizard_source() -> str:
    return (WEB / "wizard.js").read_text(encoding="utf-8")


def test_slider_binding_uses_element_type():
    text = _wizard_source()
    assert 'const isCheck = el.type === "checkbox" || el.type === "radio";' in text
    assert "wizard.opts[key] = isCheck ? el.checked : Number(el.value);" in text
    # Старый помощник ветвился по аргументу prop со значением "checked"
    # по умолчанию: ползунки размера/сдвига/интервала писали false.
    assert 'const on = (id, key, prop = "checked")' not in text


def test_no_numeric_binding_passes_checked():
    text = _wizard_source()
    calls = re.findall(r'on\("([^"]+)",\s*"([^"]+)"([^)]*)\)', text)
    numeric = {"sub_size", "sub_offset", "line_gap"}
    assert calls, "привязки on(...) не найдены"
    for _element, key, rest in calls:
        if key in numeric:
            assert "checked" not in rest, f"{key} всё ещё читает checked"


def test_boolean_sub_size_falls_back_to_default():
    opts = pipeline.normalize_options({"sub_size": False})
    assert opts["sub_size"] == 118


def test_wizard_adhd_preview_overrides_blur_and_allows_drag():
    text = _wizard_source()
    assert 'id="wzFrame"' in text and 'draggable="false"' in text
    fn_start = text.index("function applyPreviewLayout(box)")
    fn_end = text.index("function stepSubs()", fn_start)
    fn_body = text[fn_start:fn_end]
    assert fn_body.index("if (isAdhd)") < fn_body.index('wizard.opts.mode === "blur"')

