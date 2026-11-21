"""Пресеты стрима: врезка с лицом поверх видео."""
from __future__ import annotations

import unittest
from unittest import mock

from vertcut import platforms, render


class StreamChainTest(unittest.TestCase):
    """Собираем строку фильтров без запуска ffmpeg."""

    facecam = {"x": 70, "y": 10, "w": 310, "h": 240, "share": 1.0, "source": [1920, 1080]}
    crop = {"times": [0.0, 5.0], "x": [400, 400], "y": [0, 0],
            "crop_w": 608, "crop_h": 1080, "source": [1920, 1080],
            "coverage": 1.0, "faces": 10, "samples": 10}

    def test_face_layout_overlays_panel(self):
        chain = render._stream_chain(1080, 1920, self.crop, self.facecam,
                                     "face_large", "universal")
        self.assertIn("overlay=", chain)
        self.assertIn("[face]", chain)
        self.assertIn("crop=310:240:70:10", chain)
        self.assertIn("scale=520:406", chain)

    def test_face_panel_is_above_subtitles(self):
        chain = render._stream_chain(1080, 1920, self.crop, self.facecam,
                                     "face_third", "universal")
        top = platforms.zones("universal")["top"]
        self.assertIn(f"overlay=64:{top + 40}", chain)

    def test_band_uses_bottom_strip(self):
        chain = render._stream_chain(1080, 1920, self.crop, self.facecam,
                                     "band", "universal")
        self.assertIn(f"overlay=0:{1920 - render.BAND_H}", chain)
        self.assertIn(f"scale=1080:{render.BAND_H}", chain)

    def test_layouts_registry(self):
        self.assertEqual(set(render.STREAM_LAYOUTS),
                         {"face_third", "face_large", "face_huge", "band"})


class LayoutOptionsTest(unittest.TestCase):
    def test_layout_defaults_and_validation(self):
        from vertcut import pipeline

        self.assertEqual(pipeline.normalize_options({})["layout"], "")
        self.assertEqual(pipeline.normalize_options({"layout": "band"})["layout"], "band")
        self.assertEqual(pipeline.normalize_options({"layout": "nonsense"})["layout"], "")

    def test_band_reserves_space_for_subtitles(self):
        plain = platforms.bottom_text_y("universal")
        with_band = platforms.bottom_text_y("universal", reserve=render.BAND_H)
        self.assertLess(with_band, plain)


class FacecamGeometryTest(unittest.TestCase):
    def test_box_contains_face_and_stays_in_frame(self):
        from vertcut import reframe

        box = reframe._facecam_box(68, 89, 225, 115, 1920, 1080)
        self.assertGreaterEqual(box["x"], 0)
        self.assertGreaterEqual(box["y"], 0)
        self.assertLessEqual(box["x"] + box["w"], 1920)
        self.assertLessEqual(box["y"] + box["h"], 1080)
        self.assertGreater(box["w"], 68)
        self.assertGreater(box["h"], 89)

    def test_inside_filter(self):
        from vertcut import reframe

        rect = (0, 0, 400, 310)
        self.assertTrue(reframe._inside({"cx": 225, "cy": 115}, rect))
        self.assertFalse(reframe._inside({"cx": 900, "cy": 115}, rect))


if __name__ == "__main__":
    unittest.main()
