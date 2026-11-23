"""Тесты подбора клипов: границы, контекст, завершённость и разнообразие.

Запуск: .venv312/bin/python -m unittest tests.test_analyze -v
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from vertcut import analyze


def make_segment(sentences, step=0.32, pause=0.45, start_at=0.0):
    """Собирает «сырой» вывод Whisper: слова с таймингами и пунктуацией."""
    words = []
    t = start_at
    for sentence in sentences:
        for token in sentence.split():
            dur = max(0.16, step * (1 + 0.05 * len(token)))
            words.append({"word": token, "start": round(t, 3), "end": round(t + dur, 3)})
            t += dur
        t += pause
    return [{"start": words[0]["start"], "end": words[-1]["end"],
             "text": " ".join(w["word"] for w in words), "words": words}]


class ContextHelpersTest(unittest.TestCase):
    def test_filler_start_uses_word_boundaries(self):
        self.assertFalse(analyze._has_filler_start("Нужно проверить"))
        self.assertFalse(analyze._has_filler_start("Также добавлю"))
        self.assertFalse(analyze._has_filler_start("Something went wrong"))
        self.assertTrue(analyze._has_filler_start("Ну вот и всё"))
        self.assertTrue(analyze._has_filler_start("So, we tried again"))
        self.assertTrue(analyze._has_filler_start("Короче, слушай"))
        self.assertTrue(analyze._has_filler_start("ну"))

    def test_starts_with_context(self):
        self.assertTrue(analyze._starts_with_context({"text": "Потому что мы так решили."}))
        self.assertTrue(analyze._starts_with_context({"text": "Это сработало."}))
        self.assertTrue(analyze._starts_with_context({"text": "So we tried again."}))
        self.assertFalse(analyze._starts_with_context({"text": "Мы запустили продукт за неделю."}))
        self.assertFalse(analyze._starts_with_context({"text": "Команда работала без выходных."}))

    def test_ends_with_continuation(self):
        self.assertTrue(analyze._ends_with_continuation({"text": "Мы сделали это, потому что"}))
        self.assertTrue(analyze._ends_with_continuation({"text": "И тогда я понял,"}))
        self.assertTrue(analyze._ends_with_continuation({"text": "Пользователи, которые"}))
        self.assertFalse(analyze._ends_with_continuation({"text": "Это сработало."}))
        self.assertFalse(analyze._ends_with_continuation({"text": "Вы знаете, что?"}))


class ExtendWindowTest(unittest.TestCase):
    def _sents(self):
        raw = make_segment([
            "Мы запустили продукт за неделю.",
            "Потому что команда работала без выходных.",
            "Результат нас удивил.",
        ])
        return analyze.build_sentences(raw)

    def test_extends_back_to_setup(self):
        sents = self._sents()
        i, j = analyze._extend_window(sents, 1, 2, max_dur=60)
        self.assertEqual(i, 0, "клип, начинающийся с «Потому что», обязан захватить завязку")

    def test_does_not_extend_when_self_contained(self):
        sents = self._sents()
        i, j = analyze._extend_window(sents, 0, 1, max_dur=60)
        self.assertEqual(i, 0)

    def test_extends_forward_to_conclusion(self):
        raw = make_segment([
            "Мы выросли в десять раз за месяц.",
            "И знаете, что самое важное?",
            "Мы не потратили ни рубля на рекламу.",
        ])
        sents = analyze.build_sentences(raw)
        i, j = analyze._extend_window(sents, 0, 1, max_dur=60)
        self.assertEqual(j, 2, "нельзя обрывать клип на «и знаете, что?» без ответа")


class FindSegmentsTest(unittest.TestCase):
    def _find(self, sentences, duration, **kwargs):
        raw = make_segment(sentences)
        with mock.patch.object(analyze, "energy_curve", return_value=([], -30.0)):
            return analyze.find_segments(raw, Path("dummy.mp4"), duration, **kwargs)

    def test_boundaries_snap_to_sentences(self):
        sentences = [
            "Сегодня поговорим про запуск продукта.",
            "Почему это важно именно сейчас?",
            "Потому что рынок меняется быстрее, чем мы успеваем.",
            "Мы потратили два месяца на исследование.",
            "И нашли неожиданную закономерность.",
            "Оказалось, люди хотят простые решения.",
            "Вот почему мы переписали приложение с нуля.",
            "Результат превзошёл ожидания.",
        ]
        raw_sents = analyze.build_sentences(make_segment(sentences))
        clips = self._find(sentences, duration=raw_sents[-1]["end"] + 1, count=4)
        self.assertTrue(clips)
        starts = [s["start"] for s in raw_sents]
        ends = [s["end"] for s in raw_sents]
        for clip in clips:
            self.assertTrue(any(abs(clip["start"] - x) < 0.6 for x in starts),
                            f"клип начинается не на границе фразы: {clip['start']}")
            self.assertTrue(any(abs(clip["end"] - x) < 0.6 for x in ends),
                            f"клип заканчивается не на границе фразы: {clip['end']}")
            self.assertLessEqual(clip["duration"], 60.001)

    def test_no_clip_starts_mid_context(self):
        sentences = [
            "Мы запустили продукт за неделю.",
            "Потому что команда работала без выходных и праздников.",
            "Это дало нам десять тысяч пользователей за месяц.",
            "Но главное было впереди.",
            "Мы заметили, что люди возвращаются каждый день.",
            "И это изменило всё.",
        ]
        raw_sents = analyze.build_sentences(make_segment(sentences))
        clips = self._find(sentences, duration=raw_sents[-1]["end"] + 1, count=4)
        context_start = raw_sents[1]["start"]
        for clip in clips:
            self.assertGreater(abs(clip["start"] - context_start), 0.6,
                               "клип начался с «Потому что…» без завязки")

    def test_no_clip_ends_on_open_thought(self):
        sentences = [
            "Мы выросли в десять раз за месяц.",
            "И знаете, что самое важное?",
            "Мы не потратили ни рубля на рекламу.",
            "Потому что ставка была на продукт, а не на маркетинг.",
        ]
        raw_sents = analyze.build_sentences(make_segment(sentences))
        clips = self._find(sentences, duration=raw_sents[-1]["end"] + 1, count=4)
        open_end = raw_sents[1]["end"]
        for clip in clips:
            self.assertGreater(abs(clip["end"] - open_end), 0.6,
                               "клип оборвался на «и знаете, что?» без ответа")

    def test_spreads_across_timeline(self):
        strong = [
            "Почему это работает? Секрет в одном.",
            "Никто не ожидал такого результата.",
            "Это была ошибка, которая стоила миллион.",
            "Оказалось, правда совсем в другом.",
        ]
        filler = [
            "Дальше мы долго обсуждали детали и процессы.",
            "Потом перешли к следующей теме разговора.",
            "Затем вернулись к вопросам аудитории.",
            "После этого поговорили про инструменты.",
        ]
        sentences = strong + filler * 3 + strong[:1]
        raw = make_segment(sentences)
        duration = raw[0]["end"] + 1
        clips = self._find(sentences, duration=duration, count=4,
                           min_dur=8, max_dur=40, target_dur=18)
        self.assertGreaterEqual(len(clips), 2)
        self.assertTrue(any(c["start"] > duration * 0.4 for c in clips),
                        "все клипы собрались в начале видео — нет разнообразия")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class RetimeWordsTest(unittest.TestCase):
    def _words(self):
        return [
            {"word": "мы", "start": 0.0, "end": 0.3},
            {"word": "нашли", "start": 0.4, "end": 0.9},
            {"word": "бак", "start": 1.0, "end": 1.4},
            {"word": "в", "start": 1.5, "end": 1.6},
            {"word": "экспорте", "start": 1.7, "end": 2.2},
        ]

    def test_fixes_word_and_keeps_timing(self):
        from vertcut import subtitles

        out = subtitles.retime_words(self._words(), "мы нашли баг в экспорте")
        self.assertEqual([w["word"] for w in out], ["мы", "нашли", "баг", "в", "экспорте"])
        self.assertAlmostEqual(out[2]["start"], 1.0, places=2)
        self.assertAlmostEqual(out[2]["end"], 1.4, places=2)

    def test_inserted_words_get_time_slice(self):
        from vertcut import subtitles

        out = subtitles.retime_words(self._words(), "мы нашли баг в новом экспорте")
        self.assertEqual(len(out), 6)
        self.assertEqual(out[4]["word"], "новом")
        self.assertGreaterEqual(out[4]["start"], out[3]["start"])

    def test_empty_text_means_no_subtitles(self):
        from vertcut import subtitles

        self.assertEqual(subtitles.retime_words(self._words(), "   "), [])


class SrtExportTest(unittest.TestCase):
    def test_srt_has_timing_lines(self):
        from vertcut import subtitles

        words = [{"word": "Привет", "start": 1.0, "end": 1.4},
                 {"word": "мир.", "start": 1.5, "end": 2.0},
                 {"word": "Второй", "start": 2.6, "end": 3.0},
                 {"word": "ряд.", "start": 3.1, "end": 3.6}]
        srt = subtitles.to_srt(words, 1.0, 4.0)
        self.assertIn(" --> ", srt)
        self.assertIn("00:00:00,000 --> 00:00:01,000", srt)
        self.assertEqual(srt.count(" --> "), 2)
