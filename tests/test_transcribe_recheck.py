"""Детекторы сомнительных мест и повторное распознавание фрагмента."""
from __future__ import annotations

from types import SimpleNamespace

from vertcut import app_settings, transcribe


def seg(text: str, start: float = 0.0, end: float = 2.0,
        logprob: float = -0.1, no_speech: float = 0.0) -> dict:
    return {"text": text, "start": start, "end": end,
            "quality": {"avg_logprob": logprob, "no_speech_prob": no_speech}}


def part(text: str, start: float = 0.0, end: float = 2.0,
         logprob: float = -0.1) -> SimpleNamespace:
    tokens = text.split()
    step = (end - start) / max(1, len(tokens))
    return SimpleNamespace(
        text=text, start=start, end=end, avg_logprob=logprob, no_speech_prob=0.0,
        words=[SimpleNamespace(word=token, start=start + i * step,
                               end=start + (i + 1) * step)
               for i, token in enumerate(tokens)],
    )


def test_clean_segment_has_no_reasons():
    assert transcribe._suspect_reasons(seg("Почему люди боятся начать дело")) == []


def test_low_logprob_and_noise():
    assert "logprob" in transcribe._suspect_reasons(seg("тихая фраза", logprob=-0.9))
    reasons = transcribe._suspect_reasons(seg("тихая фраза", logprob=-0.5, no_speech=0.6))
    assert "noise" in reasons


def test_repeats_are_detected():
    assert "repeat" in transcribe._suspect_reasons(seg("да да да да"))
    many = "слово " * 8
    assert "repeat" in transcribe._suspect_reasons(seg(many))


def test_broken_words_are_detected():
    long_word = "a" * 30
    assert "long_word" in transcribe._suspect_reasons(seg(f"это {long_word} слово"))
    assert "short_word" in transcribe._suspect_reasons(seg("это б слово"))
    # настоящие односложные слова не считаются ошибкой
    assert "short_word" not in transcribe._suspect_reasons(seg("и я в этом доме"))


def test_short_and_too_fast_segments():
    assert "short" in transcribe._suspect_reasons(seg("ok"))
    assert "too_fast" in transcribe._suspect_reasons(seg("раз два три четыре", 0.0, 0.2))


def test_logprob_jump_between_neighbors():
    prev = seg("раньше", 0.0, 1.0, logprob=-1.0)
    nxt = seg("позже", 3.0, 4.0, logprob=-1.0)
    reasons = transcribe._suspect_reasons(seg("середина", 1.5, 2.5, logprob=-0.4), prev, nxt)
    assert "logprob_jump" in reasons


def _run_recheck(monkeypatch, tmp_path, segment, new_parts):
    monkeypatch.setattr(transcribe, "_cut_window", lambda *a, **k: True)
    monkeypatch.setattr(transcribe, "_decode", lambda *a, **k: (new_parts, None))
    monkeypatch.setattr(app_settings, "asr_terms_list", lambda limit=50: [])
    monkeypatch.delenv("VERTCUT_WHISPER_TEMPS", raising=False)
    config = transcribe.asr_config("fast")
    return transcribe._recheck(None, tmp_path / "a.wav", tmp_path, [segment],
                               "ru", None, 5, config)


def test_structural_error_is_fixed_without_score_gain(monkeypatch, tmp_path):
    segment = seg("да да да да", 0.0, 2.0, logprob=-0.1)
    fixed = _run_recheck(monkeypatch, tmp_path, segment,
                         [part("да, это история", 0.0, 2.0, logprob=-0.1)])
    assert fixed == 1
    assert segment["text"] == "да, это история"
    assert segment["quality"]["recheck_reason"] == "repeat"


def test_clean_lowprob_replacement_needs_better_score(monkeypatch, tmp_path):
    segment = seg("неразборчиво", 0.0, 2.0, logprob=-0.80)
    fixed = _run_recheck(monkeypatch, tmp_path, segment,
                         [part("неразборчиво", 0.0, 2.0, logprob=-0.80)])
    assert fixed == 0


def test_worse_text_is_not_accepted(monkeypatch, tmp_path):
    segment = seg("да да да да", 0.0, 2.0, logprob=-0.1)
    fixed = _run_recheck(monkeypatch, tmp_path, segment,
                         [part("совсем другой текст", 0.0, 2.0, logprob=-0.7)])
    assert fixed == 0
    assert segment["text"] == "да да да да"
