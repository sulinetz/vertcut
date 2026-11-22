"""Таймлайн: склейки пауз, ускорение и пересчёт субтитров/кропа."""
import unittest

from vertcut import timeline


def words(*pairs):
    return [{"word": "w", "start": a, "end": b} for a, b in pairs]


class SpeechSegmentsTest(unittest.TestCase):
    def test_without_words_keeps_everything(self):
        self.assertEqual(timeline.speech_segments([], 0.0, 5.0), [(0.0, 5.0)])

    def test_drops_long_pause(self):
        segs = timeline.speech_segments(words((0.2, 1.0), (3.0, 4.0)), 0.0, 5.0)
        self.assertEqual(len(segs), 2)
        self.assertLess(segs[1][0], 3.0)
        self.assertGreater(segs[1][0], 2.0)

    def test_short_pause_is_kept(self):
        # пауза 0.3 с меньше порога — резать нечего
        segs = timeline.speech_segments(words((0.2, 1.0), (1.3, 2.0)), 0.0, 3.0)
        self.assertEqual(segs, [(0.0, 3.0)])

    def test_noise_fallback_keeps_whole_clip(self):
        # речь занимает 20% — похоже на ошибку VAD, лучше не резать
        segs = timeline.speech_segments(words((0.0, 1.0)), 0.0, 20.0)
        self.assertEqual(segs, [(0.0, 20.0)])

    def test_segments_are_relative_and_ordered(self):
        segs = timeline.speech_segments(words((11.0, 12.0), (15.0, 16.0)), 10.0, 18.0)
        self.assertTrue(all(0.0 <= a < b <= 8.0 for a, b in segs))
        self.assertEqual(segs, sorted(segs))


class RemapTest(unittest.TestCase):
    def test_remap_time_across_cut(self):
        segs = [(0.0, 2.0), (4.0, 5.0)]
        self.assertAlmostEqual(timeline.remap_time(1.0, segs), 1.0)
        self.assertAlmostEqual(timeline.remap_time(4.5, segs), 2.5)

    def test_remap_words_moves_second_speech(self):
        mapped = timeline.remap_words(words((0.0, 1.0), (4.0, 5.0)), [(0.0, 2.0), (4.0, 5.0)])
        self.assertEqual(len(mapped), 2)
        self.assertAlmostEqual(mapped[1]["start"], 2.0)
        self.assertAlmostEqual(mapped[1]["end"], 3.0)

    def test_speed_scales_words(self):
        mapped = timeline.scale_words(words((10.0, 12.0)), 10.0, 1.05)
        self.assertAlmostEqual(mapped[0]["start"], 0.0)
        self.assertAlmostEqual(mapped[0]["end"], 1.905, places=3)

    def test_plan_duration_matches_speed(self):
        plan = timeline.plan(words((0.0, 4.0)), 0.0, 4.0, speed=1.1)
        self.assertAlmostEqual(plan["duration"], 4.0 / 1.1, places=2)

    def test_crop_path_remapped(self):
        path = {"times": [0.0, 1.0, 4.0, 5.0], "x": [0, 10, 40, 50],
                "y": [0, 0, 0, 0], "crop_w": 100, "crop_h": 100, "source": [200, 200]}
        out = timeline.remap_crop_path(path, [(0.0, 2.0), (4.0, 5.0)], 1.0)
        self.assertEqual(len(out["times"]), len(out["x"]))
        self.assertEqual(out["times"], sorted(out["times"]))
        self.assertLessEqual(out["times"][-1], 3.0)


if __name__ == "__main__":
    unittest.main()
