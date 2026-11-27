"""Поддержка GIF в библиотеке рекламных ассетов и выбор random-футажа."""
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


def make_gif(path: Path, *, frames: int = 3, duration_ms: int = 120) -> Path:
    imgs = [
        Image.new("RGBA", (80, 40), (i * 60 % 255, 200, 50, 255))
        for i in range(frames)
    ]
    if frames == 1:
        imgs[0].save(path, format="GIF")
    else:
        imgs[0].save(
            path, format="GIF", save_all=True,
            append_images=imgs[1:], duration=duration_ms, loop=0,
        )
    return path


def make_png(path: Path) -> Path:
    Image.new("RGBA", (64, 64), (10, 20, 30, 255)).save(path)
    return path


def test_add_animated_gif_stores_metadata_and_deletes(tmp_path: Path):
    asset = ads.add_file("roulette.gif", make_gif(tmp_path / "r.gif", frames=4, duration_ms=150))
    assert asset["kind"] == "image"
    assert asset["animated"] is True
    assert asset["frames"] == 4
    assert asset["duration"] == pytest.approx(0.6, abs=0.05)
    assert ads.is_animated_footage(asset) is True

    path = ads.asset_path(asset["id"])
    assert path is not None and path.is_file()
    assert ads.delete(asset["id"]) is True
    assert not path.exists()


def test_pick_random_footage_skips_static_png_and_text_and_is_deterministic(tmp_path: Path):
    make_png_asset = ads.add_file("banner.png", make_png(tmp_path / "b.png"))
    text_asset = ads.add_text("PROMO50")
    assert ads.is_animated_footage(make_png_asset) is False
    assert ads.is_animated_footage(text_asset) is False
    assert ads.pick_random_footage("clip_1") is None

    gif1 = ads.add_file("anim1.gif", make_gif(tmp_path / "g1.gif", frames=3))
    gif2 = ads.add_file("anim2.gif", make_gif(tmp_path / "g2.gif", frames=3))
    assert ads.is_animated_footage(gif1) is True

    first = ads.pick_random_footage("clip_alpha")
    second = ads.pick_random_footage("clip_alpha")
    assert first is not None and second is not None
    assert first["id"] == second["id"]
    assert first["id"] in {gif1["id"], gif2["id"]}
