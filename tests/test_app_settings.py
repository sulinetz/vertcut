"""Ключи API: хранение, маскирование и запасной путь через окружение."""
from __future__ import annotations

from vertcut import app_settings


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings, "FILE", tmp_path / "app_settings.json")
    for name in ("DEEPSEEK_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
                 "OPENROUTER_API_KEY", "POLZA_API_KEY", "POLZA_AI_API_KEY",
                 "GEMINI_PROXY", "HTTPS_PROXY", "HTTP_PROXY"):
        monkeypatch.delenv(name, raising=False)


def test_polza_key_model_env_and_provider(tmp_path, monkeypatch):
    from vertcut import semantic

    _isolate(tmp_path, monkeypatch)
    app_settings.save({"polza_key": "pza_secret_987654",
                       "polza_model": "google/gemini-2.5-flash"})
    public = app_settings.public()
    assert public["polza_key_set"] is True
    assert public["polza_key_hint"].endswith("7654")
    assert "987654" not in str(public)
    assert public["polza_model"] == "google/gemini-2.5-flash"
    assert app_settings.api_key("polza") == "pza_secret_987654"
    assert "google/gemini-2.5-flash" in public["model_choices"]["polza"]

    app_settings.save({"polza_key": "", "polza_model": "deepseek/deepseek-chat"})
    assert app_settings.api_key("polza") == "pza_secret_987654"
    app_settings.save({"clear_polza_key": True})
    assert app_settings.api_key("polza") == ""

    monkeypatch.setenv("POLZA_API_KEY", "env-polza")
    assert app_settings.api_key("polza") == "env-polza"
    monkeypatch.delenv("POLZA_API_KEY")
    monkeypatch.setenv("POLZA_AI_API_KEY", "env-polza-ai")
    assert app_settings.api_key("polza") == "env-polza-ai"

    assert "polza" in semantic.PROVIDERS
    assert semantic.PROVIDERS["polza"]["url"] == "https://polza.ai/api/v1/chat/completions"
    assert semantic.PROVIDERS["polza"]["models_url"] == "https://polza.ai/api/v1/models"
    assert "polza" in semantic.PICKERS

    parsed = semantic._parse_models("polza", {"data": [
        {"id": "google/gemini-2.5-flash", "name": "Gemini 2.5 Flash", "context_length": 1000000},
        {"id": "deepseek/deepseek-chat", "name": "DeepSeek Chat", "context_length": None},
    ]})
    assert [m["id"] for m in parsed] == ["deepseek/deepseek-chat", "google/gemini-2.5-flash"]
    assert parsed[0]["context"] == 0
    assert parsed[1]["context"] == 1000000

    semantic._MODELS_CACHE.pop("polza", None)
    monkeypatch.setattr(semantic.app_settings, "api_key", lambda _p: "")
    monkeypatch.setattr(semantic, "_get_json", lambda url, key="", proxy=None: {
        "data": [{"id": "deepseek/deepseek-chat", "name": "DeepSeek Chat"}]
    })
    assert len(semantic.models_for("polza")) == 1
    semantic._MODELS_CACHE.pop("polza", None)

    monkeypatch.setattr(semantic.app_settings, "api_key", lambda _p: "pza-test")
    monkeypatch.setattr(semantic, "models_for", lambda _p: [{"id": "m1"}])
    res = semantic.check_key("polza")
    assert res["ok"] is True and res["models"] == 1


