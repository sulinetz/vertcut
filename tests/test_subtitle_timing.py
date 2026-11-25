"""Приблизительные тайминги слов из готовых субтитров доходят до клипа."""
from __future__ import annotations

from pathlib import Path

from vertcut import analyze, pipeline, utils

SRT = """1
00:00:01,000 --> 00:00:04,000
Привет, это тестовая фраза.

2
00:00:05,000 --> 00:00:07,000
Вторая реплика.
"""


def test_srt_words_are_marked_approx(tmp_path: Path):
    path = tmp_path / "subtitles.srt"
    path.write_text(SRT, encoding="utf-8")
    segments = utils.parse_subtitles(path)
    words = [word for seg in segments for word in seg["words"]]
    assert words
    assert all(word["timing"] == "approx" for word in words)


def test_build_sentences_keeps_timing(tmp_path: Path):
    path = tmp_path / "subtitles.srt"
    path.write_text(SRT, encoding="utf-8")
    sentences = analyze.build_sentences(utils.parse_subtitles(path))
    assert sentences
    assert all(sentence["timing"] == "approx" for sentence in sentences)
    assert all(word.get("timing") == "approx"
               for sentence in sentences for word in sentence["words"])


def test_whisper_words_stay_exact():
    segments = [{"start": 0.0, "end": 1.0, "text": "раз два",
                 "words": [{"word": "раз", "start": 0.0, "end": 0.4},
                           {"word": "два", "start": 0.5, "end": 1.0}]}]
    sentences = analyze.build_sentences(segments)
    assert all("timing" not in sentence for sentence in sentences)
    assert pipeline._words_timing(sentences[0]["words"]) == "exact"


def test_words_timing_detects_approx():
    assert pipeline._words_timing([{"word": "a", "timing": "approx"}]) == "approx"
    assert pipeline._words_timing([{"word": "a"}, {"word": "b"}]) == "exact"
    assert pipeline._words_timing([]) == "exact"
