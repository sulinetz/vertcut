"""Поиск «вирусных» фрагментов: эвристики по тексту, паузам и громкости.

Без внешних API: считаем потенциальную удержку по структуре речи.
Каждый клип получает score 0..1 и объяснение (какие факторы сработали).
"""
from __future__ import annotations

import difflib
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import utils

# Сколько окон вообще пробуем оценить: длинные записи иначе дают O(n^2) памяти.
MAX_CANDIDATES = 4000

# --- Лексиконы ---------------------------------------------------------------

HOOK_PATTERNS_RU = [
    r"\bпочему\b", r"\bкак\b", r"\bчто если\b", r"\bникогда\b", r"\bвсегда\b",
    r"\bсекрет", r"\bошибк", r"\bникто не\b", r"\bкаждый\b", r"\bглавн",
    r"\bпредставь", r"\bзнаешь", r"\bвыяснил", r"\bоказалось", r"\bправда\b",
    r"\bзапрещ", r"\bбесплатн", r"\bденьг", r"\bмиллион", r"\bтысяч",
    r"\bшок", r"\bсрочно", r"\bвнимание", r"\bстоп\b", r"\bхватит\b",
]
HOOK_PATTERNS_EN = [
    r"\bwhy\b", r"\bhow\b", r"\bwhat if\b", r"\bnever\b", r"\bsecret", r"\bmistake",
    r"\bnobody\b", r"\btruth\b", r"\bwarning\b", r"\binsane", r"\bcrazy\b",
    r"\bactually\b", r"\bhere'?s\b", r"\bstop\b", r"\bmoney\b", r"\bmillion",
]
EMOTION_RU = [
    "страшн", "шок", "безумн", "невероятн", "ужасн", "провал", "провалил", "катастроф",
    "паник", "злил", "ненавиж", "любл", "мечт", "боял", "стыдн", "смешн", "туп",
    "гениальн", "лёгк", "легк", "сложн", "больн", "обидн", "радост", "счастлив",
    "ошибк", "проблем", "кризис", "долг", "банкрот", "богат", "бедн", "потерял",
    "заработал", "вырос", "упал", "провал", "секрет", "обман", "правд", "жесток",
]
EMOTION_EN = [
    "shock", "crazy", "insane", "terrible", "amazing", "incredible", "fail", "failed",
    "disaster", "panic", "hate", "love", "dream", "afraid", "embarrass", "funny",
    "stupid", "genius", "easy", "hard", "painful", "rich", "poor", "lost", "earned",
    "grew", "dropped", "secret", "lie", "truth", "brutal", "mistake",
]
FILLER_START = [
    "и вот", "ну", "вот", "так", "короче", "значит", "эм", "ээ", "как бы", "типа",
    "в общем", "ладно", "окей", "so", "well", "um", "uh", "like", "okay", "yeah",
]

STOPWORDS = set("""
и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только
ее мне было вот от меня еще нет о из ему теперь когда даже ну вдруг ли если уже или ни
быть был него до вас нибудь опять уж вам ведь там потом себя ничего ей может они тут где
есть надо ней для мы тебя их чем была сам чтоб без будто чего раз тоже себе под будет ж
тогда кто этот того потому этого какой совсем ним здесь эту сказать всех никогда сегодня
можно при наконец два об другой хоть после над больше тот через эти нас про всего них какая
много разве три эту моя впрочем хорошо свою этой перед иногда лучше чуть том нельзя такой
им более всегда конечно всю между это очень мой твой ваш наш весь это как-то что-то
the a an and or but if then than that this these those i you he she it we they me my your
is are was were be been being do does did have has had not no yes just very really so well
to of in on at for with from by about as into over after before under again more most some
""".split())

# С каких слов нельзя начинать клип: без предыдущей фразы зритель не поймёт,
# о чём речь. Главная жалоба на автонарезку — «клип начинается после завязки».
CONTEXT_STARTERS = [
    "потому что", "поэтому", "в итоге", "так вот", "и вот", "вот почему", "вот что",
    "значит", "короче", "это", "этот", "эта", "эти", "такой", "такая", "такое",
    "тогда", "но", "однако", "а", "и", "он", "она", "они", "его", "ее", "ему", "ей",
    "им", "их", "там", "тут", "тоже", "также",
    "because", "so", "this", "that", "these", "those", "it", "they", "them", "he",
    "she", "his", "her", "but", "and", "then", "which", "there",
]

