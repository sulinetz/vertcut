"""Композиция: слои, единые границы настроек и пересчёт времени."""
from __future__ import annotations

import unittest

from vertcut import composition, pipeline, timeline

CLIP = {"id": "c1", "project_id": "p1", "start": 100.0, "end": 110.0,
        "words": [], "settings": {}, "idx": 0, "title": "t", "hook": "",
        "caption": ""}


class SchemaCoverageTest(unittest.TestCase):
    def test_every_clip_setting_has_spec(self):
        missing = [key for key in pipeline.CLIP_SETTING_KEYS
                   if key not in composition.SPEC]
        self.assertEqual(missing, [])

    def test_defaults_match_project_defaults(self):
        for key in pipeline.CLIP_SETTING_KEYS:
            self.assertEqual(composition.SPEC[key].default,
                             pipeline.DEFAULT_OPTIONS[key], key)

    def test_schema_describes_every_setting(self):
        data = composition.schema()
        keys = [item["key"] for item in data["settings"]]
        self.assertEqual(len(keys), len(set(keys)))
        for item in data["settings"]:
            self.assertIn(item["type"],
                          ("int", "float", "bool", "choice", "events", "text"), item)
            self.assertTrue(item["label"], item)
            self.assertTrue(item["hint"], item)
            if item["type"] in ("int", "float"):
                self.assertIsNotNone(item["min"], item)
                self.assertIsNotNone(item["max"], item)
                self.assertLessEqual(item["min"], item["max"], item)
                self.assertGreater(item["step"], 0, item)
                self.assertGreaterEqual(item["default"], item["min"], item)
                self.assertLessEqual(item["default"], item["max"], item)
            if item["type"] == "choice":
                self.assertIn(item["default"], item["choices"], item)

    def test_layers_cover_all_settings_and_order(self):
        data = composition.schema()
        names = [layer["name"] for layer in data["layers"]]
        self.assertEqual(names, list(composition.LAYER_ORDER))
        covered = {key for layer in data["layers"] for key in layer["settings"]}
        self.assertEqual(covered, set(pipeline.CLIP_SETTING_KEYS))
        video = [layer for layer in data["layers"] if layer["z"] is not None]
        zs = [layer["z"] for layer in video]
        self.assertEqual(zs, sorted(zs))
        z = {layer["name"]: layer["z"] for layer in data["layers"]}
        self.assertLess(z["main"], z["ads"])
        self.assertLess(z["ads"], z["subtitles"])
        self.assertLess(z["subtitles"], z["graphics"])

    def test_active_layers(self):
        layers = {item["name"]: item for item in composition.layers({
            "layout": "adhd", "music_volume": 12,
            "ad_events": [{"kind": "overlay"}, {"kind": "replace"}],
        })}
        self.assertTrue(layers["adhd_bottom"]["active"])
        self.assertTrue(layers["ads"]["active"])
        self.assertEqual(layers["ads"]["overlays"], 1)
        self.assertEqual(layers["ads"]["inserts"], 1)
        self.assertTrue(layers["music"]["active"])
        self.assertTrue(layers["graphics"]["active"])

        quiet = {item["name"]: item for item in composition.layers({
            "layout": "", "music_volume": 0, "show_hook": False,
            "subtitles": False, "ad_events": [],
        })}
        self.assertFalse(quiet["adhd_bottom"]["active"])
        self.assertFalse(quiet["ads"]["active"])
        self.assertFalse(quiet["music"]["active"])
        self.assertFalse(quiet["subtitles"]["active"])
        self.assertFalse(quiet["graphics"]["active"])


