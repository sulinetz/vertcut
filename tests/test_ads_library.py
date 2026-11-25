"""Библиотека рекламных ассетов: добавление, имена, тексты, события."""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from vertcut import ads


@pytest.fixture(autouse=True)
def library(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ads, "ADS_DIR", tmp_path / "ads")
    monkeypatch.setattr(ads, "INDEX_PATH", tmp_path / "ads" / "index.json")
    yield


def make_png(path: Path) -> Path:
    Image.new("RGBA", (120, 60), (255, 0, 0, 200)).save(path)
    return path


def test_add_image_and_list(tmp_path: Path):
    asset = ads.add_file("Логотип!.PNG", make_png(tmp_path / "logo.png"))
    assert asset["kind"] == "image"
    assert asset["width"] == 120 and asset["height"] == 60
    assert asset["url"].startswith("/api/ads/")
    assert ads.asset_path(asset["id"]).is_file()
    assert ads.list_assets()[0]["name"] == "Логотип!"


def test_reject_bad_extension(tmp_path: Path):
    bad = tmp_path / "x.exe"
    bad.write_bytes(b"x")
    with pytest.raises(ValueError):
        ads.add_file("x.exe", bad)


def test_reject_broken_image(tmp_path: Path):
    bad = tmp_path / "x.png"
    bad.write_bytes(b"not a png")
    with pytest.raises(ValueError):
        ads.add_file("x.png", bad)


def test_rename_and_delete(tmp_path: Path):
    asset = ads.add_file("logo.png", make_png(tmp_path / "logo.png"))
    renamed = ads.rename(asset["id"], "Новый/логотип?")
    assert renamed["name"] == "Новыйлоготип"
    path = ads.asset_path(asset["id"])
    assert ads.delete(asset["id"]) is True
    assert not path.exists()
    assert ads.get_asset(asset["id"]) is None


def test_text_asset_is_png(tmp_path: Path):
    asset = ads.add_text("-50% до конца недели", color="#FFFFFF",
                         background="#FF0000CC", font_size=48)
    assert asset["kind"] == "text"
    path = ads.asset_path(asset["id"])
    with Image.open(path) as image:
        assert image.mode == "RGBA"
        assert image.width > 100
    with pytest.raises(ValueError):
        ads.add_text("   ")


def test_normalize_events_filters_and_clamps():
    events = ads.normalize_events([
        {"asset": "a", "kind": "overlay", "start": -4, "duration": 0.01,
         "x": 2, "y": -1, "w": 0, "h": 5, "opacity": 2,
         "anim_in": "warp", "anim_out": "fade", "anim_dur": 9, "z": 999},
        {"asset": "", "kind": "overlay"},
        {"asset": "b", "kind": "replace", "start": 5, "duration": 3,
         "volume": 2},
        "garbage",
    ], known={"a", "b"})
    assert len(events) == 2
    first, second = events
    assert first["start"] == 0.0
    assert first["duration"] == 0.2
    assert first["x"] == 1.0 and first["y"] == 0.0
    assert first["w"] == 0.02 and first["h"] == 1.0
    assert first["opacity"] == 1.0
    assert first["anim_in"] == "none" and first["anim_out"] == "fade"
    assert first["anim_dur"] == 2.0 and first["z"] == 100
    assert second["kind"] == "replace" and second["volume"] == 1.0


def test_normalize_events_unknown_asset_rejected():
    assert ads.normalize_events([{"asset": "missing"}], known={"a"}) == []
    assert len(ads.normalize_events([{"asset": "x"}])) == 1


def test_events_cap():
    events = [{"asset": "a", "start": i} for i in range(100)]
    assert len(ads.normalize_events(events)) == ads.MAX_EVENTS
