"""ADHD: фильтр ffmpeg, равенство нейтрального графа и валидация настроек."""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import mock

import pytest
from fastapi import HTTPException

from vertcut import main, pipeline, render


class FakeProc:
    def __init__(self, cmd, fail=False, **_kwargs):
        self.cmd = cmd
        self.returncode = 1 if fail else 0
        self.stdout = iter(["out_time_us=1000000\n"])
        self.stderr = iter([])
        if not fail:
            target = Path(cmd[-1])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"x" * 20000)

    def wait(self):
        return self.returncode

    def poll(self):
        return self.returncode

    def kill(self):
        self.returncode = -1


def _probe(_path):
    return {"width": 1920, "height": 1080, "duration": 60.0, "fps": 30.0,
            "has_audio": True}


@pytest.fixture
def render_dir(tmp_path: Path):
    source = tmp_path / "src.mp4"
    source.write_bytes(b"x" * 100)
    bg = tmp_path / "bg.mp4"
    bg.write_bytes(b"x" * 100)
    return source, bg, tmp_path / "out.mp4"


def render_graph(source: Path, out: Path, **kwargs) -> str:
    made = []

    def fake(cmd, **kw):
        proc = FakeProc(cmd, **kw)
        made.append(proc.cmd)
        return proc

    with mock.patch.object(render, "probe", _probe), \
         mock.patch.object(render, "_measure_loudness", lambda *a, **k: None), \
         mock.patch.object(render, "hw_decode", lambda: None), \
         mock.patch.object(render, "hw_encoder", lambda: None), \
         mock.patch.object(render, "subprocess") as sub:
        sub.Popen.side_effect = fake
        sub.PIPE = -1
        render.render_clip(source, 0.0, 10.0, out, **kwargs)
    cmd = made[0]
    return cmd[cmd.index("-filter_complex") + 1]


def test_neutral_defaults_keep_old_graph(render_dir):
    source, bg, out = render_dir
    base = render_graph(source, out, layout="adhd", bg_path=bg, split_ratio=0.5)
    explicit = render_graph(
        source, out, layout="adhd", bg_path=bg, split_ratio=0.5,
        adhd_top_fill="cover", adhd_bottom_fill="cover",
        adhd_top_scale=1.0, adhd_top_offset_x=0.0, adhd_top_offset_y=0.0,
        adhd_bottom_scale=1.0, adhd_bottom_offset_x=0.0, adhd_bottom_offset_y=0.0,
        adhd_bottom_speed=1.0, adhd_bottom_volume=0.0)
    assert base == explicit
    assert base.count("vstack=inputs=2") == 1
    assert "scale=1080:960:force_original_aspect_ratio=increase" in base


def test_old_low_split_ratio_still_renders(render_dir):
    source, bg, out = render_dir
    graph = render_graph(source, out, layout="adhd", bg_path=bg, split_ratio=0.3)
    assert "1080:576" in graph
    assert "scale=1080:1344" in graph


def test_top_contain_letterboxes(render_dir):
    source, bg, out = render_dir
    graph = render_graph(source, out, layout="adhd", bg_path=bg,
                         adhd_top_fill="contain", adhd_top_scale=0.8)
    assert "[topbg][topfit]overlay" in graph
    assert "force_original_aspect_ratio=decrease" in graph
    assert "scale=864:768" in graph  # 1080*0.8, 960*0.8


def test_bottom_contain_and_offsets(render_dir):
    source, bg, out = render_dir
    graph = render_graph(source, out, layout="adhd", bg_path=bg,
                         adhd_bottom_fill="contain",
                         adhd_bottom_offset_x=0.1, adhd_bottom_offset_y=-0.1)
    assert "[botbg][botfit]overlay" in graph
    assert "(W-w)/2+108" in graph
    assert "(H-h)/2+-96" in graph


def test_bottom_speed_changes_pts(render_dir):
    source, bg, out = render_dir
    graph = render_graph(source, out, layout="adhd", bg_path=bg,
                         adhd_bottom_speed=2.0)
    assert "[bottom]setpts=PTS/2.000000[bottom2]" in graph
    assert "[top][bottom2]vstack" in graph


def test_top_scale_and_crop_offset(render_dir):
    source, bg, out = render_dir
    graph = render_graph(source, out, layout="adhd", bg_path=bg,
                         adhd_top_scale=1.2, adhd_top_offset_x=0.05,
                         adhd_top_offset_y=-0.05)
    assert "[top]scale=iw*1.2000:ih*1.2000" in graph
    assert "crop=1080:960:162.0:48.0" in graph


