"""Единый список настроек клипа и строгая нормализация типов."""
from __future__ import annotations

import unittest

from vertcut import live, main, pipeline


class NormalizationTest(unittest.TestCase):
    def test_bools_accept_strings_and_numbers(self):
        for value, expected in (("0", False), ("false", False), ("no", False),
                                (0, False), ("1", True), ("true", True), (1, True),
                                (True, True), (False, False)):
            opts = pipeline.normalize_options({"subtitles": value, "uppercase": value,
                                               "show_hook": value})
            self.assertIs(opts["subtitles"], expected, f"subtitles={value!r}")
            self.assertIs(opts["uppercase"], expected, f"uppercase={value!r}")
            self.assertIs(opts["show_hook"], expected, f"show_hook={value!r}")

    def test_small_sub_size_is_clamped_not_replaced(self):
        self.assertEqual(pipeline.normalize_options({"sub_size": 40})["sub_size"], 70)
        self.assertEqual(pipeline.normalize_options({"sub_size": 69})["sub_size"], 70)
        self.assertEqual(pipeline.normalize_options({"sub_size": 118})["sub_size"], 118)
        self.assertEqual(pipeline.normalize_options({"sub_size": 500})["sub_size"], 180)


class SettingsKeysTest(unittest.TestCase):
    def test_clip_settings_use_the_shared_list(self):
        opts = pipeline.normalize_options({})
        settings = pipeline._clip_settings(opts)
        for key in pipeline.CLIP_SETTING_KEYS:
            self.assertIn(key, settings)
        self.assertEqual(settings["focus_x"], 0.5)

    def test_clip_edit_fields_are_known_settings(self):
        extra = {"text", "start", "end", "hook", "title", "caption", "focus_x"}
        self.assertLessEqual(set(main.ClipEdit.model_fields) - extra,
                             set(pipeline.CLIP_SETTING_KEYS))

    def test_live_settings_cover_same_keys(self):
        settings = live._settings(pipeline.normalize_options({}))
        for key in pipeline.CLIP_SETTING_KEYS:
            self.assertIn(key, settings)

    def test_rerender_accepts_shared_keys(self):
        clip = {"id": "c1", "project_id": "p1", "start": 0.0, "end": 10.0,
                "words": [], "settings": {}, "status": "ready", "idx": 0,
                "title": "t", "hook": "", "caption": ""}
        captured = {}
        from unittest import mock

        def update(_cid, **fields):
            captured.update(fields)

        with mock.patch.object(pipeline.db, "get_clip", lambda _c: dict(clip)), \
             mock.patch.object(pipeline.db, "get_project",
                               lambda _p: {"id": "p1", "source": "src.mp4",
                                           "options": {}, "duration": 10.0}), \
             mock.patch.object(pipeline.db, "update_clip", update), \
             mock.patch.object(pipeline, "PROJECTS_DIR", __import__("pathlib").Path(".")), \
             mock.patch.object(pipeline, "_render_one", lambda *a, **k: None):
            try:
                pipeline.rerender_clip("c1", {"subtitles": False, "show_hook": False})
            except RuntimeError:
                pass
        settings = captured.get("settings") or {}
        self.assertIs(settings.get("subtitles"), False)
        self.assertIs(settings.get("show_hook"), False)


if __name__ == "__main__":
    unittest.main()