"""Рендер промо-футажа в render.py: overlay, split_bottom, хромакей, GIF, звук."""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from vertcut import render


class FakeProc:
    def __init__(self, cmd, **_kwargs):
        self.cmd = cmd
        self.returncode = 0
        self.stdout = iter(["out_time_us=1000000\n"])
        self.stderr = iter([])
        target = Path(cmd[-1])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"x" * 20000)

    def wait(self):
        return 0

    def poll(self):
        return 0

    def kill(self):
        self.returncode = -1


def _probe(path):
    p = str(path)
    if "silent" in p:
        return {"width": 1920, "height": 1080, "duration": 10.0, "fps": 30.0, "has_audio": False}
    return {"width": 1920, "height": 1080, "duration": 10.0, "fps": 30.0, "has_audio": True}


@pytest.fixture
def media(tmp_path: Path):
    src = tmp_path / "src.mp4"
    src.write_bytes(b"x" * 100)
    promo_mp4 = tmp_path / "promo.mp4"
    promo_mp4.write_bytes(b"x" * 100)
    promo_gif = tmp_path / "promo.gif"
    promo_gif.write_bytes(b"GIF89a")
    promo_png = tmp_path / "promo.png"
    promo_png.write_bytes(b"PNG")
    bg = tmp_path / "bg.mp4"
    bg.write_bytes(b"x" * 100)
    return src, promo_mp4, promo_gif, promo_png, bg, tmp_path / "out.mp4"


def run_render(source: Path, out: Path, **kwargs):
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
    return made[0]


def graph_of(cmd):
    return cmd[cmd.index("-filter_complex") + 1]


def test_neutral_defaults_keep_command_identical(media):
    src, _, _, _, _, out = media
    plain = run_render(src, out)
    neutral = run_render(
        src, out,
        promo_path=None, promo_mode="overlay", promo_scale=60,
        promo_pos="bottom", promo_key_color="none", promo_timing="loop",
        promo_audio_vol=0.0,
    )
    assert plain == neutral


def test_overlay_colorkey_periodic_gif_and_ass_order(media):
    src, promo_mp4, promo_gif, promo_png, _, out = media
    cmd = run_render(
        src, out,
        ass_path=out.parent / "subs.ass",
        promo_path=promo_mp4,
        promo_mode="overlay",
        promo_scale=50,
        promo_pos="top",
        promo_key_color="green",
        promo_timing="periodic",
        promo_windows=[(1.0, 4.0), (6.0, 9.0)],
        hflip=True,
    )
    graph = graph_of(cmd)
    assert "scale=540:-2" in graph
    assert "colorkey=0x00FF00:0.25:0.1" in graph
    assert "enable='between(t,1.000,4.000)+between(t,6.000,9.000)':eof_action=pass" in graph
    assert graph.index("hflip[styled]") < graph.index("[promov]overlay=")
    assert graph.index("[promov]overlay=") < graph.index("ass=filename=")
    assert cmd[cmd.index("-t", cmd.index("-filter_complex")) + 1] == "10.000"

    cmd_gif = run_render(src, out, promo_path=promo_gif, promo_key_color="black")
    assert "-ignore_loop" in cmd_gif
    assert "colorkey=0x000000:0.15:0.1" in graph_of(cmd_gif)

    cmd_png = run_render(src, out, promo_path=promo_png, promo_pos="custom", promo_x=0.25, promo_y=0.75)
    assert "-loop" in cmd_png and "30" in cmd_png
    g_png = graph_of(cmd_png)
    assert "W*0.250-w/2" in g_png and "H*0.750-h/2" in g_png


def test_split_bottom_vstack_style_isolation_and_adhd_override(media):
    src, promo_mp4, _, _, bg, out = media
    cmd = run_render(
        src, out,
        layout="adhd",
        bg_path=bg,
        hflip=True,
        tilt=2.0,
        promo_path=promo_mp4,
        promo_mode="split_bottom",
        promo_fill="contain",
        promo_split_ratio=0.7,
    )
    graph = graph_of(cmd)
    assert str(bg) not in cmd
    assert "vstack=inputs=2[base]" in graph
    assert "force_original_aspect_ratio=decrease,setsar=1,pad=1080:576" in graph
    # Стиль применяется к [top] до vstack, а не к [base] после него.
    assert "[top]hflip" in graph
    assert graph.index("[top_styled][promo_bot]vstack=inputs=2[base]") > graph.index("[top]hflip")
    assert "[base]hflip" not in graph


def test_promo_audio_mixing_delayed_and_silent_source(media, tmp_path: Path):
    src, promo_mp4, _, _, _, out = media
    cmd = run_render(
        src, out,
        promo_path=promo_mp4,
        promo_mode="overlay",
        promo_timing="start",
        promo_windows=[(2.0, 5.0)],
        promo_audio_vol=0.6,
    )
    graph = graph_of(cmd)
    assert "volume=0.600" in graph
    assert "adelay=2000|2000" in graph
    assert "apad=whole_dur=10.000" in graph
    assert "amix=inputs=2:duration=first:dropout_transition=0" in graph

    silent = tmp_path / "silent_src.mp4"
    silent.write_bytes(b"x" * 100)
    cmd_silent = run_render(
        silent, out,
        promo_path=promo_mp4,
        promo_mode="overlay",
        promo_timing="periodic",
        promo_windows=[(1.0, 3.0), (5.0, 7.0)],
        promo_audio_vol=0.5,
    )
    g_silent = graph_of(cmd_silent)
    assert "[1:a]asplit=2[pas0][pas1]" in g_silent
    assert "adelay=1000|1000" in g_silent
    assert "adelay=5000|5000" in g_silent
    assert cmd_silent[cmd_silent.index("-map", cmd_silent.index("-map") + 1) + 1] == "[pa]"