# Слова-связки в конце фразы: мысль не закончена, клип оборвётся.
CONTINUATION_END = [
    "потому что", "потому", "так что", "и", "а", "но", "или", "либо", "которые",
    "который", "которая", "которое", "что", "чтобы", "если", "когда", "пока",
    "because", "so", "and", "but", "or", "which", "that", "if", "when", "while",
]

# Реклама и заставки в начале/конце выпуска — плохие моменты для нарезки.
SPONSOR_MARKERS = (
    "промокод", "промо", "спонсор", "реклама", "подписывай", "подписывайтесь",
    "бусти", "boosty", "patreon", "донат", "donation", "купон", "скидка",
    "ссылке в описании", "description", "канал спонсора",
)
INTRO_GUARD = 20.0
OUTRO_GUARD = 20.0

_NUM_RE = re.compile(r"\d+[.,]?\d*|%|₽|\$|€|руб|тысяч|миллион|миллиард|процент", re.I)
_SENT_END = re.compile(r"[.!?…]+[\"'»)]*\s*$")
_WORD_RE = re.compile(r"[\w\-']+", re.U)
_FILLER_RE = re.compile(
    r"^(?:" + "|".join(sorted((re.escape(item) for item in FILLER_START),
                               key=len, reverse=True)) + r")\b",
    re.I,
)


def _norm(text: str) -> str:
    return text.lower().replace("ё", "е")


def _count_patterns(text: str, patterns: List[str]) -> int:
    low = _norm(text)
    return sum(1 for p in patterns if re.search(p, low))


def _has_filler_start(text: str) -> bool:
    low = _norm(text).strip(" «\"'—-")
    return bool(_FILLER_RE.match(low))


def _sponsor_penalty(text: str) -> float:
    low = _norm(text)
    hits = sum(1 for marker in SPONSOR_MARKERS if marker in low)
    return min(0.35, hits * 0.18)


def _weak_share(sents: List[Dict[str, Any]]) -> float:
    """Доля предложений с низкой уверенностью Whisper."""
    values = [float(s["conf"]) for s in sents if s.get("conf") is not None]
    if not values:
        return 0.0
    return sum(1 for value in values if value < -0.8) / len(values)


def _starts_with_context(sent: Dict[str, Any]) -> bool:
    """Фраза начинается с местоимения/связки — без предыдущей фразы непонятна."""
    words = _norm(sent.get("text") or "").strip(" «\"'—-").split()
    if not words:
        return False
    head = " ".join(words[:2])
    first = words[0]
    for marker in CONTEXT_STARTERS:
        if " " in marker:
            if head.startswith(marker):
                return True
        elif first == marker:
            return True
    return False


def _ends_with_continuation(sent: Dict[str, Any]) -> bool:
    """Фраза обрывается на связке — мысль продолжится в следующей."""
    text = _norm(sent.get("text") or "").strip()
    if not text:
        return True
    if text.endswith(("?", "!", "…")):
        return False
    if text.endswith((",", "—", "-", ":", ";", "–")):
        return True  # фраза оборвана посреди мысли
    text = text.rstrip(".,;:")
    words = text.split()
    if not words:
        return True
    tail1 = words[-1]
    tail2 = " ".join(words[-2:])
    if tail2 in ("потому что", "так что", "в том что"):
        return True
    return tail1 in CONTINUATION_END


