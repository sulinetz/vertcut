"""Выбор моментов нейросетью: DeepSeek или Google AI Studio (Gemini).

Оба сервиса отдают OpenAI-совместимый `/chat/completions`, поэтому клиент
один. На вход идёт **текст** расшифровки (субтитры или Whisper — разницы нет),
на выход — номера предложений, а не секунды: точность таймингов остаётся за
Whisper. Границы затем прилипают к тишине, как в обычной нарезке.

Без ключа, при ошибке сети или лимите функция возвращает ``None`` — вызывающий
код молча откатывается на эвристики `analyze.find_segments`. Ничего не падает.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import analyze, app_settings

PROMPT_VERSION = 5
REQUEST_TIMEOUT = float(os.environ.get("VERTCUT_LLM_TIMEOUT", "90"))
DEBUG = bool(os.environ.get("VERTCUT_LLM_DEBUG"))

# Метки настроения и типы контента живут в `analyze`, чтобы локальный отбор и
# нейросетевой фильтровали по одним и тем же ключам.
MOODS: Dict[str, str] = analyze.MOODS
CONTENT_TYPES: Dict[str, str] = analyze.CONTENT_TYPES

_MOOD_ALIASES = analyze.MOOD_ALIASES

_TYPE_ALIASES = {
    "история": "story", "story": "story", "storytelling": "story",
    "юмор": "humor", "humor": "humor", "humour": "humor", "comedy": "humor",
    "конфликт": "conflict", "conflict": "conflict", "controversy": "conflict",
    "инсайт": "insight", "insight": "insight", "epiphany": "insight",
    "обучение": "education", "education": "education", "educational": "education",
    "tutorial": "education",
    "реакция": "reaction", "reaction": "reaction",
    "мотивация": "motivation", "motivation": "motivation", "motivational": "motivation",
    "провокация": "provocation", "provocation": "provocation", "challenge": "provocation",
    "эмоциональный момент": "emotion", "эмоция": "emotion", "emotion": "emotion",
    "emotional": "emotion",
    "интересный факт": "fact", "факт": "fact", "fact": "fact", "trivia": "fact",
}


PROVIDERS: Dict[str, Dict[str, Any]] = {
    "deepseek": {
        "url": "https://api.deepseek.com/chat/completions",
        "label": "DeepSeek",
        # ~128k токенов. Берём с запасом на промпт и ответ.
        "budget_chars": 260_000,
    },
    "gemini": {
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "label": "Gemini",
        "budget_chars": 1_200_000,
        "models_url": "https://generativelanguage.googleapis.com/v1beta/models",
    },
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "label": "OpenRouter (DeepSeek)",
        "budget_chars": 120_000,
        "models_url": "https://openrouter.ai/api/v1/models",
    },
    "polza": {
        "url": "https://polza.ai/api/v1/chat/completions",
        "label": "Polza.ai",
        "budget_chars": 120_000,
        "models_url": "https://polza.ai/api/v1/models",
    },
}

PICKERS = ("local", "auto", "openrouter", "polza", "deepseek", "gemini")

SYSTEM_PROMPT = """Ты — редактор вирусных вертикальных видео (Shorts, TikTok, Reels).
Тебе дают расшифровку речи с номерами предложений и таймкодами.
Найди моменты, которые залетят: сильный хук, конфликт или интрига, конкретика,
эмоция и законченная развязка.

Правила:
- Границы — только по номерам предложений. Начало понятно без предыдущего текста.
- Не обрывай шутку, историю или мысль на середине: конец — развязка или панчлайн.
- Не бери рекламу, приветствия, прощания, воду и служебные фразы.
- Длительность держи в указанном диапазоне.
- Моменты не должны пересекаться.
- mood — точное настроение момента своими словами (1–2 слова в нижнем регистре на языке видео:
  например весёлое, грустное, драма, шок, мысль, хорни, флирт, кринж, сарказм, азарт, саспенс,
  уютное, жёсткое — передавай реальную эмоцию момента после расшифровки, не ограничивайся шаблонами).
