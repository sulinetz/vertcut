"""Реклама в pipeline: слова и ASS пересчитываются, файлы подставляются."""
from __future__ import annotations

from pathlib import Path
from unittest import mock

from vertcut import pipeline


def test_render_one_shifts_subtitles_and_passes_files(tmp_path: Path):
    clip = {
        "id": "c1", "idx": 0, "project_id": "p1", "start": 100.0, "end": 110.0,
        "title": "t", "hook": "", "caption": "", "status": "rendering",
        "words": [
            {"word": "до", "start": 101.0, "end": 102.0},
            {"word": "после", "start": 106.0, "end": 107.0},
        ],
        "settings": {},
    }
    settings = {"subtitles": True, "mode": "crop", "ads_enabled": True,
                "ad_events": [{"id": "r1", "asset": "ad1", "kind": "replace",
                               "start": 104.0, "duration": 2.0, "volume": 0.5}]}
    asset = tmp_path / "ad.mp4"
    asset.write_bytes(b"x" * 100)
    captured = {}

    def build_ass(words, start, end, **kwargs):
        captured["words"] = [dict(word) for word in words]
        captured["start"] = start
        captured["end"] = end
        captured["blackouts"] = kwargs.get("blackouts")
        return "[Script Info]\n"

    def render(_source, _start, _end, out, **kwargs):
        captured["render"] = kwargs
        out.write_bytes(b"x" * 2000)
        return {"encoder": "libx264", "path": out}

    with mock.patch.object(pipeline.ads, "asset_path", lambda aid: asset), \
         mock.patch.object(pipeline.subtitles, "build_ass", build_ass), \
         mock.patch.object(pipeline.render, "render_clip", render), \
         mock.patch.object(pipeline.render, "make_thumb", lambda *a, **k: None), \
         mock.patch.object(pipeline.render, "make_preview", lambda *a, **k: None), \
         mock.patch.object(pipeline.reframe, "build_crop_path", lambda *a, **k: None), \
         mock.patch.object(pipeline.db, "update_clip", lambda *a, **k: None):
        pipeline._render_one(asset, tmp_path, clip, settings)

    assert captured["start"] == 100.0
    assert captured["end"] == 112.0
    words = {word["word"]: word for word in captured["words"]}
    assert words["до"]["start"] == 101.0
    assert words["после"]["start"] == 108.0
    assert captured["render"]["ad_events"][0]["asset"] == "ad1"
    assert captured["render"]["ad_files"]["ad1"] == asset
    assert captured["blackouts"] == [(4.0, 6.0)]


def test_disabled_ads_are_not_passed(tmp_path: Path):
    clip = {
        "id": "c1", "idx": 0, "project_id": "p1", "start": 0.0, "end": 10.0,
        "title": "t", "hook": "", "caption": "", "status": "rendering",
        "words": [], "settings": {},
    }
    settings = {"subtitles": False, "mode": "crop", "ads_enabled": False,
                "ad_events": [{"id": "r1", "asset": "ad1", "kind": "replace",
                               "start": 4.0, "duration": 2.0}]}
    asset = tmp_path / "ad.mp4"
    asset.write_bytes(b"x" * 100)
    captured = {}

    def render(_source, _start, _end, out, **kwargs):
        captured.update(kwargs)
        out.write_bytes(b"x" * 2000)
        return {"encoder": "libx264", "path": out}

    with mock.patch.object(pipeline.ads, "asset_path", lambda aid: asset), \
         mock.patch.object(pipeline.render, "render_clip", render), \
         mock.patch.object(pipeline.render, "make_thumb", lambda *a, **k: None), \
         mock.patch.object(pipeline.render, "make_preview", lambda *a, **k: None), \
         mock.patch.object(pipeline.reframe, "build_crop_path", lambda *a, **k: None), \
         mock.patch.object(pipeline.db, "update_clip", lambda *a, **k: None):
        pipeline._render_one(asset, tmp_path, clip, settings)
    assert captured["ad_events"] == []
    assert captured["ad_files"] == {}
