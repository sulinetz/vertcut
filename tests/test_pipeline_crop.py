"""Кроп-траектория считается до setpts: скорость её не делит."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vertcut import pipeline

CROP = {
    "times": [0.0, 1.0, 4.0, 5.0, 10.0],
    "x": [0, 10, 40, 50, 100],
    "y": [0, 0, 0, 0, 0],
    "crop_w": 320,
    "crop_h": 180,
    "source": [640, 360],
    "coverage": 0.9,
}


class CropSpeedTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.src = self.dir / "src.mp4"
        self.src.write_bytes(b"x" * 100)

    def tearDown(self):
        self.tmp.cleanup()

    def test_crop_path_is_not_scaled_by_speed(self):
        seen = {}

        def fake_render(source, start, end, out_path, **kwargs):
            seen.update(kwargs)
            target = Path(out_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"x" * 20000)
            return {"encoder": "libx264"}

        clip = {
            "id": "c1", "idx": 0, "start": 10.0, "end": 20.0, "title": "t", "hook": "",
            "words": [
                {"word": "a", "start": 10.2, "end": 11.0},
                {"word": "b", "start": 15.0, "end": 16.0},
            ],
        }
        settings = {
            "jump_cuts": True, "cut_zoom": False, "speed": 1.05, "subtitles": False,
            "mode": "auto", "aspect": "9:16", "platform": "", "layout": "",
            "music_volume": 8,
        }
        with mock.patch.object(pipeline.reframe, "build_crop_path",
                               lambda *a, **k: dict(CROP)), \
             mock.patch.object(pipeline.render, "render_clip", side_effect=fake_render), \
             mock.patch.object(pipeline.render, "make_thumb", lambda *a, **k: None), \
             mock.patch.object(pipeline.render, "make_preview", lambda *a, **k: None), \
             mock.patch.object(pipeline.db, "update_clip", lambda *a, **k: None):
            pipeline._render_one(self.src, self.dir, clip, settings)

        times = seen["crop_path"]["times"]
        # 2.32 с — длительность склеек до деления на скорость (speed=1.05).
        # Если скорость применить здесь, последняя точка уедет на 2.21.
        self.assertAlmostEqual(max(times), 2.32, places=2)
        self.assertGreater(max(times), 2.25)


if __name__ == "__main__":
    unittest.main()
