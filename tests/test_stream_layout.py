"""Пресеты стрима: крупное лицо полосой сверху или снизу."""
from __future__ import annotations

import unittest

from vertcut import platforms, render


class StreamChainTest(unittest.TestCase):
    facecam = {"x": 70, "y": 10, "w": 310, "h": 240, "share": 1.0, "source": [1920, 1080]}
    crop = {"times": [0.0, 5.0], "x": [400, 400], "y": [0, 0],
            "crop_w": 608, "crop_h": 1080, "source": [1920, 1080],
            "coverage": 1.0, "faces": 10, "samples": 10}

    def test_band_bottom(self):
        chain = render._stream_chain(1080, 1920, self.crop, self.facecam,
                                     "band", "universal")
        self.assertIn(f"overlay=0:{1920 - render.BAND_H}", chain)
        self.assertIn(f"scale=1080:{render.BAND_H}", chain)
        self.assertIn("crop=310:240:70:10", chain)

    def test_band_top(self):
        chain = render._stream_chain(1080, 1920, self.crop, self.facecam,
                                     "band_top", "universal")
        self.assertIn("overlay=0:0", chain)
        self.assertIn(f"pad=1080:1920:0:{render.BAND_H}:black", chain)

    def test_base_is_cropped_for_band(self):
        for layout in ("band", "band_top"):
            chain = render._stream_chain(1080, 1920, self.crop, self.facecam,
                                         layout, "universal")
            self.assertIn("scale=1080:1280", chain, layout)

    def test_layouts_registry(self):
        self.assertEqual(set(render.STREAM_LAYOUTS), {"band", "band_top"})


class BandOptionsTest(unittest.TestCase):
    def test_layout_validation(self):
        from vertcut import pipeline

        for layout in ("band", "band_top"):
            self.assertEqual(pipeline.normalize_options({"layout": layout})["layout"], layout)
        self.assertEqual(pipeline.normalize_options({"layout": "face_third"})["layout"], "")

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