def test_bottom_volume_mixes_bottom_audio(render_dir):
    source, bg, out = render_dir
    graph = render_graph(source, out, layout="adhd", bg_path=bg,
                         adhd_bottom_volume=0.2)
    assert "[1:a]volume=0.200" in graph
    assert "[a0][bga]amix" in graph


def test_bottom_volume_without_bg_audio_is_ignored(render_dir):
    source, bg, out = render_dir
    silent = {"width": 1920, "height": 1080, "duration": 60.0, "fps": 30.0,
              "has_audio": False}
    made = []

    def fake(cmd, **kw):
        proc = FakeProc(cmd, **kw)
        made.append(proc.cmd)
        return proc

    with mock.patch.object(render, "probe", lambda p: silent), \
         mock.patch.object(render, "_measure_loudness", lambda *a, **k: None), \
         mock.patch.object(render, "hw_decode", lambda: None), \
         mock.patch.object(render, "hw_encoder", lambda: None), \
         mock.patch.object(render, "subprocess") as sub:
        sub.Popen.side_effect = fake
        sub.PIPE = -1
        render.render_clip(source, 0.0, 10.0, out, layout="adhd", bg_path=bg,
                           adhd_bottom_volume=0.2)
    graph = made[0][made[0].index("-filter_complex") + 1]
    assert "bga" not in graph


def test_options_defaults_and_clamps():
    opts = pipeline.normalize_options({})
    assert opts["adhd_top_fill"] == "cover"
    assert opts["adhd_bottom_fill"] == "cover"
    assert opts["adhd_top_scale"] == 1.0
    assert opts["adhd_bottom_speed"] == 1.0
    assert opts["adhd_bottom_start"] == -1.0
    assert opts["adhd_bottom_volume"] == 0.0

    clamped = pipeline.normalize_options({
        "adhd_top_fill": "zoom", "adhd_bottom_fill": "contain",
        "adhd_top_scale": 5, "adhd_bottom_scale": 0.1,
        "adhd_top_offset_x": 9, "adhd_bottom_offset_y": -9,
        "adhd_bottom_speed": 9, "adhd_bottom_volume": 99,
        "adhd_bottom_start": -5, "adhd_bg": "../evil.mp4",
    })
    assert clamped["adhd_top_fill"] == "cover"
    assert clamped["adhd_bottom_fill"] == "contain"
    assert clamped["adhd_top_scale"] == 2.0
    assert clamped["adhd_bottom_scale"] == 0.5
    assert clamped["adhd_top_offset_x"] == 0.5
    assert clamped["adhd_bottom_offset_y"] == -0.5
    assert clamped["adhd_bottom_speed"] == 4.0
    assert clamped["adhd_bottom_volume"] == 50.0
    assert clamped["adhd_bottom_start"] == -1.0
    assert clamped["adhd_bg"] == ""


def test_clip_settings_include_adhd_fields(tmp_path: Path):
    for key in ("adhd_bg", "adhd_top_fill", "adhd_bottom_fill",
                "adhd_top_scale", "adhd_top_offset_x", "adhd_top_offset_y",
                "adhd_bottom_scale", "adhd_bottom_offset_x",
                "adhd_bottom_offset_y", "adhd_bottom_speed",
                "adhd_bottom_start", "adhd_bottom_volume"):
        assert key in pipeline.CLIP_SETTING_KEYS

    local = tmp_path / "adhd_bottom.mp4"
    local.write_bytes(b"x" * 2000)
    assert pipeline._adhd_bg_file("local:adhd_bottom.mp4", tmp_path) == local
    assert pipeline._adhd_bg_file("local:../../evil.mp4", tmp_path) is None


def test_clip_edit_rejects_bad_fill():
    body = main.ClipEdit(adhd_top_fill="zoom")
    with pytest.raises(HTTPException) as exc:
        main._clean_clip_edit(body)
    assert exc.value.status_code == 400
    clean = main._clean_clip_edit(main.ClipEdit(adhd_top_fill="contain",
                                                adhd_bottom_speed=9,
                                                split_ratio=0.9))
    assert clean["adhd_top_fill"] == "contain"
    assert clean["adhd_bottom_speed"] == 4.0
    assert clean["split_ratio"] == 0.85
