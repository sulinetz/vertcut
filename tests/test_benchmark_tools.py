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

def test_download_item_reuses_cached_media(tmp_path, monkeypatch):
    """Повторный запуск после сбоя не должен качать материал заново."""
    import sys
    import types

    workdir = tmp_path / "item"
    workdir.mkdir()
    audio = workdir / "audio.wav"
    subs = workdir / "sub.ru.vtt"
    audio.write_bytes(b"RIFF")
    subs.write_text("WEBVTT\n", encoding="utf-8")

    class Boom:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("сеть не должна вызываться при кэше")

    monkeypatch.setitem(sys.modules, "yt_dlp", types.SimpleNamespace(YoutubeDL=Boom))
    found_audio, found_subs = bench.download_item("https://example.com/x", workdir, "ru")
    assert Path(found_audio) == audio
    assert Path(found_subs) == subs


def test_main_writes_markdown_file(tmp_path, monkeypatch):
    import json

    items = tmp_path / "items.json"
    items.write_text(json.dumps({"items": [
        {"url": "https://example.com/x", "start": 0, "duration": 60, "kind": "тест"}
    ]}), encoding="utf-8")
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"")
    subs = tmp_path / "s.vtt"
    subs.write_text("WEBVTT\n", encoding="utf-8")
    monkeypatch.setattr(bench, "download_item", lambda *_a, **_k: (audio, subs))
    monkeypatch.setattr(bench, "cut_audio", lambda *_a, **_k: audio)
    monkeypatch.setattr(bench.utils, "parse_vtt", lambda _p: [
        {"words": [{"word": word, "start": i * 0.5, "end": i * 0.5 + 0.4}
                   for i, word in enumerate(
                       ["привет", "мир", "это", "тестовая", "запись", "речи"])]}])
    monkeypatch.setattr(bench, "evaluate", lambda *_a, **_k: {
        "config": "profile=fast model=small", "wer": 12.5,
        "terms_wrong": 0, "terms_checked": 1, "punct_ref": 3, "punct_hyp": 2,
        "words": 10, "median_word": 0.4, "sane_share": 1.0, "speed": 30.0,
        "vram_mb": 3000, "ram_mb": 900,
    })
    out = tmp_path / "bench.md"
    code = bench.main(["--items", str(items), "--profiles", "fast",
                       "--out", str(out)])
    assert code == 0
    assert out.exists()
    assert "WER" in out.read_text(encoding="utf-8")
