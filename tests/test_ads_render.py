"""Реклама в рендере: отсутствие событий не меняет команду, накладки и вставки."""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from vertcut import render


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
def media(tmp_path: Path):
    source = tmp_path / "src.mp4"
    source.write_bytes(b"x" * 100)
    image = tmp_path / "logo.png"
    image.write_bytes(b"x" * 100)
    video = tmp_path / "ad.mp4"
    video.write_bytes(b"x" * 100)
    return source, image, video, tmp_path / "out.mp4"


def render_cmd(source: Path, out: Path, **kwargs):
    made = []

    def fake(cmd, **kw):
        proc = FakeProc(cmd, **kw)
        made.append(proc.cmd)
        return proc

    with mock.patch.object(render, "probe", _probe), \
         mock.patch.object(render, "_measure_loudness", lambda *a, **k: None), \
         mock.patch.object(render, "hw_encoder", lambda: None), \
         mock.patch.object(render, "subprocess") as sub:
        sub.Popen.side_effect = fake
        sub.PIPE = -1
        render.render_clip(source, 0.0, 10.0, out, **kwargs)
    return made[0]


def graph_of(cmd):
    return cmd[cmd.index("-filter_complex") + 1]


def overlay_event(image: Path, **extra) -> dict:
    event = {"id": "e1", "asset": "logo", "kind": "overlay", "start": 2.0,
             "duration": 2.0, "x": 0.7, "y": 0.05, "w": 0.2, "h": 0.2,
             "opacity": 0.8, "anim_in": "fade", "anim_out": "none",
             "anim_dur": 0.3, "z": 5}
    event.update(extra)
    return event


def replace_event(video: Path, **extra) -> dict:
    event = {"id": "r1", "asset": "ad", "kind": "replace", "start": 6.0,
             "duration": 2.0, "volume": 0.5}
    event.update(extra)
    return event


def test_no_events_keeps_command(media):
    source, image, video, out = media
    plain = render_cmd(source, out)
    empty = render_cmd(source, out, ad_events=[], ad_files={})
    assert plain == empty


def test_missing_asset_is_ignored(media):
    source, image, video, out = media
    plain = render_cmd(source, out)
    missing = render_cmd(source, out, ad_events=[overlay_event(image)],
                         ad_files={})
    assert plain == missing


def test_overlay_graph_has_scale_fade_and_enable(media):
    source, image, video, out = media
    cmd = render_cmd(source, out, ad_events=[overlay_event(image)],
                     ad_files={"logo": image}, ass_path=out.parent / "a.ass")
    graph = graph_of(cmd)
    assert "[1:v]" in graph
    assert "scale=216:384" in graph  # 0.2 от 1080x1920
    assert "colorchannelmixer=aa=0.800" in graph
    assert "fade=t=in:st=2.000:d=0.300:alpha=1" in graph
    assert "overlay=" in graph
    assert "enable='between(t,2.000,4.000)'" in graph
    assert graph.index("overlay=") < graph.index("ass=filename")
    assert cmd.count("-i") == 2


def test_overlay_slide_and_scale_animations(media):
    source, image, video, out = media
    slide = overlay_event(image, x=0.05, anim_in="slide", anim_out="slide")
    cmd = render_cmd(source, out, ad_events=[slide], ad_files={"logo": image})
    graph = graph_of(cmd)
    assert "overlay_w*(1-min(max((t-2.000)/0.300,0),1))" in graph

    scaled = overlay_event(image, anim_in="scale", anim_out="scale")
    cmd = render_cmd(source, out, ad_events=[scaled], ad_files={"logo": image})
    graph = graph_of(cmd)
    assert "eval=frame" in graph
    assert "overlay_w/2" in graph


def test_replace_adds_duration_and_audio(media):
    source, image, video, out = media
    cmd = render_cmd(source, out, ad_events=[replace_event(video)],
                     ad_files={"ad": video})
    graph = graph_of(cmd)
    assert "concat=n=3:v=1:a=0[basei]" in graph
    assert "[1:v]scale=1080:1920" in graph
    assert "trim=duration=2.000" in graph
    assert "[1:a]atrim=duration=2.000" in graph
    assert "volume=0.500" in graph
    assert "concat=n=3:v=0:a=1[a0i]" in graph
    out_t = cmd[cmd.index("-t", cmd.index("-filter_complex")) + 1]
    assert out_t == "12.000"


def test_overlay_crossing_insert_stretches_over_ad(media):
    source, image, video, out = media
    event = overlay_event(image, start=5.0, duration=4.0, anim_in="none")
    cmd = render_cmd(source, out, ad_events=[event, replace_event(video)],
                     ad_files={"logo": image, "ad": video})
    graph = graph_of(cmd)
    # 5.0 → 5.0, 9.0 → 11.0: накладка продолжается поверх рекламы.
    assert "enable='between(t,5.000,11.000)'" in graph


def test_replace_in_adhd_uses_full_frame(media):
    source, image, video, out = media
    cmd = render_cmd(source, out, layout="adhd", split_ratio=0.6,
                     ad_events=[replace_event(video)], ad_files={"ad": video})
    graph = graph_of(cmd)
    assert "vstack=inputs=2[base]" in graph
    assert "[1:v]scale=1080:1920" in graph
    assert "concat=n=3:v=1:a=0[basei]" in graph


def test_replace_with_image_uses_silence_audio(media):
    source, image, video, out = media
    cmd = render_cmd(source, out, ad_events=[replace_event(image, asset="logo")],
                     ad_files={"logo": image})
    graph = graph_of(cmd)
    assert "aevalsrc=0|0:s=48000:d=2.000" in graph