def _extend_window(sents: List[Dict[str, Any]], i: int, j: int,
                   max_dur: float, max_back: int = 2, max_fwd: int = 2) -> Tuple[int, int]:
    """Дотягивает окно до завязки слева и до вывода справа, если это укладывается в лимит.

    Именно из-за этого автонарезка «начинается после завязки» и «обрывается за
    секунду до главной фразы»: границы берутся по форме предложений, а не по смыслу.
    """
    span = lambda a, b: sents[b]["end"] - sents[a]["start"]
    back = 0
    while back < max_back and i > 0 and _starts_with_context(sents[i]) and span(i - 1, j) <= max_dur:
        i -= 1
        back += 1
    fwd = 0
    while fwd < max_fwd and j + 1 < len(sents):
        nxt = sents[j + 1]
        needs_tail = _ends_with_continuation(sents[j])
        # короткий вопрос + короткий ответ — это завязка и развязка одной мысли
        question_payoff = (
            sents[j]["text"].strip().endswith("?")
            and len(_WORD_RE.findall(sents[j]["text"])) <= 14
            and len(_WORD_RE.findall(nxt["text"])) <= 22
        )
        short_conclusion = _starts_with_context(nxt) and len(_WORD_RE.findall(nxt["text"])) <= 14
        if not (needs_tail or short_conclusion or question_payoff) or span(i, j + 1) > max_dur:
            break
        j += 1
        fwd += 1
    return i, j


