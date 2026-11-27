"""Дополнительные поля событий рекламы (key_color) и обратная совместимость."""
from __future__ import annotations

from pathlib import Path
from unittest import mock

from vertcut import ads, render


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


def _probe(_path):
    return {"width": 1920, "height": 1080, "duration": 60.0, "fps": 30.0, "has_audio": True}


def _render_cmd(source: Path, out: Path, events, files):
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
        render.render_clip(source, 0.0, 10.0, out, ad_events=events, ad_files=files)
    return made[0]


def test_normalize_events_key_color_and_legacy_defaults():
    events = ads.normalize_events([
        {"asset": "a", "kind": "overlay", "start": 1, "duration": 2},
        {"asset": "b", "kind": "overlay", "start": 1, "duration": 2, "key_color": "GREEN"},
        {"asset": "c", "kind": "overlay", "start": 1, "duration": 2, "key_color": "black"},
        {"asset": "d", "kind": "overlay", "start": 1, "duration": 2, "key_color": "purple"},
    ])
    assert events[0]["key_color"] == "none"
    assert events[1]["key_color"] == "green"
    assert events[2]["key_color"] == "black"
    assert events[3]["key_color"] == "none"


def test_overlay_event_colorkey_render_and_neutral_compatibility(tmp_path: Path):
    source = tmp_path / "src.mp4"
    source.write_bytes(b"x" * 100)
    banner = tmp_path / "ad.mp4"
    banner.write_bytes(b"x" * 100)
    out = tmp_path / "out.mp4"

    plain_ev = {"id": "e1", "asset": "ad", "kind": "overlay", "start": 1.0, "duration": 2.0}
    none_ev = {**plain_ev, "key_color": "none"}
    cmd_plain = _render_cmd(source, out, [plain_ev], {"ad": banner})
    cmd_none = _render_cmd(source, out, [none_ev], {"ad": banner})
    assert cmd_plain == cmd_none
    assert "colorkey=" not in cmd_plain[cmd_plain.index("-filter_complex") + 1]

    cmd_green = _render_cmd(source, out, [{**plain_ev, "key_color": "green"}], {"ad": banner})
    graph_green = cmd_green[cmd_green.index("-filter_complex") + 1]
    assert "colorkey=0x00FF00:0.25:0.1" in graph_green

    cmd_black = _render_cmd(source, out, [{**plain_ev, "key_color": "black"}], {"ad": banner})
    graph_black = cmd_black[cmd_black.index("-filter_complex") + 1]
    assert "colorkey=0x000000:0.15:0.1" in graph_black
