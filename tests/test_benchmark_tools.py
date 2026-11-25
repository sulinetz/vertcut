"""Чистые помощники бенчмарка Whisper: WER, термины, окно субтитров."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_benchmark():
    path = ROOT / "tools" / "whisper_benchmark.py"
    spec = importlib.util.spec_from_file_location("whisper_benchmark", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


bench = load_benchmark()


def test_normalize_and_wer():
    assert bench.normalize_text("Привет, МИР! Ёлка") == ["привет", "мир", "елка"]
    assert bench.wer_percent("привет мир", "привет мир") == 0.0
    assert bench.wer_percent("привет мир", "привет") == 50.0
    assert bench.wer_percent("", "что угодно") == 0.0


def test_term_errors_only_for_terms_present_in_reference():
    ref = "Мы используем OpenAI и Kubernetes"
    hyp = "Мы используем OpenAI и кубернетес"
    wrong, checked = bench.term_errors(ref, hyp, ["OpenAI", "Kubernetes", "GPT-5"])
    assert (wrong, checked) == (1, 2)
    assert bench.term_errors(ref, ref, None) == (0, 0)


def test_slice_reference_uses_word_timings_and_padding():
    cues = [{"words": [
        {"word": "до", "start": 8.0, "end": 9.0},
        {"word": "внутри", "start": 10.2, "end": 11.0},
        {"word": "ещё", "start": 12.0, "end": 12.5},
        {"word": "после", "start": 20.0, "end": 21.0},
    ]}]
    assert bench.slice_reference(cues, 10.0, 15.0) == "внутри ещё"
    # допуск 0.2 с ловит слово, начинающееся чуть раньше окна
    assert bench.slice_reference(cues, 8.6, 15.0) == "до внутри ещё"


def test_timing_stats_counts_sane_words():
    segments = [{"words": [
        {"word": "a", "start": 0.0, "end": 0.4},
        {"word": "b", "start": 0.5, "end": 0.9},
        {"word": "c", "start": 1.0, "end": 5.0},
    ]}]
    stats = bench.timing_stats(segments)
    assert stats["words"] == 3
    assert stats["median_word"] == 0.4
    assert stats["sane_share"] == 0.667


def test_punctuation_count():
    assert bench.punctuation_count("Привет, мир! Как дела?") == 3
