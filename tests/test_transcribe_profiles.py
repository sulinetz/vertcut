"""Профили Whisper, словарь терминов и ключ кэша распознавания."""
from __future__ import annotations

from pathlib import Path

import pytest

from vertcut import app_settings, transcribe


@pytest.fixture(autouse=True)
def clean_model():
    transcribe._reset_model()
    yield
    transcribe._reset_model()


@pytest.fixture
def no_env(monkeypatch):
    for name in ("VERTCUT_WHISPER", "VERTCUT_WHISPER_BEAM", "VERTCUT_WHISPER_BEST_OF",
                 "VERTCUT_WHISPER_TEMPS", "VERTCUT_WHISPER_RECHECK",
                 "VERTCUT_WHISPER_BATCH_SIZE", "VERTCUT_WHISPER_BATCH_MIN",
                 "VERTCUT_WHISPER_WEAK_LOGP", "VERTCUT_WHISPER_PROMPT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(app_settings, "whisper_model", lambda: "small")
    monkeypatch.setattr(app_settings, "asr_terms_list", lambda limit=50: [])
    return monkeypatch


def test_profile_models(no_env):
    assert transcribe.asr_config("fast")["model"] == "small"
    assert transcribe.asr_config("balance")["model"] == "large-v3-turbo"
    assert transcribe.asr_config("max")["model"] == "large-v3"
    assert transcribe.asr_config("")["model"] == "small"


def test_empty_profile_preserves_old_setting(no_env):
    no_env.setattr(app_settings, "whisper_model", lambda: "medium")
    cfg = transcribe.asr_config("")
    assert cfg["model"] == "medium"
    assert cfg["profile"] == ""


def test_explicit_model_wins_over_profile(no_env):
    assert transcribe.asr_config("max", "medium")["model"] == "medium"
    assert transcribe.asr_config("fast", "turbo")["model"] == "large-v3-turbo"


def test_env_model_wins_over_everything(no_env):
    no_env.setenv("VERTCUT_WHISPER", "base")
    assert transcribe.asr_config("max", "large-v3")["model"] == "base"


def test_profile_parameters(no_env):
    fast = transcribe.asr_config("fast")
    balance = transcribe.asr_config("balance")
    assert fast["beam"] == 1 and fast["recheck"] == 0
    assert balance["beam"] == 5 and balance["recheck"] == 8
    assert balance["temperatures"] == [0.0, 0.2]
    assert fast["batch"] >= balance["batch"]


def test_env_parameters_override_profile(no_env):
    no_env.setenv("VERTCUT_WHISPER_BEAM", "3")
    no_env.setenv("VERTCUT_WHISPER_RECHECK", "2")
    no_env.setenv("VERTCUT_WHISPER_TEMPS", "0.0,0.3")
    cfg = transcribe.asr_config("max")
    assert cfg["beam"] == 3
    assert cfg["recheck"] == 2
    assert cfg["temperatures"] == [0.0, 0.3]


def test_unknown_profile_falls_back_to_settings(no_env):
    assert transcribe.asr_config("gigantic")["profile"] == ""
    assert transcribe.asr_config("gigantic")["model"] == "small"


def test_terms_go_to_prompt(no_env):
    no_env.setattr(app_settings, "asr_terms_list", lambda limit=50: ["OpenAI", "GPT-5"])
    cfg = transcribe.asr_config("balance")
    assert "OpenAI" in cfg["prompt"] and "GPT-5" in cfg["prompt"]
    assert len(cfg["prompt"]) <= 600


def test_prompt_echo_knows_dictionary(no_env):
    prompt = transcribe.BASE_PROMPT + " Имена и термины: OpenRouter, DeepSeek."
    assert transcribe._prompt_echo("OpenRouter, DeepSeek, имена и термины", prompt)
    assert not transcribe._prompt_echo("Почему люди боятся начать своё дело", prompt)


def test_config_is_read_every_call(no_env):
    before = transcribe.asr_config("")["model"]
    no_env.setattr(app_settings, "whisper_model", lambda: "large-v3")
    after = transcribe.asr_config("")["model"]
    assert before == "small"
    assert after == "large-v3"


def test_transcript_key_depends_on_settings(tmp_path: Path, no_env):
    media = tmp_path / "audio.wav"
    media.write_bytes(b"x" * 100)
    base = transcribe.transcript_key(media)
    assert base == transcribe.transcript_key(media)
    assert base != transcribe.transcript_key(media, profile="fast")
    assert base != transcribe.transcript_key(media, model="large-v3")
    assert base != transcribe.transcript_key(media, language="ru")
    assert base != transcribe.transcript_key(media, audio_track=2)

    no_env.setattr(app_settings, "asr_terms_list", lambda limit=50: ["OpenAI"])
    assert transcribe.transcript_key(media) != base


def test_transcript_key_depends_on_file(tmp_path: Path, no_env):
    media = tmp_path / "audio.wav"
    media.write_bytes(b"x" * 100)
    first = transcribe.transcript_key(media)
    media.write_bytes(b"x" * 200)
    assert transcribe.transcript_key(media) != first


def test_single_model_slot(monkeypatch, no_env):
    loaded = []

    class FakeModel:
        def __init__(self, name, **kwargs):
            self.name = name
            loaded.append(name)

    import faster_whisper

    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeModel)
    monkeypatch.setattr(transcribe, "_device_candidates", lambda long_audio: [("cpu", "int8")])
    first = transcribe._get_model(config=transcribe.asr_config("fast"))
    same = transcribe._get_model(config=transcribe.asr_config("fast"))
    assert same is first
    second = transcribe._get_model(config=transcribe.asr_config("max"))
    assert second is not first
    assert loaded == ["small", "large-v3"]
    assert transcribe._MODEL is second


def test_model_cached_follows_profile(monkeypatch, tmp_path: Path, no_env):
    monkeypatch.setattr(transcribe, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(transcribe, "WHISPER_LOCAL_DIR", "")
    target = tmp_path / "models--Systran--faster-whisper-large-v3-turbo" / "snapshots" / "x"
    target.mkdir(parents=True)
    (target / "model.bin").write_bytes(b"x" * (1024 * 1024 + 1))
    assert transcribe.model_cached("balance")
    assert not transcribe.model_cached("max")
