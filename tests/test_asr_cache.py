"""Кэш распознавания: повторный запуск не транскрибирует заново без причины."""
from __future__ import annotations

import json
from pathlib import Path

from vertcut import app_settings, pipeline, transcribe


def make_cache(workdir: Path, media: Path, **opts) -> dict:
    data = {
        "language": "ru", "duration": 10.0,
        "segments": [{"start": 0.0, "end": 1.0, "text": "слово",
                      "words": [{"word": "слово", "start": 0.0, "end": 1.0}]}],
        "engine": "whisper-small",
        "cache_key": transcribe.transcript_key(media, **opts),
    }
    (workdir / "transcript.json").write_text(json.dumps(data, ensure_ascii=False),
                                             encoding="utf-8")
    return data


def test_cache_hit_with_same_key(tmp_path: Path):
    media = tmp_path / "source.mp4"
    media.write_bytes(b"x" * 100)
    workdir = tmp_path / "p1"
    workdir.mkdir()
    data = make_cache(workdir, media)
    assert pipeline._cached_transcript(workdir, media, None, None, {}) == data


def test_cache_miss_when_profile_or_model_changes(tmp_path: Path):
    media = tmp_path / "source.mp4"
    media.write_bytes(b"x" * 100)
    workdir = tmp_path / "p1"
    workdir.mkdir()
    make_cache(workdir, media)
    assert pipeline._cached_transcript(workdir, media, None, None,
                                       {"asr_profile": "max"}) is None
    assert pipeline._cached_transcript(workdir, media, None, None,
                                       {"whisper_model": "medium"}) is None


def test_cache_miss_when_dictionary_changes(tmp_path: Path, monkeypatch):
    media = tmp_path / "source.mp4"
    media.write_bytes(b"x" * 100)
    workdir = tmp_path / "p1"
    workdir.mkdir()
    make_cache(workdir, media)
    monkeypatch.setattr(app_settings, "asr_terms_list", lambda limit=50: ["OpenAI"])
    assert pipeline._cached_transcript(workdir, media, None, None, {}) is None


def test_cache_miss_when_file_changes(tmp_path: Path):
    media = tmp_path / "source.mp4"
    media.write_bytes(b"x" * 100)
    workdir = tmp_path / "p1"
    workdir.mkdir()
    make_cache(workdir, media)
    media.write_bytes(b"x" * 200)
    assert pipeline._cached_transcript(workdir, media, None, None, {}) is None


def test_old_transcript_without_key_is_not_reused(tmp_path: Path):
    media = tmp_path / "source.mp4"
    media.write_bytes(b"x" * 100)
    workdir = tmp_path / "p1"
    workdir.mkdir()
    (workdir / "transcript.json").write_text(json.dumps({
        "language": "ru", "segments": [{"start": 0, "end": 1, "text": "x", "words": []}],
    }), encoding="utf-8")
    assert pipeline._cached_transcript(workdir, media, None, None, {}) is None


def test_normalize_options_validates_asr_settings():
    opts = pipeline.normalize_options({
        "asr_profile": "MAX", "whisper_model": "turbo", "language": "RU-ru"})
    assert opts["asr_profile"] == "max"
    assert opts["whisper_model"] == "large-v3-turbo"
    assert opts["language"] == "ru"
    assert pipeline.normalize_options({"asr_profile": "gigantic"})["asr_profile"] == ""
    assert pipeline.normalize_options({"whisper_model": "nope"})["whisper_model"] == ""
    assert pipeline.normalize_options({"language": "auto"})["language"] == ""
