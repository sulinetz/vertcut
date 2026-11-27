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
import re
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
    "polza": "deepseek/deepseek-chat",
}

WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"]

# Пользователь может написать «turbo» — это тот же large-v3-turbo.
WHISPER_ALIASES = {"turbo": "large-v3-turbo", "large": "large-v3",
                   "large-turbo": "large-v3-turbo"}


def normalize_whisper_model(value: Any) -> str:
    """Имя модели в каноническом виде; пусто — неизвестное значение."""
    text = str(value or "").strip().lower()
    text = WHISPER_ALIASES.get(text, text)
    return text if text in WHISPER_MODELS else ""

MODEL_CHOICES = {
    "deepseek": ["deepseek-chat", "deepseek-reasoner"],
    "gemini": ["gemini-flash-latest", "gemini-pro-latest"],
    "openrouter": ["deepseek/deepseek-chat", "deepseek/deepseek-r1",
                   "openai/gpt-4o-mini", "anthropic/claude-3.5-sonnet"],
    "polza": ["deepseek/deepseek-chat", "google/gemini-2.5-flash",
              "openai/gpt-4o-mini", "deepseek/deepseek-v3.2"],
}

_ENV_KEYS = {
    "deepseek": ("DEEPSEEK_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "openrouter": ("OPENROUTER_API_KEY",),
    "polza": ("POLZA_API_KEY", "POLZA_AI_API_KEY"),
}

_PROVIDERS = tuple(DEFAULT_MODELS)

DEFAULTS: Dict[str, Any] = {
    "deepseek_key": "",
    "gemini_key": "",
    "deepseek_model": DEFAULT_MODELS["deepseek"],
    "gemini_model": DEFAULT_MODELS["gemini"],
    "openrouter_key": "",
    "openrouter_model": DEFAULT_MODELS["openrouter"],
    "polza_key": "",
    "polza_model": DEFAULT_MODELS["polza"],
    "whisper_model": "small",
    "asr_terms": "",
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
        model_keys = tuple(f"{p}_model" for p in _PROVIDERS)
        for key in (*model_keys, "whisper_model", "asr_terms", "proxy"):
            value = patch.get(key)
            if isinstance(value, str):
                data[key] = value.strip()[:2000 if key == "asr_terms" else 300]
        for prov in _PROVIDERS:
            value = patch.get(f"{prov}_key")
            if isinstance(value, str):
                value = value.strip()
                if value:
                    data[f"{prov}_key"] = value[:400]
            if patch.get(f"clear_{prov}_key"):
                data[f"{prov}_key"] = ""
            if not data.get(f"{prov}_model"):
                data[f"{prov}_model"] = DEFAULT_MODELS[prov]
        data["whisper_model"] = normalize_whisper_model(data.get("whisper_model")) or "small"
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
    out: Dict[str, Any] = {
        "proxy": data["proxy"],
        "model_choices": MODEL_CHOICES,
        "whisper_model": data["whisper_model"],
        "whisper_models": WHISPER_MODELS,
        "asr_terms": data["asr_terms"],
    }
    for prov in _PROVIDERS:
        key_val = data.get(f"{prov}_key") or ""
        out[f"{prov}_model"] = data.get(f"{prov}_model") or DEFAULT_MODELS[prov]
        out[f"{prov}_key_set"] = bool(key_val)
        out[f"{prov}_key_hint"] = _mask(key_val)
    return out


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


def whisper_model() -> str:
    value = normalize_whisper_model(load().get("whisper_model"))
    return value or "small"


def asr_terms() -> str:
    return str(load().get("asr_terms") or "")


def asr_terms_list(limit: int = 50) -> list:
    """Словарь имён и терминов: строки через запятую, точку с запятой или перенос."""
    raw = asr_terms()
    parts = re.split(r"[,;\n\r]+", raw)
    out = []
    seen = set()
    for item in parts:
        term = re.sub(r"\s+", " ", item).strip()
        if not term:
            continue
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(term[:40])
        if len(out) >= max(1, int(limit)):
            break
    return out


def model_for(provider: str) -> str:
    return str(load().get(f"{provider}_model") or DEFAULT_MODELS.get(provider, ""))


def proxy_for(provider: str) -> Optional[str]:
    """Прокси для запросов к провайдеру.

    None — системный прокси (Windows/переменные окружения), "" — напрямую,
    строка — явный адрес. Старое значение none/off/direct означает «напрямую».
    """
    with _LOCK:
        value = str(_read().get("proxy") or "").strip()
    if not value:
        if provider == "gemini":
            env = (os.environ.get("GEMINI_PROXY")
                   or os.environ.get("HTTPS_PROXY")
                   or os.environ.get("HTTP_PROXY") or "").strip()
            if env:
                value = env
            else:
                return None
        else:
            return None
    if value.lower() in ("none", "off", "direct", "directly"):
        return ""
    return value


def has_key(provider: str) -> bool:
    return bool(api_key(provider))