def build_sentences(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Склеивает слова в предложения по пунктуации и паузам."""
    words: List[Dict[str, Any]] = []
    for seg in segments:
        confidence = (seg.get("quality") or {}).get("avg_logprob")
        for w in seg.get("words") or []:
            token = (w.get("word") or "").strip()
            if token:
                item = {"word": token, "start": float(w["start"]), "end": float(w["end"])}
                if confidence is not None:
                    item["conf"] = float(confidence)
                words.append(item)
    if not words:
        return []

    sentences: List[Dict[str, Any]] = []
    cur: List[Dict[str, Any]] = []

    def flush() -> None:
        if not cur:
            return
        text = " ".join(w["word"] for w in cur)
        text = re.sub(r"\s+([,.!?…:;])", r"\1", text).strip()
        sentence = {
            "start": cur[0]["start"],
            "end": cur[-1]["end"],
            "text": text,
            "words": list(cur),
        }
        confs = [w["conf"] for w in cur if "conf" in w]
        if confs:
            sentence["conf"] = sum(confs) / len(confs)
        sentences.append(sentence)
        cur.clear()

    for i, w in enumerate(words):
        if cur:
            gap = w["start"] - cur[-1]["end"]
            if gap > 0.7 and len(cur) >= 3:
                flush()
        cur.append(w)
        ends_sentence = bool(_SENT_END.search(w["word"])) or w["word"].endswith(("?", "!", "…"))
        too_long = len(" ".join(x["word"] for x in cur)) > 220
        if ends_sentence or too_long:
            flush()
    flush()
    return sentences


def _wav_energy(path: Path, hop: float) -> Tuple[List[float], float]:
    """RMS по кадрам из готового audio16k.wav: читаем блоками, а не всю запись."""
    import wave

    import numpy as np

    values: List[float] = []
    total = 0.0
    with wave.open(str(path), "rb") as wf:
        if wf.getsampwidth() != 2:
            raise ValueError("ожидается 16-bit PCM")
        rate = wf.getframerate()
        channels = wf.getnchannels()
        hint = max(1, int(round(rate * 30)))
        n = max(1, int(hop * rate))
        carry = np.zeros(0, dtype=np.float32)
        while True:
            raw = wf.readframes(hint)
            if not raw:
                break
            block = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            if channels > 1:
                block = block.reshape(-1, channels).mean(axis=1)
            data = np.concatenate([carry, block]) if carry.size else block
            frames = len(data) // n
            carry = data[frames * n:]
            if not frames:
                continue
            rms = np.sqrt(np.mean(data[:frames * n].reshape(frames, n) ** 2, axis=1) + 1e-12)
            db = 20 * np.log10(np.maximum(rms, 1e-6))
            values.extend(float(x) for x in db)
            total += float(np.sum(db))
    if not values:
        return [], -60.0
    return values, total / len(values)


def energy_curve(media: Path, hop: float = 0.25,
                 wav: Optional[Path] = None) -> Tuple[List[float], float]:
    """RMS-громкость по кадрам (дБ) и средний уровень.

    Предпочитает готовый audio16k.wav (он уже 16 кГц/моно) и читает его
    блоками: часовая запись больше не занимает сотни мегабайт памяти.
    """
    if wav is not None and Path(wav).exists():
        try:
            return _wav_energy(Path(wav), hop)
        except Exception:  # noqa: BLE001
            pass
    try:
        import numpy as np

        audio = utils.read_audio_mono(media)
        sr = 16000
        n = max(1, int(hop * sr))
        frames = len(audio) // n
        if frames == 0:
            return [], -60.0
        trimmed = audio[: frames * n].reshape(frames, n)
        rms = np.sqrt(np.mean(trimmed ** 2, axis=1) + 1e-12)
        db = 20 * np.log10(np.maximum(rms, 1e-6))
        return [float(x) for x in db], float(np.mean(db))
    except Exception:
        return [], -30.0


def _energy_stats(curve: List[float], mean_db: float, start: float, end: float,
                  hop: float, offset: float = 0.0) -> Tuple[float, float]:
    """Средняя громкость и доля тишины в окне.

    offset — сдвиг дубляжа: кривая построена по его дорожке, а времена клипа
    уже пересчитаны в шкалу видео.
    """
    if not curve:
        return 0.0, 0.0
    a, b = int((start - offset) / hop), int((end - offset) / hop)
    a = max(0, min(a, len(curve) - 1))
    b = max(a + 1, min(b, len(curve)))
    window = curve[a:b]
    if not window:
        return 0.0, 0.0
    mean = sum(window) / len(window)
    # нормализуем относительно среднего по всему видео
    loud = max(0.0, min(1.0, (mean - (mean_db - 6)) / 12.0))
    silence = sum(1 for x in window if x < mean_db - 18) / len(window)
    return loud, silence


def _nearest_quiet(curve: List[float], mean_db: float, t: float, hop: float,
                   window: float = 0.6, offset: float = 0.0) -> float:
    """Сдвигает границу к ближайшей тихой точке — стык звучит чище."""
    if not curve:
        return t
    lo = max(0, int((t - window - offset) / hop))
    hi = min(len(curve) - 1, int((t + window - offset) / hop))
    best, best_score = t, 1e9
    for i in range(lo, hi + 1):
        point = i * hop + offset
        score = abs(curve[i] - (mean_db - 20)) + abs(point - t) * 2.0
        if curve[i] < mean_db - 15 and score < best_score:
            best, best_score = point, score
    return best


def _score_window(sents: List[Dict[str, Any]], media_duration: float,
                  curve: List[float], mean_db: float, hop: float,
                  energy_offset: float = 0.0) -> Tuple[float, Dict[str, float]]:
    text = " ".join(s["text"] for s in sents)
    words = [w for s in sents for w in s["words"]]
    n_words = max(1, len(words))
    start = sents[0]["start"]
    end = sents[-1]["end"]
    dur = end - start
    first = sents[0]["text"]
    low = _norm(text)

    # 1. Хук в первые секунды
    hook = 0.0
    if "?" in first:
        hook += 0.30
    if _NUM_RE.search(first):
        hook += 0.18
    if re.search(r"\b(ты|тебя|твой|вы|ваш|твое)\b", _norm(first)):
        hook += 0.16
    hits = _count_patterns(first, HOOK_PATTERNS_RU + HOOK_PATTERNS_EN)
    hook += min(0.42, hits * 0.16)
    if _has_filler_start(first):
        hook -= 0.28
    if len(_WORD_RE.findall(first)) > 28:
        hook -= 0.12
    if re.search(r"[.!?…]", first):
        hook += 0.08
    hook = max(0.0, min(1.0, hook))

    # 2. Плотность речи
    speech_rate = n_words / max(1.0, dur)
    if 2.0 <= speech_rate <= 5.0:
        rate_score = 1.0 - abs(speech_rate - 3.2) / 3.2
    else:
        rate_score = max(0.0, 0.5 - abs(speech_rate - 3.2) * 0.25)
    loud, silence = _energy_stats(curve, mean_db, start, end, hop, energy_offset)
    retention = 0.55 * rate_score + 0.25 * loud + 0.20 * (1.0 - min(1.0, silence * 2.2))
    retention = max(0.0, min(1.0, retention))

    # 3. Эмоциональная насыщенность
    emo_hits = _count_patterns(text, EMOTION_RU) + _count_patterns(text, EMOTION_EN)
    emo_density = emo_hits / max(1.0, n_words / 100.0)
    emotion = min(1.0, emo_density / 7.0)

    # 4. Конкретика: цифры, деньги, имена
    num_hits = len(_NUM_RE.findall(text))
    specificity = min(1.0, num_hits / 3.0)

    # 5. Завершённость: последнее предложение заканчивается мыслью
    last = sents[-1]["text"].strip()
    completeness = 0.6
    if re.search(r"[.!?…]$", last):
        completeness = 0.85
    if _ends_with_continuation(sents[-1]):
        completeness -= 0.35
    if last.endswith("?") or re.search(r"\b(вот и все|итог|вывод|запомни|вывод)\b", _norm(last)):
        completeness = 1.0
    if len(_WORD_RE.findall(last)) < 3:
        completeness -= 0.3
    completeness = max(0.0, min(1.0, completeness))

    # 6. Формат: оптимальная длина 22–45 секунд
    if 22 <= dur <= 45:
        length_fit = 1.0
    elif dur < 22:
        length_fit = max(0.0, (dur - 10) / 12.0)
    else:
        length_fit = max(0.0, 1.0 - (dur - 45) / 30.0)

    # 7. Наличие «крючка» в конце (вопрос/призыв)
    tail = _norm(" ".join(s["text"] for s in sents[-1:]))
    payoff = 1.0 if ("?" in tail or re.search(r"\b(подпис|коммент|сохран|попроб|сделай)\b", tail)) else 0.45

    score = (
        0.28 * hook
        + 0.18 * retention
        + 0.16 * emotion
        + 0.08 * specificity
        + 0.12 * completeness
        + 0.12 * length_fit
        + 0.06 * payoff
    )
    # Реклама, слабое распознавание и самые края выпуска — минус к оценке.
    score -= _sponsor_penalty(text)
    weak = _weak_share(sents)
    if weak:
        score *= 1.0 - 0.4 * weak
    if media_duration > 120:
        guard = min(INTRO_GUARD, media_duration * 0.05)
        if start < guard or end > media_duration - min(OUTRO_GUARD, media_duration * 0.05):
            score -= 0.08
    parts = {
        "hook": round(hook, 3), "retention": round(retention, 3), "emotion": round(emotion, 3),
        "specificity": round(specificity, 3), "completeness": round(completeness, 3),
        "length_fit": round(length_fit, 3), "payoff": round(payoff, 3),
        "sponsor": round(_sponsor_penalty(text), 3), "weak_text": round(weak, 3),
    }
    return round(min(1.0, max(0.0, score)), 4), parts


@lru_cache(maxsize=4096)
def _keywords_cached(text: str, limit: int) -> Tuple[str, ...]:
    counts: Dict[str, int] = {}
    for w in _WORD_RE.findall(text):
        low = w.lower()
        if len(low) < 4 or low in STOPWORDS or low.isdigit():
            continue
        counts[low] = counts.get(low, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], -len(kv[0])))
    return tuple(w for w, _ in ranked[:limit])


def _keywords(text: str, limit: int = 6) -> List[str]:
    return list(_keywords_cached(text, int(limit)))


def _title_score(text: str) -> float:
    """Насколько фраза годится в заголовок клипа.

    Короткие переходы («Что дальше?», «И вот итог.») в заголовок не идут: они
    ничего не обещают зрителю, а в ленте выглядят мусором.
    """
    t = text.strip()
    length = len(t)
    score = 0.0
    if 25 <= length <= 72:
        score += 2.0
    elif 18 <= length < 25:
        score += 0.8
    elif length < 18:
        score -= 1.5
    if "?" in t:
        score += 1.2
    if _NUM_RE.search(t):
        score += 0.6
    score += min(1.2, 0.4 * _count_patterns(t, HOOK_PATTERNS_RU + HOOK_PATTERNS_EN))
    if _has_filler_start(t):
        score -= 1.0
    if len(_WORD_RE.findall(t)) < 4:
        score -= 1.2
    return score


def _make_title(sents: List[Dict[str, Any]]) -> str:
    """Короткий заголовок: самое «цепляющее» предложение в начале клипа."""
    candidates = [s["text"].strip() for s in sents[:4] if s["text"].strip()]
    best = max(candidates, key=_title_score) if candidates else sents[0]["text"]
    best = re.sub(r"\s+", " ", best).strip(" .,-—")
    if len(best) > 64:
        cut = best[:64]
        if " " in cut:
            cut = cut[: cut.rfind(" ")]
        best = cut + "…"
    return best[:1].upper() + best[1:] if best else "Фрагмент"


def _make_caption(title: str, text: str, platform: str) -> str:
    tags = _keywords(text, 6)
    base = ["shorts", "reels", "tiktok", "виральное", "нарезка"]
    tag_line = " ".join("#" + re.sub(r"[^\w]", "", t) for t in (tags + base) if t)
    return f"{title}\n\n{tag_line}"


def _text_similar(a: str, b: str, threshold: float = 0.74) -> bool:
    """Один и тот же текст в разных местах: припев, повторённая фраза, рефрен."""
    if not a or not b:
        return False
    return difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio() > threshold


def find_segments(segments: List[Dict[str, Any]], media: Path, duration: float,
                  count: int = 10, min_dur: float = 15, max_dur: float = 60,
                  target_dur: float = 32, platform: str = "shorts",
                  wav: Optional[Path] = None,
                  energy_offset: float = 0.0) -> List[Dict[str, Any]]:
    """Возвращает список клипов: тайминги, score, заголовок, объяснение."""
    sents = build_sentences(segments)
    if not sents:
        return []
    curve, mean_db = energy_curve(media, wav=wav)
    hop = 0.25

    candidates: List[Dict[str, Any]] = []
    n = len(sents)
    capped = False
    for i in range(n):
        if capped:
            break
        start = sents[i]["start"]
        if start + min_dur > duration:
            break
        for j in range(i, n):
            end = sents[j]["end"]
            dur = end - start
            if dur > max_dur:
                break
            if dur < min_dur:
                continue
            # Около целевой длины сравниваем несколько вариантов: чуть короче,
            # ровно по цели и на одно предложение длиннее.
            if dur >= target_dur or j == n - 1:
                tried = set()
                for jj in (j - 1, j, j + 1):
                    if jj < i or jj >= n:
                        continue
                    candidate_end = sents[jj]["end"]
                    long = candidate_end - start
                    if long < min_dur or long > max_dur:
                        continue
                    bi, bj = _extend_window(sents, i, jj, max_dur)
                    if (bi, bj) in tried:
                        continue
                    tried.add((bi, bj))
                    window = sents[bi:bj + 1]
                    w_start, w_end = window[0]["start"], window[-1]["end"]
                    if w_end - w_start > max_dur:  # перестраховка на длинных фразах
                        window, w_start, w_end = sents[i:jj + 1], start, candidate_end
                    score, parts = _score_window(window, duration, curve, mean_db, hop,
                                                 energy_offset)
                    candidates.append({
                        "start": round(w_start, 3), "end": round(w_end, 3),
                        "duration": round(w_end - w_start, 2),
                        "score": score, "parts": parts,
                        "text": " ".join(x["text"] for x in window),
                        "words": [w for x in window for w in x["words"]],
                        "title": _make_title(window),
                    })
                    if len(candidates) >= MAX_CANDIDATES:
                        capped = True
                        break
                break

    if not candidates and sents and duration <= 180:
        # короткий клип/запись: берём весь связный фрагмент, даже если он короче min_dur
        start = max(0.0, sents[0]["start"] - 0.2)
        end = min(duration, sents[-1]["end"] + 0.3, start + max(8.0, max_dur))
        if end - start >= 3:
            chunk = sents
            score, parts = _score_window(chunk, duration, curve, mean_db, hop)
            candidates.append({
                "start": round(start, 3), "end": round(end, 3), "duration": round(end - start, 2),
                "score": score, "parts": parts,
                "text": " ".join(x["text"] for x in chunk),
                "words": [w for x in chunk for w in x["words"]],
                "title": _make_title(chunk),
            })

    if not candidates:
        return []

    # Разнообразие: не берём пересекающиеся окна
    candidates.sort(key=lambda c: c["score"], reverse=True)
    limit = count if count > 0 else 999

    # Разнообразие по таймлайну: без него топ-N собирается из одного «сильного»
    # куска, а вторая половина видео не попадает в выдачу вовсе (жалоба на
    # смещение к первым 10–15 минутам).
    buckets = max(1, min(limit, 12))
    span = max(1.0, duration / buckets)

    def _bucket(cand: Dict[str, Any]) -> int:
        middle = (cand["start"] + cand["end"]) / 2
        return max(0, min(buckets - 1, int(middle // span)))

    grouped: Dict[int, List[Dict[str, Any]]] = {}
    for cand in candidates:
        grouped.setdefault(_bucket(cand), []).append(cand)

    best_score = candidates[0]["score"] if candidates else 0.0
    seeded: List[Dict[str, Any]] = []
    for key in sorted(grouped):
        bucket_items = sorted(grouped[key], key=lambda c: c["score"], reverse=True)
        # слабый «лучший в бакете» не должен вытеснять сильные клипы
        if bucket_items and bucket_items[0]["score"] >= best_score * 0.55:
            seeded.append(bucket_items[0])
    seeded.sort(key=lambda c: c["score"], reverse=True)

    leftovers: List[Dict[str, Any]] = []
    seeded_ids = {id(c) for c in seeded}
    for cand in candidates:
        if id(cand) not in seeded_ids:
            leftovers.append(cand)
    ordered_candidates = seeded + leftovers

    import difflib

    def _norm_title(t: str) -> str:
        return re.sub(r"[^\w]+", " ", _norm(t)).strip()

    picked: List[Dict[str, Any]] = []
    for cand in ordered_candidates:
        if len(picked) >= limit:
            break
        overlap = False
        cand_words = set(_keywords(cand["text"], 14))
        for p in picked:
            inter = min(p["end"], cand["end"]) - max(p["start"], cand["start"])
            if inter > 0:
                short = min(p["end"] - p["start"], cand["end"] - cand["start"])
                if inter / short > 0.18:
                    overlap = True
                    break
            if difflib.SequenceMatcher(None, _norm_title(cand["title"]), _norm_title(p["title"])).ratio() > 0.82:
                overlap = True
                break
            # почти одинаковый текст (повторы, нарезка одного и того же) — тоже дубль
            p_words = set(_keywords(p["text"], 14))
            if cand_words and p_words:
                jaccard = len(cand_words & p_words) / len(cand_words | p_words)
                if jaccard > 0.62:
                    overlap = True
                    break
            # Один и тот же припев или повторённая фраза в другом месте выпуска:
            # сравниваем весь текст, а не только ключевые слова.
            if _text_similar(cand.get("text") or "", p.get("text") or ""):
                overlap = True
                break
        if not overlap:
            picked.append(cand)

    picked.sort(key=lambda c: c["score"], reverse=True)
    out: List[Dict[str, Any]] = []
    for idx, c in enumerate(picked):
        start = c["start"]
        end = c["end"]
        # аккуратные границы: отступаем в тишину
        start = max(0.0, _nearest_quiet(curve, mean_db, start - 0.10, hop, window=0.30,
                                        offset=energy_offset))
        end = min(duration, _nearest_quiet(curve, mean_db, end + 0.18, hop,
                                           offset=energy_offset))
        words = [w for w in c["words"] if w["end"] > start + 0.05 and w["start"] < end - 0.05]
        clip_text = " ".join(w["word"] for w in words)
        out.append({
            "idx": idx,
            "start": round(start, 3),
            "end": round(end, 3),
            "duration": round(end - start, 2),
            "score": c["score"],
            "parts": c["parts"],
            "title": c["title"],
            "hook": c["title"],
            "caption": _make_caption(c["title"], clip_text, platform),
            "keywords": _keywords(clip_text, 6),
            "words": words,
        })
    return out
