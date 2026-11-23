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
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import analyze, app_settings

PROMPT_VERSION = 1
REQUEST_TIMEOUT = float(os.environ.get("VERTCUT_LLM_TIMEOUT", "90"))
DEBUG = bool(os.environ.get("VERTCUT_LLM_DEBUG"))

# Метки настроения. Ключи английские — так стабильнее в JSON и в фильтре.
MOODS: Dict[str, str] = {
    "funny": "весёлое",
    "sad": "грустное",
    "drama": "драма",
    "shock": "шок",
    "insight": "мысль",
    "wholesome": "тёплое",
    "intense": "жёсткое",
}

_MOOD_ALIASES = {
    "веселое": "funny", "весёлое": "funny", "смешное": "funny", "fun": "funny",
    "humor": "funny", "comedy": "funny",
    "грустное": "sad", "печальное": "sad", "sadness": "sad", "emotional": "sad",
    "драма": "drama", "dramatic": "drama", "conflict": "drama",
    "шок": "shock", "shocking": "shock", "surprise": "shock", "wow": "shock",
    "мысль": "insight", "insightful": "insight", "wise": "insight",
    "полезное": "insight", "educational": "insight",
    "теплое": "wholesome", "тёплое": "wholesome", "kind": "wholesome",
    "жёсткое": "intense", "жесткое": "intense", "brutal": "intense",
    "aggressive": "intense",
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
    },
}

PICKERS = ("local", "auto", "deepseek", "gemini")

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
- mood — одно слово строго из списка: funny, sad, drama, shock, insight, wholesome, intense.
- score 0..1 — насколько момент залетит. Оценивай по смыслу, а не по словарю.
- title — короткий цепляющий заголовок на языке речи, до 70 символов.
- why — одна фраза, почему момент сильный.

Верни ТОЛЬКО JSON без пояснений:
{"clips":[{"from":12,"to":17,"score":0.82,"mood":"funny","title":"...","why":"...",
"hook":0.9,"conflict":0.5,"specificity":0.6,"emotion":0.8,"payoff":0.7}]}
"""


class LLMError(Exception):
    """Ошибка запроса: статус и человеко-понятное сообщение."""

    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


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


def _post_json(url: str, payload: Dict[str, Any], key: str,
               proxy: str = "", timeout: float = REQUEST_TIMEOUT) -> Dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    # Пустой ProxyHandler отключает системные прокси: DeepSeek обычно доступен
    # напрямую, а глобальный HTTPS_PROXY может всё сломать.
    handlers = [urllib.request.ProxyHandler({"http": proxy, "https": proxy})] if proxy \
        else [urllib.request.ProxyHandler({})]
    opener = urllib.request.build_opener(*handlers)
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
    mood = str(value or "").strip().lower()
    if mood in MOODS:
        return mood
    return _MOOD_ALIASES.get(mood, "")


def _clean_items(payload: Any, total: int, limit: int) -> List[Dict[str, Any]]:
    """Проверка ответа модели: индексы в пределах, from <= to, score 0..1."""
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
        if limit and len(cleaned) >= limit:
            break
        cleaned.append({
            "from": start,
            "to": end,
            "score": _as_float(item.get("score")),
            "mood": _clean_mood(item.get("mood")),
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
    moods = [m for m in (opts.get("mood_filter") or []) if m in MOODS]
    mood_hint = ""
    if moods:
        mood_hint = "\nНужны только эти настроения: " + ", ".join(moods) + "."
    return (
        f"Видео длится {_stamp(duration)}. Клипы от {opts.get('min_dur')} до "
        f"{opts.get('max_dur')} секунд, цель — около {opts.get('target_dur')}.\n"
        f"Верни не больше {want} лучших моментов.{mood_hint}\n\n"
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
        for item in _clean_items(_extract_json(content), len(sents), limit=60):
            signature = (item["from"], item["to"])
            if signature in seen:
                continue
            seen.add(signature)
            items.append(item)
    if items:
        _cache_write(_cache_path(workdir), key, provider, items)
    return items


def _to_candidates(items: List[Dict[str, Any]], sents: List[Dict[str, Any]],
                   duration: float, opts: Dict[str, Any], curve: List[float],
                   mean_db: float, hop: float, energy_offset: float,
                   provider: str) -> List[Dict[str, Any]]:
    max_dur = float(opts.get("max_dur") or 60)
    min_dur = float(opts.get("min_dur") or 15)
    min_score = float(opts.get("min_score") or 0.0)
    moods = [m for m in (opts.get("mood_filter") or []) if m in MOODS]

    candidates: List[Dict[str, Any]] = []
    for item in items:
        if item.get("score", 0.0) < min_score:
            continue
        if moods and item.get("mood") not in moods:
            continue
        start_i, end_i = item["from"], item["to"]
        start_i, end_i = analyze._extend_window(sents, start_i, end_i, max_dur)
        while end_i > start_i and sents[end_i]["end"] - sents[start_i]["start"] > max_dur:
            end_i -= 1
        start = sents[start_i]["start"]
        end = sents[end_i]["end"]
        if end - start > max_dur or end - start < 3.0:
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
        out.append({
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": round(end - start, 2),
            "score": cand["score"],
            "parts": cand["parts"],
            "title": cand["title"],
            "hook": cand["hook"],
            "caption": analyze._make_caption(
                cand["title"], clip_text, str(opts.get("platform") or "shorts")),
            "keywords": analyze._keywords(clip_text, 6),
            "words": words,
            "mood": cand["mood"],
            "why": cand["why"],
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
    chain = ["deepseek", "gemini"] if picker == "auto" else [picker]
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
        content, _usage = _chat(
            provider,
            [{"role": "user", "content": "Ответь одним словом: ок"}],
            max_tokens=8, json_mode=False,
        )
    except LLMError as exc:
        return {"ok": False, "status": exc.status, "message": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": str(exc)[:300]}
    return {
        "ok": True,
        "model": app_settings.model_for(provider),
        "message": f"Ключ работает. Ответ: {(content or '').strip()[:40]}",
    }
