"""Тайминг промо-футажа: promo_windows, map_windows_to_base, pipeline и API."""
from __future__ import annotations

from pathlib import Path
from unittest import mock

from vertcut import composition, main, pipeline, timeline


def test_promo_windows_modes():
    assert timeline.promo_windows("loop", duration=12.0) == [(0.0, 12.0)]
    assert timeline.promo_windows("start", duration=12.0, start=2.0, length=4.0) == [(2.0, 6.0)]
    assert timeline.promo_windows("start", duration=5.0, start=4.9, length=4.0) == []
    assert timeline.promo_windows("end", duration=12.0, length=3.5) == [(8.5, 12.0)]
    assert timeline.promo_windows("periodic", duration=25.0, start=2.0, length=4.0, period=10.0) == [
        (2.0, 6.0), (12.0, 16.0), (22.0, 25.0),
    ]


def test_map_windows_to_base_cuts_around_inserts():
    inserts = [{"at": 4.0, "final_start": 4.0, "duration": 2.0}]
    base = timeline.map_windows_to_base([(2.0, 8.0)], inserts)
    assert base == [(2.0, 6.0)]

    split = timeline.map_windows_to_base([(1.0, 3.0), (4.5, 7.5)], inserts)
    assert split == [(1.0, 3.0), (4.0, 5.5)]


def test_promo_plan_and_clip_ad_timeline_route():
    clip = {"id": "c1", "idx": 0, "project_id": "p1", "start": 100.0, "end": 120.0,
            "words": [], "settings": {
                "ads_enabled": True,
                "promo_footage": "f1",
                "promo_mode": "overlay",
                "promo_timing": "periodic",
                "promo_start_sec": 2.0,
                "promo_duration_sec": 4.0,
                "promo_period_sec": 10.0,
            }}
    with mock.patch.object(main.db, "get_clip", lambda _c: dict(clip)), \
         mock.patch.object(main.db, "get_project", lambda _p: {"options": {}}):
        data = main.clip_ad_timeline("c1")
    assert data["promo"]["active"] is True
    assert data["promo"]["mode"] == "overlay"
    assert data["promo"]["windows"] == [(2.0, 6.0), (12.0, 16.0)]
    assert data["promo"]["base_windows"] == [(2.0, 6.0), (12.0, 16.0)]


def test_pipeline_render_one_split_bottom_reserves_subs_and_skips_adhd_bg(tmp_path: Path):
    clip = {
        "id": "c42", "idx": 0, "project_id": "p1", "start": 0.0, "end": 10.0,
        "title": "t", "hook": "h", "caption": "", "status": "rendering",
        "words": [{"word": "hi", "start": 1.0, "end": 2.0}],
        "settings": {},
    }
    promo_file = tmp_path / "promo.mp4"
    promo_file.write_bytes(b"x" * 100)
    captured = {}

    def fake_ass(words, start, end, **kwargs):
        captured["bottom_reserve"] = kwargs.get("bottom_reserve")
        return "[Script Info]\n"

    def fake_crop(*args, **kwargs):
        captured["crop_aspect"] = kwargs.get("aspect")
        return None

    def fake_render(_s, _a, _b, out, **kwargs):
        captured["render"] = kwargs
        out.write_bytes(b"x" * 2000)
        return {"encoder": "libx264", "path": out}

    settings = {
        "layout": "adhd",
        "mode": "auto",
        "subtitles": True,
        "ads_enabled": True,
        "promo_footage": "random",
        "promo_mode": "split_bottom",
        "promo_split_ratio": 0.7,
        "promo_timing": "periodic",
        "promo_audio_vol": 40,
    }
    with mock.patch.object(pipeline.ads, "pick_random_footage", return_value={"id": "p1"}), \
         mock.patch.object(pipeline.ads, "asset_path", return_value=promo_file), \
         mock.patch.object(pipeline.subtitles, "build_ass", fake_ass), \
         mock.patch.object(pipeline.reframe, "build_crop_path", fake_crop), \
         mock.patch.object(pipeline.render, "render_clip", fake_render), \
         mock.patch.object(pipeline.render, "make_thumb", lambda *a, **k: None), \
         mock.patch.object(pipeline.render, "make_preview", lambda *a, **k: None), \
         mock.patch.object(pipeline.db, "update_clip", lambda *a, **k: None):
        pipeline._render_one(promo_file, tmp_path, clip, settings)

    assert captured["crop_aspect"] == "1080:1344"
    assert captured["bottom_reserve"] == 576
    assert captured["render"]["bg_path"] is None
    assert captured["render"]["promo_path"] == promo_file
    assert captured["render"]["promo_timing"] == "loop"
    assert captured["render"]["promo_audio_vol"] == 0.4
