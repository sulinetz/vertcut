"""Защита от выхода длинных субтитров за края и масштаб ASS под разные форматы."""
from __future__ import annotations

import re
from pathlib import Path
from unittest import mock

from vertcut import pipeline, subtitles


def test_long_russian_phrase_fits_within_safe_width():
    words = [
        {"word": "соблазна", "start": 0.2, "end": 1.0},
        {"word": "воспользоваться", "start": 1.0, "end": 2.4},
    ]
    ass = subtitles.build_ass(
        words, 0.0, 3.0,
        hook="соблазна воспользоваться предложением",
        sub_size=118, font="montserrat", uppercase=True,
    )
    m_sub = re.search(r"Dialogue: 0,.*?\\fs(\d+)", ass)
    assert m_sub is not None
    eff = int(m_sub.group(1))
    assert eff < 118
    info = subtitles.font_info("montserrat")
    px = subtitles._line_px("ВОСПОЛЬЗОВАТЬСЯ", info, eff, font_key="montserrat")
    assert px * 1.04 <= 940.0

    m_hook = re.search(r"Dialogue: 1,.*?\\fs(\d+)", ass)
    assert m_hook is not None
    hook_eff = int(m_hook.group(1))
    assert subtitles._line_px("ВОСПОЛЬЗОВАТЬСЯ", info, hook_eff,
                              font_key="montserrat", outline=8.0, spacing=0.5) * 1.04 <= 920.0


def test_short_phrase_keeps_full_font_size():
    words = [
        {"word": "привет", "start": 0.2, "end": 0.8},
        {"word": "мир", "start": 0.8, "end": 1.4},
    ]
    ass = subtitles.build_ass(words, 0.0, 2.0, sub_size=118, show_hook=False)
    line = next(ln for ln in ass.splitlines() if ln.startswith("Dialogue: 0,"))
    assert re.search(r"\\fs\d+", line) is None


def test_aspect_playres_and_pipeline_passes_dimensions(tmp_path: Path):
    words = [{"word": "формат", "start": 0.2, "end": 1.2}]
    for pw, ph in ((1920, 1080), (1080, 1080), (1080, 1350)):
        ass = subtitles.build_ass(words, 0.0, 2.0, play_w=pw, play_h=ph, show_hook=False)
        assert f"PlayResX: {pw}" in ass
        assert f"PlayResY: {ph}" in ass
        m = re.search(r"\\pos\((\d+),(\d+)\)", ass)
        assert m is not None
        assert int(m.group(1)) == pw // 2
        assert 40 <= int(m.group(2)) <= ph - 40

    clip = {
        "id": "c1", "idx": 0, "project_id": "p1", "start": 0.0, "end": 8.0,
        "title": "t", "hook": "", "caption": "", "status": "rendering",
        "words": words, "settings": {},
    }
    src = tmp_path / "src.mp4"
    src.write_bytes(b"x" * 100)
    captured = {}

    def fake_ass(_w, _s, _e, **kwargs):
        captured["ass"] = kwargs
        return "[Script Info]\n"

    def fake_render(_src, _a, _b, out, **kwargs):
        captured["render"] = kwargs
        out.write_bytes(b"x" * 2000)
        return {"encoder": "libx264", "path": out}

    with mock.patch.object(pipeline.utils, "probe", return_value={
             "width": 1920, "height": 1080, "duration": 20.0, "fps": 30.0, "has_audio": True}), \
         mock.patch.object(pipeline.subtitles, "build_ass", fake_ass), \
         mock.patch.object(pipeline.render, "render_clip", fake_render), \
         mock.patch.object(pipeline.render, "make_thumb", lambda *a, **k: None), \
         mock.patch.object(pipeline.render, "make_preview", lambda *a, **k: None), \
         mock.patch.object(pipeline.db, "update_clip", lambda *a, **k: None):
        pipeline._render_one(src, tmp_path, clip, {
            "aspect": "16:9", "mode": "blur", "subtitles": True,
        })

    assert captured["ass"]["play_w"] == 1920
    assert captured["ass"]["play_h"] == 1080
    assert captured["render"]["aspect"] == "16:9"
    assert captured["render"]["mode"] == "blur"


def test_editor_preview_uses_pixel_dimensions_not_aspect_ratios():
    """Живой макет должен считать масштаб шрифта в пикселях (1080×1920), а не 9×16."""
    app_js = (Path(__file__).resolve().parent.parent / "web" / "app.js").read_text(encoding="utf-8")
    assert "const ASPECT_PX =" in app_js
    assert '"9:16": { w: 1080, h: 1920 }' in app_js
    block = re.search(r"const syncStageGeometry = \(\) => \{.*?\n  \};", app_js, re.S)
    assert block is not None
    assert "ASPECT_PX[aspect]" in block.group(0)
    assert "ASPECT_META[aspect]" not in block.group(0)