def test_openrouter_key_and_model(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    app_settings.save({"openrouter_key": "sk-or-v1-abcdef123456",
                       "openrouter_model": "deepseek/deepseek-r1"})
    public = app_settings.public()
    assert public["openrouter_key_set"] is True
    assert public["openrouter_key_hint"].endswith("3456")
    assert "abcdef123456" not in str(public)
    assert public["openrouter_model"] == "deepseek/deepseek-r1"
    assert app_settings.api_key("openrouter") == "sk-or-v1-abcdef123456"
    assert "deepseek/deepseek-r1" in public["model_choices"]["openrouter"]
    app_settings.save({"openrouter_key": "", "openrouter_model": "deepseek/deepseek-chat"})
    assert app_settings.api_key("openrouter") == "sk-or-v1-abcdef123456"
    app_settings.save({"clear_openrouter_key": True})
    assert app_settings.api_key("openrouter") == ""


def test_openrouter_env_fallback(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-openrouter")
    assert app_settings.api_key("openrouter") == "env-openrouter"


def test_openrouter_is_available_to_semantic():
    from vertcut import semantic

    assert "openrouter" in semantic.PROVIDERS
    assert semantic.PROVIDERS["openrouter"]["url"].startswith("https://openrouter.ai/")
    assert "openrouter" in semantic.PICKERS


def test_save_and_mask(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    app_settings.save({"deepseek_key": "sk-deepseek-12345678", "proxy": "http://127.0.0.1:7901"})
    public = app_settings.public()
    assert public["deepseek_key_set"] is True
    assert "sk-deepseek-12345678" not in str(public)
    assert public["deepseek_key_hint"].endswith("5678")
    assert public["proxy"] == "http://127.0.0.1:7901"
    assert app_settings.api_key("deepseek") == "sk-deepseek-12345678"
    # В интерфейс ключ не попадает даже частично.
    assert "12345678" not in public["deepseek_key_hint"]


def test_empty_key_does_not_clear_existing(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    app_settings.save({"gemini_key": "AIza-secret-0000"})
    app_settings.save({"gemini_key": "", "gemini_model": "gemini-pro-latest"})
    assert app_settings.api_key("gemini") == "AIza-secret-0000"
    assert app_settings.model_for("gemini") == "gemini-pro-latest"


def test_clear_key(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    app_settings.save({"deepseek_key": "sk-x-11112222"})
    app_settings.save({"clear_deepseek_key": True})
    assert app_settings.api_key("deepseek") == ""


def test_env_fallback(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "env-deepseek")
    monkeypatch.setenv("GOOGLE_API_KEY", "env-gemini")
    assert app_settings.api_key("deepseek") == "env-deepseek"
    assert app_settings.api_key("gemini") == "env-gemini"
    # Файл имеет приоритет над окружением.
    app_settings.save({"deepseek_key": "file-key-0000"})
    assert app_settings.api_key("deepseek") == "file-key-0000"


def test_proxy_from_settings_and_env(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    assert app_settings.proxy_for("gemini") is None
    monkeypatch.setenv("GEMINI_PROXY", "http://127.0.0.1:7901")
    assert app_settings.proxy_for("gemini") == "http://127.0.0.1:7901"
    app_settings.save({"proxy": "none"})
    assert app_settings.proxy_for("gemini") == ""
    app_settings.save({"proxy": "http://10.0.0.1:8080"})
    assert app_settings.proxy_for("gemini") == "http://10.0.0.1:8080"


def test_corrupt_file_is_ignored(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    app_settings.FILE.write_text("{не json", encoding="utf-8")
    assert app_settings.api_key("deepseek") == ""
    assert app_settings.model_for("deepseek") == "deepseek-chat"


def test_model_catalog_parsing():
    from vertcut import semantic

    openrouter = semantic._parse_models("openrouter", {"data": [
        {"id": "deepseek/deepseek-v4.1-flash-1017", "name": "DeepSeek V4.1 Flash",
         "context_length": 160000},
        {"id": "openai/gpt-4o-mini", "name": "GPT-4o mini"},
    ]})
    assert [m["id"] for m in openrouter] == ["deepseek/deepseek-v4.1-flash-1017",
                                             "openai/gpt-4o-mini"]
    assert openrouter[0]["name"] == "DeepSeek V4.1 Flash"
    gemini = semantic._parse_models("gemini", {"models": [
        {"name": "models/gemini-2.5-flash", "displayName": "Gemini 2.5 Flash",
         "supportedGenerationMethods": ["generateContent"], "inputTokenLimit": 1000000},
        {"name": "models/text-embedding-004",
         "supportedGenerationMethods": ["embedContent"]},
    ]})
    assert [m["id"] for m in gemini] == ["gemini-2.5-flash"]


def test_proxy_handlers_keep_system_by_default():
    from vertcut import semantic

    assert semantic._proxy_handlers(None) is None
    direct = semantic._proxy_handlers("")
    explicit = semantic._proxy_handlers("http://127.0.0.1:7901")
    assert len(direct) == 1 and len(explicit) == 1


def test_openrouter_profile_is_a_provider():
    from vertcut import semantic, app_settings

    assert "openrouter" in semantic.PROVIDERS
    assert semantic.PROVIDERS["openrouter"]["url"].startswith("https://openrouter.ai/")
    assert "deepseek/deepseek-chat" in app_settings.MODEL_CHOICES["openrouter"]


def test_check_key_uses_catalog(monkeypatch):
    from vertcut import semantic

    monkeypatch.setattr(semantic.app_settings, "api_key", lambda provider: "sk-test")
    monkeypatch.setattr(semantic, "models_for", lambda provider: [{"id": "m1"}, {"id": "m2"}])
    result = semantic.check_key("openrouter")
    assert result["ok"] is True
    assert result["models"] == 2


def test_whisper_model_setting(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    assert app_settings.whisper_model() == "small"
    app_settings.save({"whisper_model": "large-v3"})
    assert app_settings.whisper_model() == "large-v3"
    assert app_settings.public()["whisper_model"] == "large-v3"
    app_settings.save({"whisper_model": "turbo"})
    assert app_settings.whisper_model() == "large-v3-turbo"
    app_settings.save({"whisper_model": "gigantic"})
    assert app_settings.whisper_model() == "small"


def test_asr_terms_are_parsed_and_limited(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    app_settings.save({"asr_terms": "OpenAI, GPT-5\nOpenAI; DeepSeek"})
    assert app_settings.asr_terms_list() == ["OpenAI", "GPT-5", "DeepSeek"]
    assert app_settings.public()["asr_terms"].startswith("OpenAI")
    app_settings.save({"asr_terms": ",,,  "})
    assert app_settings.asr_terms_list() == []
    long_list = ", ".join(f"term{i}" for i in range(80))
    app_settings.save({"asr_terms": long_list})
    assert len(app_settings.asr_terms_list()) == 50

