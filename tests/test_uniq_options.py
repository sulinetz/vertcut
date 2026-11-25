"""Сквозные проверки уникализации: тайминги ASS и нормализация опций."""
import re
import unittest

from vertcut import pipeline, subtitles, timeline


def words(*pairs):
    return [{"word": f"w{i}", "start": a, "end": b} for i, (a, b) in enumerate(pairs)]


def last_dialogue_end(ass: str) -> float:
    ends = []
    for line in ass.splitlines():
        if not line.startswith("Dialogue:"):
            continue
        stamp = line.split(",")[2]
        h, m, s = stamp.split(":")
        ends.append(int(h) * 3600 + int(m) * 60 + float(s))
    return max(ends) if ends else 0.0


class AssTimingTest(unittest.TestCase):
    def test_subtitles_follow_jump_cuts(self):
        src = words((0.2, 1.0), (1.2, 2.0), (3.5, 4.2), (4.4, 5.2))
        plan = timeline.plan(src, 0.0, 6.0, speed=1.0)
        self.assertTrue(plan["cut"])
        ass = subtitles.build_ass(plan["words"], 0.0, plan["duration"])
        self.assertLessEqual(last_dialogue_end(ass), plan["duration"] + 0.6)
        # без пересчёта последнее слово оказалось бы в конце исходных 6 с
        self.assertLess(last_dialogue_end(ass), 6.0)

    def test_subtitles_after_speed(self):
        src = words((0.2, 1.0), (1.2, 2.0))
        plan = timeline.plan(src, 0.0, 2.0, speed=1.1)
        self.assertAlmostEqual(plan["duration"], 2.0 / 1.1, places=2)
        ass = subtitles.build_ass(plan["words"], 0.0, plan["duration"])
        self.assertLessEqual(last_dialogue_end(ass), plan["duration"] + 0.6)


class OptionsTest(unittest.TestCase):
    def test_defaults_off(self):
        opts = pipeline.normalize_options({})
        self.assertFalse(opts["hflip"])
        self.assertFalse(opts["jump_cuts"])
        self.assertFalse(opts["cut_zoom"])
        self.assertEqual(opts["speed"], 1.0)
        self.assertEqual(opts["pitch"], 1.0)
        self.assertEqual(opts["split_ratio"], 0.5)
        self.assertEqual(opts["bg_video"], "random")

    def test_clamps(self):
        self.assertEqual(pipeline.normalize_options({"speed": 2.0})["speed"], 1.1)
        self.assertEqual(pipeline.normalize_options({"speed": 0.5})["speed"], 1.0)
        self.assertEqual(pipeline.normalize_options({"pitch": 2.0})["pitch"], 1.05)
        self.assertEqual(pipeline.normalize_options({"tilt": 90})["tilt"], 3.0)
        self.assertEqual(pipeline.normalize_options({"split_ratio": 0.9})["split_ratio"], 0.85)
        self.assertEqual(pipeline.normalize_options({"split_ratio": 0.1})["split_ratio"], 0.25)

    def test_bad_bg_name_falls_back(self):
        self.assertEqual(pipeline.normalize_options({"bg_video": "../evil.mp4"})["bg_video"], "random")
        self.assertEqual(pipeline.normalize_options({"bg_video": "clip.mp4"})["bg_video"], "clip.mp4")

    def test_adhd_subtitles_default_middle(self):
        self.assertEqual(pipeline.normalize_options({"layout": "adhd"})["sub_position"], "middle")
        self.assertEqual(
            pipeline.normalize_options({"layout": "adhd", "sub_position": "top"})["sub_position"],
            "top")

    def test_unknown_layout_rejected(self):
        self.assertEqual(pipeline.normalize_options({"layout": "nope"})["layout"], "")


if __name__ == "__main__":
    unittest.main()