- types — от одного до трёх типов содержания строго из списка: story, humor, conflict, insight,
  education, reaction, motivation, provocation, emotion, fact. Тип отвечает на вопрос «что это»,
  настроение — «какая эмоция».
- tag — один главный короткий тег темы момента (1–2 слова в нижнем регистре на языке видео;
  NSFW и 18+ теги полностью поддерживаются и одобряются — называй суть прямо без цензуры,
  например: хентай, бдсм, минет, доминирование, флирт, отношения, конфликт, игры, деньги).
- score 0..1 — насколько момент залетит. Оценивай по абсолютной шкале, а не «лучшее в этом куске»:
  0.9 — переслал бы другу, 0.7 — сильный момент, 0.5 — нормально, 0.2 — проходное.
- title — короткий цепляющий заголовок на языке речи, до 70 символов.
- why — одна фраза, почему момент сильный.

Верни ТОЛЬКО JSON без пояснений:
{"clips":[{"from":12,"to":17,"score":0.82,"mood":"funny","types":["humor","story"],
"tag":"отношения","title":"...","why":"...",
"hook":0.9,"conflict":0.5,"specificity":0.6,"emotion":0.8,"payoff":0.7}]}
"""


class LLMError(Exception):
    """Ошибка запроса: статус и человеко-понятное сообщение."""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


# Финальное сравнение: короткие тексты кандидатов, без повторной отправки
# транскрипта. 24 — компромисс между качеством рейтинга и ценой запроса.
CALIBRATE_LIMIT = 24
CALIBRATE_SYSTEM_PROMPT = """Ты — редактор вирусных вертикальных видео.
Тебе дают кандидатов из разных частей одного видео. Оценки между частями
несопоставимы, потому что их выставляли отдельные запросы.

Сравни кандидатов между собой по смыслу и верни итоговый рейтинг:
содержательность, интересное начало, эмоция, самостоятельность мысли,
понятность без исходного видео, завершённость, пригодность для короткого формата.

Правила:
- Не добавляй новых кандидатов и не меняй id.
- score 0..1 по одной общей шкале: 0.9 — переслал бы другу, 0.7 — сильный,
  0.5 — нормально, 0.2 — проходное.