class ClampParityTest(unittest.TestCase):
    CASES = (
        ("speed", 2.0), ("speed", 0.5), ("pitch", 0.5), ("pitch", 1.2),
        ("tilt", 9), ("tilt", -1), ("split_ratio", 0.9), ("split_ratio", 0.1),
        ("sub_size", 40), ("sub_size", 999), ("sub_offset", 9999),
        ("sub_offset", "abc"), ("line_gap", -5), ("line_gap", 999),
        ("zoom", 200), ("bitrate", 999), ("music_volume", -3),
        ("adhd_bottom_volume", 99), ("adhd_top_scale", 0.1),
        ("adhd_bottom_speed", 9), ("audio_offset", 999),
        ("audio_track", 99), ("external_audio_track", -9),
        ("aspect", "7:8"), ("mode", "??"), ("accent", "??"),
        ("sub_position", "??"), ("look", "??"), ("layout", "??"),
        ("vignette", "false"), ("hflip", "true"),
    )

    def test_parity_with_normalize_options(self):
        for key, raw in self.CASES:
            self.assertEqual(composition.clamp_value(key, raw),
                             pipeline.normalize_options({key: raw})[key],
                             f"{key}={raw!r}")

    def test_strict_rejects_garbage(self):
        with self.assertRaises(composition.CompositionError):
            composition.clamp_strict("sub_size", "abc")
        with self.assertRaises(composition.CompositionError):
            composition.clamp_strict("layout", "sideways")
        self.assertEqual(composition.clamp_strict("speed", 2.0), 1.1)

    def test_old_settings_roundtrip(self):
        stored = {
            "aspect": "9:16", "layout": "adhd", "split_ratio": 0.6,
            "sub_size": 132, "sub_offset": 40, "line_gap": 10,
            "adhd_top_scale": 1.1, "adhd_bottom_volume": 5,
            "speed": 1.05, "pitch": 1.0, "music_volume": 8,
            "ads_enabled": True, "ad_events": [],
        }
        self.assertEqual(composition.apply(stored), stored)
        once = pipeline.normalize_options(stored)
        twice = pipeline.normalize_options(once)
        self.assertEqual(once, twice)

    def test_clean_clip_edit_uses_same_ranges(self):
        from vertcut import main

        data = main._clean_clip_edit(main.ClipEdit(sub_size=999, speed=2.0,
                                                   split_ratio=0.9, tilt=9))
        self.assertEqual(data["sub_size"], 180)
        self.assertEqual(data["speed"], 1.1)
        self.assertEqual(data["split_ratio"], 0.85)
        self.assertEqual(data["tilt"], 3.0)


class AdTimelineTest(unittest.TestCase):
    def _timeline(self):
        words = [{"word": f"w{i}", "start": 100.0 + i, "end": 100.5 + i}
                 for i in range(10)]
        clip = {**CLIP, "words": words}
        settings = {"ad_events": [{"id": "r1", "asset": "a1", "kind": "replace",
                                   "start": 104.0, "duration": 2.0}]}
        return clip, settings, pipeline.clip_timeline(clip, settings)

    def test_inserts_match_timeline_module(self):
        clip, settings, tl = self._timeline()
        plan = composition.ad_inserts(clip, settings, tl)
        manual = timeline.insert_spans(
            tl["segments"] or [(0.0, clip["end"] - clip["start"])],
            [{"id": "r1", "kind": "replace", "start": 4.0, "duration": 2.0}],
            speed=tl["speed"], duration=tl["length"])
        self.assertEqual([(i["at"], i["duration"], i["final_start"]) for i in plan["inserts"]],
                         [(i["at"], i["duration"], i["final_start"]) for i in manual["inserts"]])
        self.assertEqual(plan["duration"], manual["duration"])

    def test_inserts_can_be_limited_to_resolved_events(self):
        clip, settings, tl = self._timeline()
        self.assertEqual(composition.ad_inserts(clip, settings, tl, [])["inserts"], [])
        plan = composition.ad_inserts(clip, settings, tl,
                                      settings["ad_events"])
        self.assertEqual(len(plan["inserts"]), 1)

    def test_event_window_matches_manual_formula(self):
        clip, settings, tl = self._timeline()
        plan = composition.ad_inserts(clip, settings, tl)
        segments = tl["segments"] or [(0.0, clip["end"] - clip["start"])]
        start, end = timeline.event_window(
            1.0, 3.0, segments=segments, speed=tl["speed"],
            inserts=plan["inserts"], duration=plan["duration"])
        manual_start = timeline.inserted_time(
            timeline.remap_time(1.0, segments, tl["speed"]),
            plan["inserts"], inclusive=True)
        manual_end = timeline.inserted_time(
            timeline.remap_time(3.0, segments, tl["speed"]),
            plan["inserts"], inclusive=False)
        self.assertEqual(start, manual_start)
        self.assertEqual(end, manual_end)

    def test_insert_window(self):
        start, end = timeline.insert_window({"final_start": 2.0, "duration": 1.5})
        self.assertEqual((start, end), (2.0, 3.5))

    def test_clip_composition_route(self):
        from unittest import mock

        from vertcut import main

        clip = {**CLIP, "settings": {"layout": "adhd",
                                    "ad_events": [{"kind": "overlay"}]}}
        with mock.patch.object(main.db, "get_clip", lambda _c: dict(clip)):
            data = main.clip_composition("c1")
        active = {item["name"]: item["active"] for item in data["layers"]}
        self.assertTrue(active["adhd_bottom"])
        self.assertTrue(active["ads"])


if __name__ == "__main__":
    unittest.main()
