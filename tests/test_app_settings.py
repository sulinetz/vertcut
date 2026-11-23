"""Ключи API: хранение, маскирование и запасной путь через окружение."""
from __future__ import annotations

from vertcut import app_settings


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(app_settings, "FILE", tmp_path / "app_settings.json")
    for name in ("DEEPSEEK_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
                 "GEMINI_PROXY", "HTTPS_PROXY", "HTTP_PROXY"):
        monkeypatch.delenv(name, raising=False)


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
    assert app_settings.proxy_for("gemini") == ""
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