- Верни ТОЛЬКО JSON: {"clips":[{"id":0,"score":0.8}]}
"""


def _http_message(status: int, body: str) -> str:
    tail = (body or "").strip()[:300]
    hints = {
        400: "Запрос отклонён. Проверьте название модели.",
        401: "Ключ неверный или отозван.",
        402: "На аккаунте закончились средства.",
        403: "Ключ не имеет доступа к модели или запрос заблокирован по IP (нужен прокси).",
        404: "Модель не найдена. Проверьте название.",
        413: "Слишком большой запрос: текст не влез в контекст модели.",
        429: "Превышен лимит запросов. Подождите или смените провайдера.",
        500: "Ошибка на стороне сервиса. Попробуйте позже.",
        502: "Сервис недоступен. Попробуйте позже.",
        503: "Сервис перегружен. Попробуйте позже.",
    }
    hint = hints.get(status, "Запрос не удался.")
    return hint + (f" [{status}] {tail}" if tail else f" [{status}]")


def _proxy_handlers(proxy: Optional[str]):
    """None — системный прокси, "" — напрямую, строка — явный адрес."""
    if proxy is None:
        return None
    if proxy == "":
        return [urllib.request.ProxyHandler({})]
    return [urllib.request.ProxyHandler({"http": proxy, "https": proxy})]


def _post_json(url: str, payload: Dict[str, Any], key: str,
               proxy: Optional[str] = None, timeout: float = REQUEST_TIMEOUT) -> Dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    # Пустой ProxyHandler отключает системные прокси: DeepSeek обычно доступен
    # напрямую, а глобальный HTTPS_PROXY может всё сломать.
    handlers = _proxy_handlers(proxy)
    opener = urllib.request.build_opener(*handlers) if handlers is not None \
        else urllib.request.build_opener()
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            pass
        raise LLMError(_http_message(exc.code, body), exc.code) from exc
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"Сеть недоступна: {str(exc)[:200]}") from exc
    try:
        parsed = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        raise LLMError("Сервис вернул не JSON") from exc
    if not isinstance(parsed, dict):
        raise LLMError("Сервис вернул неожиданный ответ")
    return parsed


_MODELS_CACHE: Dict[str, tuple] = {}
MODELS_CACHE_SECONDS = 6 * 3600


def _get_json(url: str, key: str = "", proxy: Optional[str] = None,
              timeout: float = 30.0) -> Dict[str, Any]:
    headers = {"Accept": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    request = urllib.request.Request(url, headers=headers)
    handlers = _proxy_handlers(proxy)
    opener = urllib.request.build_opener(*handlers) if handlers is not None \
        else urllib.request.build_opener()
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            pass
        raise LLMError(_http_message(exc.code, body), exc.code) from exc
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"Нет связи с провайдером: {str(exc)[:200]}") from exc
    try:
        parsed = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        raise LLMError("Провайдер вернул не JSON") from exc
    if not isinstance(parsed, dict):
        raise LLMError("Провайдер вернул неожиданный ответ")
    return parsed


def _parse_models(provider: str, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if provider in ("openrouter", "polza"):
        for item in payload.get("data") or []:
            mid = str(item.get("id") or "").strip()
            if mid:
                out.append({"id": mid, "name": str(item.get("name") or mid),
                            "context": int(item.get("context_length") or 0)})
    elif provider == "gemini":
        for item in payload.get("models") or []:
            methods = item.get("supportedGenerationMethods") or []
            if methods and "generateContent" not in methods:
                continue
            name = str(item.get("name") or "")
            mid = name.split("/", 1)[1] if name.startswith("models/") else name
            if mid:
                out.append({"id": mid, "name": str(item.get("displayName") or mid),
                            "context": int(item.get("inputTokenLimit") or 0)})
    else:
        for item in payload.get("data") or []:
            mid = str(item.get("id") or "").strip()
            if mid:
                out.append({"id": mid, "name": str(item.get("owned_by") or mid),
                            "context": 0})
    out.sort(key=lambda m: m["id"])
    return out


def models_for(provider: str) -> List[Dict[str, Any]]:
    """Каталог моделей с кешем; OpenRouter и Polza.ai — без ключа."""
    spec = PROVIDERS.get(provider)
    if not spec:
        raise LLMError("Неизвестный провайдер")
    cached = _MODELS_CACHE.get(provider)
    if cached and time.time() - cached[0] < MODELS_CACHE_SECONDS:
        return list(cached[1])
    key = app_settings.api_key(provider)
    if provider not in ("openrouter", "polza") and not key:
        raise LLMError("Сначала задайте ключ")
    if provider == "gemini":
        url = f"{spec['models_url']}?key={urllib.parse.quote(key)}"
        payload = _get_json(url, proxy=app_settings.proxy_for(provider))
    else:
        payload = _get_json(spec["models_url"], key=key,
                            proxy=app_settings.proxy_for(provider))
    models = _parse_models(provider, payload)
    if not models:
        raise LLMError("Провайдер не вернул моделей")
    _MODELS_CACHE[provider] = (time.time(), models)
    return list(models)


def _chat(provider: str, messages: List[Dict[str, str]],
          max_tokens: int = 4000, json_mode: bool = True) -> Tuple[str, Dict[str, Any]]:
    spec = PROVIDERS.get(provider)
    if not spec:
        raise LLMError("Неизвестный провайдер")
    key = app_settings.api_key(provider)
    if not key:
        raise LLMError("Ключ не задан", 401)
    model = app_settings.model_for(provider)
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    proxy = app_settings.proxy_for(provider)
    try:
        result = _post_json(spec["url"], payload, key, proxy)
    except LLMError as exc:
        # Не все OpenAI-совместимые шлюзы знают response_format.
        if exc.status == 400 and "response_format" in payload:
            payload.pop("response_format", None)
            result = _post_json(spec["url"], payload, key, proxy)
        else:
            raise
    try:
        content = result["choices"][0]["message"]["content"]
    except Exception as exc:  # noqa: BLE001
        raise LLMError("В ответе нет текста") from exc
    if isinstance(content, list):
        content = "".join(str(part.get("text") or "") if isinstance(part, dict) else str(part)
                          for part in content)
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    return str(content or ""), usage


def _extract_json(text: str) -> Any:
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        pass
    start = min((i for i in (raw.find("{"), raw.find("[")) if i >= 0), default=-1)
    end = max(raw.rfind("}"), raw.rfind("]"))
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except Exception:  # noqa: BLE001
            pass
    raise LLMError("Не удалось разобрать JSON в ответе модели")


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, result))


def _maybe_float(value: Any) -> float:
    """Оценка подкритерия: -1 означает «модель не прислала»."""
    if value is None:
        return -1.0
    try:
        result = float(value)
    except (TypeError, ValueError):
        return -1.0
    return max(0.0, min(1.0, result))


def _clean_mood(value: Any) -> str:
    return analyze.normalize_mood(value)


_TAG_STOP = {"none", "null", "n/a", "na", "unknown", "undefined", "tag", "тег", "-", "—", "нет"}


def _clean_tag(value: Any) -> str:
    """Нормализует основной тег клипа (без цензуры, включая NSFW-теги)."""
    text = re.sub(r"[\"'`()\[\]{}<>]+", "", str(value or ""))
    text = re.sub(r"^#+", "", text.strip())
    text = re.sub(r"\s+", " ", text).strip(" ,.;:!?-_").lower()
    if not text or text in _TAG_STOP:
        return ""
    return text[:40].strip()


def _clean_types(value: Any, limit: int = 3) -> List[str]:
    """До `limit` валидных типов контента. Мусор от модели отбрасывается."""
    if isinstance(value, str):
        raw = re.split(r"[,;/|\s]+", value)
    elif isinstance(value, (list, tuple)):
        raw = list(value)
    else:
        raw = []
    out: List[str] = []
    for item in raw:
        key = str(item or "").strip().lower()
        key = key if key in CONTENT_TYPES else _TYPE_ALIASES.get(key, "")
        if key and key not in out:
            out.append(key)
        if len(out) >= limit:
            break
    return out


def _clean_items(payload: Any, total: int, limit: int,
                 allowed: Optional[set] = None) -> List[Dict[str, Any]]:
    """Проверка ответа модели: индексы в пределах, from <= to, score 0..1.

    `allowed` — номера предложений, которые реально были в запросе. Модель не
    должна возвращать индексы из соседних частей: такие ответы отбрасываем.
    """
    data = payload.get("clips") if isinstance(payload, dict) else payload
    if not isinstance(data, list):
        return []
    cleaned: List[Dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            start = int(item.get("from"))
            end = int(item.get("to"))
        except (TypeError, ValueError):
            continue
        if start < 0 or end < start or end >= total:
            continue
        if allowed is not None and (start not in allowed or end not in allowed):
            continue
        if limit and len(cleaned) >= limit:
            break
        cleaned.append({
            "from": start,
            "to": end,
            "score": _as_float(item.get("score")),
            "mood": _clean_mood(item.get("mood")),
            "types": _clean_types(item.get("types") or item.get("content_types")),
            "tag": _clean_tag(item.get("tag") or item.get("main_tag")),
            "title": re.sub(r"\s+", " ", str(item.get("title") or "")).strip()[:90],
            "why": re.sub(r"\s+", " ", str(item.get("why") or "")).strip()[:280],
            "hook": _maybe_float(item.get("hook")),
            "conflict": _maybe_float(item.get("conflict")),
            "specificity": _maybe_float(item.get("specificity")),
            "emotion": _maybe_float(item.get("emotion")),
            "payoff": _maybe_float(item.get("payoff")),
        })
    return cleaned


def _chunks(sents: List[Dict[str, Any]], budget: int) -> List[List[int]]:
    """Делит предложения на окна по бюджету символов с перекрытием в 3 фразы."""
    indexes = list(range(len(sents)))
    chunks: List[List[int]] = []
    current: List[int] = []
    size = 0
    for index in indexes:
        line = len(sents[index]["text"]) + 16
        if current and size + line > budget:
            chunks.append(current)
            # перекрытие: модель видит, чем закончилась предыдущая часть
            current = current[-3:]
            size = sum(len(sents[i]["text"]) + 16 for i in current)
        current.append(index)
        size += line
    if current:
        chunks.append(current)
    return chunks


def _prompt(sents: List[Dict[str, Any]], indexes: List[int], duration: float,
            opts: Dict[str, Any]) -> str:
    count = int(opts.get("count") or 0) or 12
    want = max(3, min(40, count * 2))
    lines = []
    for i in indexes:
        sent = sents[i]
        lines.append(f"[{i}] {_stamp(sent['start'])} {sent['text']}")
    moods = [analyze.normalize_mood(m) for m in (opts.get("mood_filter") or []) if analyze.normalize_mood(m)]
    mood_hint = ""
    if moods:
        mood_hint = "\nНужны только эти настроения: " + ", ".join(moods) + "."
    types = [t for t in (opts.get("type_filter") or []) if t in CONTENT_TYPES]
    type_hint = ""
    if types:
        type_hint = "\nНужны только эти типы содержания: " + ", ".join(types) + "."
    return (
        f"Видео длится {_stamp(duration)}. Клипы СТРОГО от {opts.get('min_dur')} до "
        f"{opts.get('max_dur')} секунд, цель — около {opts.get('target_dur')} секунд "
        f"(объединяй соседние реплики одной сцены до нужной длительности).\n"
        f"Верни не больше {want} лучших моментов.{mood_hint}{type_hint}\n\n"
        + "\n".join(lines)
    )


def _stamp(seconds: float) -> str:
    total = max(0, int(seconds or 0))
    return f"{total // 3600:02d}:{(total % 3600) // 60:02d}:{total % 60:02d}"


def _cache_path(workdir: Optional[Path]) -> Optional[Path]:
    return Path(workdir) / "semantic_cache.json" if workdir else None


def _cache_key(provider: str, sents: List[Dict[str, Any]], duration: float,
               opts: Dict[str, Any]) -> str:
    digest = hashlib.sha256()
    digest.update(f"v{PROMPT_VERSION}|{provider}|{app_settings.model_for(provider)}".encode())
    digest.update(f"|{round(duration)}|{opts.get('count')}|{opts.get('min_dur')}"
                  f"|{opts.get('max_dur')}|{opts.get('target_dur')}".encode())
    digest.update(("|" + ",".join(sorted(opts.get("mood_filter") or []))).encode())
    digest.update(("|t:" + ",".join(sorted(opts.get("type_filter") or []))).encode())
    for sent in sents:
        digest.update(f"|{round(float(sent['start']), 2)}|{sent['text']}".encode("utf-8"))
    return digest.hexdigest()


def _cache_read(path: Optional[Path], key: str) -> Optional[List[Dict[str, Any]]]:
    if not path or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        items = (data.get(key) or {}).get("items")
        return items if isinstance(items, list) else None
    except Exception:  # noqa: BLE001
        return None


def _cache_write(path: Optional[Path], key: str, provider: str,
                 items: List[Dict[str, Any]]) -> None:
    if not path:
        return
    try:
        data: Dict[str, Any] = {}
        if path.exists():
            parsed = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                data = parsed
        data[key] = {"provider": provider, "items": items}
        if len(data) > 24:
            for old in list(data)[:-24]:
                data.pop(old, None)
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, path)
    except Exception:  # noqa: BLE001
        pass


def _ask(provider: str, sents: List[Dict[str, Any]], duration: float,
         opts: Dict[str, Any], workdir: Optional[Path]) -> List[Dict[str, Any]]:
    key = _cache_key(provider, sents, duration, opts)
    cached = _cache_read(_cache_path(workdir), key)
    if cached is not None:
        return cached
    budget = int(PROVIDERS[provider]["budget_chars"])
    items: List[Dict[str, Any]] = []
    seen = set()
    for indexes in _chunks(sents, budget):
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _prompt(sents, indexes, duration, opts)},
        ]
        content, _usage = _chat(provider, messages)
        allowed = set(indexes)
        for item in _clean_items(_extract_json(content), len(sents),
                                 limit=60, allowed=allowed):
            signature = (item["from"], item["to"])
            if signature in seen:
                continue
            seen.add(signature)
            items.append(item)
    if items:
        _cache_write(_cache_path(workdir), key, provider, items)
    return items


def _calibrate_prompt(sents: List[Dict[str, Any]], items: List[Dict[str, Any]],
                      duration: float) -> str:
    blocks: List[str] = []
    for rank, item in enumerate(items):
        window = sents[item["from"]:item["to"] + 1]
        text = " ".join(sent["text"] for sent in window)
        if len(text) > 300:
            text = text[:300].rstrip() + "…"
        mood = item.get("mood") or "-"
        types = ",".join(item.get("types") or []) or "-"
        blocks.append(
            f"#{rank} [{_stamp(sents[item['from']]['start'])}] "
            f"score={float(item.get('score') or 0):.2f} mood={mood} types={types}\n{text}")
    return (
        f"Видео длится {_stamp(duration)}.\n"
        f"Кандидатов: {len(items)}. Верни рейтинг для всех.\n\n"
        + "\n\n".join(blocks)
    )


def _clean_ranking(payload: Any, size: int) -> List[Dict[str, Any]]:
    """Разбор ответа финального сравнения: id из shortlist и новые score."""
    data = payload.get("clips") if isinstance(payload, dict) else payload
    if isinstance(data, dict):
        data = data.get("ranking")
    if not isinstance(data, list):
        return []
    out: List[Dict[str, Any]] = []
    seen = set()
    for item in data:
        if isinstance(item, int):
            index, raw_score = item, None
        elif isinstance(item, dict):
            try:
                index = int(item.get("id", item.get("index")))
            except (TypeError, ValueError):
                continue
            raw_score = item.get("score")
        else:
            continue
        if index < 0 or index >= size or index in seen:
            continue
        seen.add(index)
        score = _maybe_float(raw_score) if raw_score is not None else -1.0
        out.append({"id": index, "score": score})
    return out


def _calibrate(provider: str, sents: List[Dict[str, Any]],
               items: List[Dict[str, Any]], duration: float,
               opts: Dict[str, Any], workdir: Optional[Path]) -> List[Dict[str, Any]]:
    """Общий рейтинг кандидатов одним запросом.

    Оценки из разных чанков несопоставимы. Сравниваем только shortlist из
    коротких текстов и метаданных. Любая ошибка — возвращаем исходный порядок:
    клипы терять нельзя.
    """
    if len(items) < 3:
        return items
    shortlist = sorted(items, key=lambda item: float(item.get("score") or 0),
                       reverse=True)[:CALIBRATE_LIMIT]
    digest = hashlib.sha256()
    digest.update(f"cal|v{PROMPT_VERSION}|{provider}"
                  f"|{app_settings.model_for(provider)}".encode())
    for item in shortlist:
        digest.update(f"|{item['from']}-{item['to']}-{float(item.get('score') or 0):.3f}".encode())
        digest.update(("|" + ",".join(item.get("types") or [])).encode())
    key = digest.hexdigest()
    path = _cache_path(workdir)
    ranking = _cache_read(path, key)
    if ranking is None:
        ranking = []
        try:
            content, _usage = _chat(provider, [
                {"role": "system", "content": CALIBRATE_SYSTEM_PROMPT},
                {"role": "user", "content": _calibrate_prompt(sents, shortlist, duration)},
            ])
            ranking = _clean_ranking(_extract_json(content), len(shortlist))
        except LLMError as exc:
            if DEBUG:
                print(f"[semantic] {provider}: сравнение не удалось: {exc}")
            ranking = []
        except Exception as exc:  # noqa: BLE001
            if DEBUG:
                print(f"[semantic] {provider}: сравнение: неожиданная ошибка: {exc}")
            ranking = []
        if ranking:
            _cache_write(path, key, provider, ranking)
    scores = {row["id"]: row["score"] for row in (ranking or [])
              if row.get("score") is not None and float(row["score"]) >= 0}
    if not scores:
        return items
    calibrated: List[Dict[str, Any]] = []
    for rank, item in enumerate(shortlist):
        copy = dict(item)
        if rank in scores:
            copy["score"] = round(float(scores[rank]), 4)
        calibrated.append(copy)
    short_ids = {id(item) for item in shortlist}
    floor = min(scores.values())
    for item in items:
        if id(item) in short_ids:
            continue
        copy = dict(item)
        copy["score"] = min(float(copy.get("score") or 0.0), floor)
        calibrated.append(copy)
    return calibrated


def _fit_window(sents: List[Dict[str, Any]], start_i: int, end_i: int,
                min_dur: float, max_dur: float) -> Tuple[int, int]:
    """Подгоняет границы окна от нейросети под выбранный диапазон [min_dur, max_dur]."""
    start_i, end_i = analyze._extend_window(sents, start_i, end_i, max_dur)
    while end_i > start_i and sents[end_i]["end"] - sents[start_i]["start"] > max_dur:
        end_i -= 1
    while sents[end_i]["end"] - sents[start_i]["start"] < min_dur:
        if end_i + 1 < len(sents) and sents[end_i + 1]["end"] - sents[start_i]["start"] <= max_dur:
            end_i += 1
        elif start_i > 0 and sents[end_i]["end"] - sents[start_i - 1]["start"] <= max_dur:
            start_i -= 1
        else:
            break
    return start_i, end_i


def _to_candidates(items: List[Dict[str, Any]], sents: List[Dict[str, Any]],
                   duration: float, opts: Dict[str, Any], curve: List[float],
                   mean_db: float, hop: float, energy_offset: float,
                   provider: str) -> List[Dict[str, Any]]:
    max_dur = float(opts.get("max_dur") or 60)
    min_dur = float(opts.get("min_dur") or 15)
    min_score = float(opts.get("min_score") or 0.0)
    moods = [analyze.normalize_mood(m) for m in (opts.get("mood_filter") or []) if analyze.normalize_mood(m)]
    types_wanted = [t for t in (opts.get("type_filter") or []) if t in CONTENT_TYPES]
    total_speech = (sents[-1]["end"] - sents[0]["start"]) if sents else 0.0
    eff_min = min_dur if (duration > min_dur * 1.15 and total_speech >= min_dur) else 3.0

    candidates: List[Dict[str, Any]] = []
    for item in items:
        if item.get("score", 0.0) < min_score:
            continue
        if moods and not analyze.mood_matches(item.get("mood"), moods):
            continue
        if types_wanted and not set(types_wanted) & set(item.get("types") or []):
            continue
        start_i, end_i = _fit_window(sents, item["from"], item["to"], min_dur, max_dur)
        start = sents[start_i]["start"]
        end = sents[end_i]["end"]
        if end - start > max_dur or end - start < max(3.0, eff_min):
            continue
        window = sents[start_i:end_i + 1]
        title = item.get("title") or analyze._make_title(window)
        text = " ".join(sent["text"] for sent in window)
        parts = {
            "hook": item.get("hook"), "retention": item.get("conflict"),
            "emotion": item.get("emotion"), "specificity": item.get("specificity"),
            "completeness": item.get("payoff"), "source": provider,
        }
        parts = {key: round(value, 3) for key, value in parts.items()
                 if isinstance(value, (int, float)) and value >= 0}
        candidates.append({
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": round(end - start, 2),
            "score": round(float(item["score"]), 4),
            "parts": parts,
            "text": text,
            "words": [word for sent in window for word in sent["words"]],
            "title": title,
            "hook": title,
            "mood": item.get("mood") or "",
            "why": item.get("why") or "",
            "tag": item.get("tag") or "",
            "content_types": list(item.get("types") or []),
            "source": provider,
        })

    if not candidates:
        return []

    # Дедупликация: пересечения, почти одинаковый текст, повторы.
    candidates.sort(key=lambda item: item["score"], reverse=True)
    picked: List[Dict[str, Any]] = []
    for cand in candidates:
        duplicate = False
        for prev in picked:
            overlap = min(prev["end"], cand["end"]) - max(prev["start"], cand["start"])
            if overlap > 0:
                shorter = min(prev["end"] - prev["start"], cand["end"] - cand["start"])
                if shorter > 0 and overlap / shorter > 0.18:
                    duplicate = True
                    break
            if analyze._text_similar(cand["text"], prev["text"]):
                duplicate = True
                break
        if not duplicate:
            picked.append(cand)

    limit = int(opts.get("count") or 0)
    picked = picked[:limit] if limit > 0 else picked

    out: List[Dict[str, Any]] = []
    for cand in picked:
        start = max(0.0, analyze._nearest_quiet(
            curve, mean_db, cand["start"] - 0.10, hop, window=0.30, offset=energy_offset))
        end = min(duration, analyze._nearest_quiet(
            curve, mean_db, cand["end"] + 0.18, hop, offset=energy_offset))
        words = [word for word in cand["words"]
                 if word["end"] > start + 0.05 and word["start"] < end - 0.05]
        if end - start < 3.0:
            continue
        clip_text = " ".join(word["word"] for word in words)
        keywords = analyze._keywords(clip_text, 6)
        primary_tag = cand.get("tag") or (keywords[0] if keywords else cand.get("mood") or "")
        caption = analyze._make_caption(
            cand["title"], clip_text, str(opts.get("platform") or "shorts"))
        hash_tag = re.sub(r"[^\w]", "", primary_tag.replace(" ", "_"))
        if hash_tag and f"#{hash_tag}" not in caption.lower():
            head, sep, tail = caption.partition("\n\n")
            caption = f"{head}\n\n#{hash_tag} {tail}".strip() if sep else f"{caption}\n\n#{hash_tag}"
        out.append({
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": round(end - start, 2),
            "score": cand["score"],
            "parts": cand["parts"],
            "title": cand["title"],
            "hook": cand["hook"],
            "caption": caption,
            "keywords": keywords,
            "words": words,
            "mood": cand["mood"],
            "why": cand["why"],
            "tag": primary_tag,
            "content_types": list(cand.get("content_types") or []),
            "source": cand["source"],
        })
    return out


def find_segments(segments: List[Dict[str, Any]], media: Path, duration: float,
                  opts: Optional[Dict[str, Any]] = None,
                  workdir: Optional[Path] = None,
                  wav: Optional[Path] = None,
                  energy_offset: float = 0.0) -> Optional[List[Dict[str, Any]]]:
    """Моменты от нейросети или ``None`` — тогда нужен откат на эвристики."""
    opts = opts or {}
    picker = str(opts.get("picker") or "local")
    if picker == "local":
        return None
    chain = ["openrouter", "polza", "deepseek", "gemini"] if picker == "auto" else [picker]
    sents = analyze.build_sentences(segments)
    if len(sents) < 4 or duration < 5:
        return None

    curve, mean_db = analyze.energy_curve(media, wav=wav)
    hop = 0.25
    for provider in chain:
        if provider not in PROVIDERS or not app_settings.api_key(provider):
            continue
        try:
            items = _ask(provider, sents, duration, opts, workdir)
        except LLMError as exc:
            if DEBUG:
                print(f"[semantic] {provider}: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001
            if DEBUG:
                print(f"[semantic] {provider}: неожиданная ошибка: {exc}")
            continue
        if not items:
            continue
        items = _calibrate(provider, sents, items, duration, opts, workdir)
        found = _to_candidates(items, sents, duration, opts, curve, mean_db,
                               hop, energy_offset, provider)
        if found:
            return found
    return None


def check_key(provider: str) -> Dict[str, Any]:
    """Дешёвая проверка ключа: один короткий запрос."""
    if provider not in PROVIDERS:
        return {"ok": False, "message": "Неизвестный провайдер"}
    if not app_settings.api_key(provider):
        return {"ok": False, "message": "Ключ не задан"}
    try:
        models = models_for(provider)
    except LLMError as exc:
        return {"ok": False, "status": exc.status, "message": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": str(exc)[:300]}
    return {
        "ok": True,
        "model": app_settings.model_for(provider),
        "models": len(models),
        "message": f"Ключ работает. Доступно моделей: {len(models)}",
    }