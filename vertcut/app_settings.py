"""Общие настройки приложения: ключи API и модели для выбора моментов.

Ключи лежат в `%APPDATA%\\VertCut\\app_settings.json` и никогда не попадают
в проект, базу или репозиторий. В интерфейс отдаём только подсказку
(последние 4 символа), а не сам ключ.

Переменные окружения — запасной путь: `DEEPSEEK_API_KEY`, `GEMINI_API_KEY`
(или `GOOGLE_API_KEY`), `GEMINI_PROXY`.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from .config import DATA_DIR

FILE = DATA_DIR / "app_settings.json"
_LOCK = threading.RLock()

DEFAULT_MODELS = {
    "deepseek": "deepseek-chat",
    "gemini": "gemini-flash-latest",
    "openrouter": "deepseek/deepseek-chat",
}

MODEL_CHOICES = {
    "deepseek": ["deepseek-chat", "deepseek-reasoner"],
    "gemini": ["gemini-flash-latest", "gemini-pro-latest"],
    "openrouter": ["deepseek/deepseek-chat", "deepseek/deepseek-r1",
                   "openai/gpt-4o-mini", "anthropic/claude-3.5-sonnet"],
}

_ENV_KEYS = {
    "deepseek": ("DEEPSEEK_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "openrouter": ("OPENROUTER_API_KEY",),
}

DEFAULTS: Dict[str, Any] = {
    "deepseek_key": "",
    "gemini_key": "",
    "deepseek_model": DEFAULT_MODELS["deepseek"],
    "gemini_model": DEFAULT_MODELS["gemini"],
    "openrouter_key": "",
    "openrouter_model": DEFAULT_MODELS["openrouter"],
    "proxy": "",
}


def _read() -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    try:
        raw = FILE.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            data = parsed
    except OSError:
        pass
    except Exception:  # noqa: BLE001 — битый файл не должен ронять приложение
        pass
    merged = dict(DEFAULTS)
    for key in DEFAULTS:
        value = data.get(key)
        if isinstance(value, str):
            merged[key] = value
    return merged


def _write(data: Dict[str, Any]) -> None:
    FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    os.replace(temp, FILE)


def load() -> Dict[str, Any]:
    """Все настройки, включая ключи (только для внутреннего использования)."""
    with _LOCK:
        return _read()


def save(patch: Dict[str, Any]) -> Dict[str, Any]:
    """Сохраняет только известные поля. Пустая строка ключа не затирает его."""
    with _LOCK:
        data = _read()
        for key in ("deepseek_model", "gemini_model", "openrouter_model", "proxy"):
            value = patch.get(key)
            if isinstance(value, str):
                data[key] = value.strip()[:300]
        for key in ("deepseek_key", "gemini_key", "openrouter_key"):
            value = patch.get(key)
            if isinstance(value, str):
                value = value.strip()
                if value:
                    data[key] = value[:400]
        if patch.get("clear_deepseek_key"):
            data["deepseek_key"] = ""
        if patch.get("clear_gemini_key"):
            data["gemini_key"] = ""
        if patch.get("clear_openrouter_key"):
            data["openrouter_key"] = ""
        if not data.get("deepseek_model"):
            data["deepseek_model"] = DEFAULT_MODELS["deepseek"]
        if not data.get("gemini_model"):
            data["gemini_model"] = DEFAULT_MODELS["gemini"]
        if not data.get("openrouter_model"):
            data["openrouter_model"] = DEFAULT_MODELS["openrouter"]
        _write(data)
        return data


def _mask(value: str) -> str:
    if not value:
        return ""
    tail = value[-4:] if len(value) > 8 else ""
    return f"••••{tail}"


def public() -> Dict[str, Any]:
    """Безопасный ответ для интерфейса: ключи замаскированы."""
    with _LOCK:
        data = _read()
    return {
        "deepseek_model": data["deepseek_model"],
        "gemini_model": data["gemini_model"],
        "openrouter_model": data["openrouter_model"],
        "proxy": data["proxy"],
        "deepseek_key_set": bool(data["deepseek_key"]),
        "gemini_key_set": bool(data["gemini_key"]),
        "deepseek_key_hint": _mask(data["deepseek_key"]),
        "gemini_key_hint": _mask(data["gemini_key"]),
        "openrouter_key_set": bool(data["openrouter_key"]),
        "openrouter_key_hint": _mask(data["openrouter_key"]),
        "model_choices": MODEL_CHOICES,
    }


def api_key(provider: str) -> str:
    """Ключ из файла; если пусто — из переменных окружения."""
    with _LOCK:
        data = _read()
    value = str(data.get(f"{provider}_key") or "").strip()
    if value:
        return value
    for name in _ENV_KEYS.get(provider, ()):
        env = os.environ.get(name, "").strip()
        if env:
            return env
    return ""


def model_for(provider: str) -> str:
    return str(load().get(f"{provider}_model") or DEFAULT_MODELS.get(provider, ""))


def proxy_for(provider: str) -> str:
    """Прокси нужен в основном Gemini: из настроек, затем окружения."""
    with _LOCK:
        value = str(_read().get("proxy") or "").strip()
    if not value and provider == "gemini":
        value = (os.environ.get("GEMINI_PROXY")
                 or os.environ.get("HTTPS_PROXY")
                 or os.environ.get("HTTP_PROXY") or "").strip()
    if value.lower() in ("none", "off", "direct"):
        return ""
    return value


def has_key(provider: str) -> bool:
    return bool(api_key(provider))
