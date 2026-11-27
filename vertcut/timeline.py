"""Таймлайн клипа: вырезание пауз, ускорение и пересчёт таймингов.

Любая операция, меняющая длительность (склейки, скорость), обязана пересчитать
времена слов и траекторию кадрирования. Иначе караоке и умный кроп разъезжаются
относительно картинки. Модуль чистый: без ffmpeg и без обращений к диску.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

Span = Tuple[float, float]

# Пауза короче этого не режется: иначе речь превращается в «пулемёт».
MIN_GAP = 0.5
# Запас вокруг слова, чтобы не срезать согласные.
PAD = 0.18
# Сколько тишины оставить по краям склейки — речь не должна обрываться вплотную.
# Берётся из PAD, поэтому всегда меньше него.
BREATHE = 0.10
# Если склейки суммарно снимают меньше этого, они бессмысленны.
MIN_SAVING = 0.30


def _clip_spans(words: Sequence[Dict[str, Any]], start: float, end: float) -> List[Span]:
    spans: List[Span] = []
    for word in words or []:
        try:
            a = max(start, float(word["start"]))
            b = min(end, float(word["end"]))
        except (KeyError, TypeError, ValueError):
            continue
        if b - a > 0.02:
            spans.append((a, b))
    spans.sort()
    merged: List[Span] = []
    for a, b in spans:
        if merged and a <= merged[-1][1] + 0.001:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def speech_segments(words: Sequence[Dict[str, Any]], start: float, end: float,
                    min_gap: float = MIN_GAP, pad: float = PAD,
                    breathe: float = BREATHE) -> List[Span]:
    """Куски для склейки, относительно начала клипа: всё, кроме пауз."""
    duration = max(0.1, float(end) - float(start))
    spans = _clip_spans(words, float(start), float(end))
    if len(spans) < 2:
        return [(0.0, duration)]

    # расширяем каждую реплику и сливаем то, что после расширения пересекается
    padded: List[Span] = []
    for a, b in spans:
        a2 = max(float(start), a - pad)
        b2 = min(float(end), b + pad)
        if padded and a2 <= padded[-1][1]:
            padded[-1] = (padded[-1][0], max(padded[-1][1], b2))
        else:
            padded.append((a2, b2))

    # паузы короче min_gap не режем
    merged: List[Span] = []
    for a, b in padded:
        if merged and a - merged[-1][1] < min_gap:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))

    if len(merged) < 2:
        return [(0.0, duration)]

    # Дыхание по краям склейки берём только из запаса pad: слово не обрезаем.
    shift = min(breathe, pad)
    out: List[Span] = []
    for i, (a, b) in enumerate(merged):
        left = a + (shift if i > 0 else 0.0)
        right = b - (shift if i < len(merged) - 1 else 0.0)
        if right - left < 0.08:
            mid = (a + b) / 2.0
            left, right = mid - 0.04, mid + 0.04
        out.append((max(a, left), min(b, right)))

    kept = sum(b - a for a, b in out)
    speech_total = sum(b - a for a, b in spans)
    # Речь может занимать малую долю клипа (паузы, музыка) — сравниваем
    # с самими репликами, а не с длиной фрагмента.
    if speech_total > 0 and kept < speech_total * 0.5:
        return [(0.0, duration)]
    if duration - kept < MIN_SAVING:
        return [(0.0, duration)]
    return [(round(a - float(start), 3), round(b - float(start), 3)) for a, b in out]


def offsets(segments: Sequence[Span]) -> Tuple[List[float], float]:
    """Накопительное смещение каждого куска на выходном таймлайне."""
    acc = 0.0
    out: List[float] = []
    for a, b in segments:
        out.append(acc)
        acc += max(0.0, b - a)
    return out, acc


def remap_time(value: float, segments: Sequence[Span], speed: float = 1.0) -> float:
    """Время внутри исходного фрагмента -> время готового клипа."""
    speed = max(0.01, float(speed or 1.0))
    offs, _total = offsets(segments)
    for i, (a, b) in enumerate(segments):
        if value <= a:
            return round(offs[i] / speed, 3)
        if value < b:
            return round((offs[i] + (value - a)) / speed, 3)
    return round((offs[-1] + max(0.0, segments[-1][1] - segments[-1][0])) / speed, 3)


def remap_words(words: Sequence[Dict[str, Any]], segments: Sequence[Span],
                speed: float = 1.0) -> List[Dict[str, Any]]:
    """Слова на выходном таймлайне (0..длительность клипа), с учётом скорости."""
    speed = max(0.01, float(speed or 1.0))
    out: List[Dict[str, Any]] = []
    for word in words or []:
        try:
            ws = float(word["start"])
            we = float(word["end"])
        except (KeyError, TypeError, ValueError):
            continue
        for a, b in segments:
            lo = max(ws, a)
            hi = min(we, b)
            if hi - lo <= 0.02:
                continue
            mapped = dict(word)
            mapped["start"] = round(remap_time(lo, segments, speed), 3)
            mapped["end"] = round(remap_time(hi, segments, speed), 3)
            if mapped["end"] - mapped["start"] < 0.03:
                mapped["end"] = round(mapped["start"] + 0.03, 3)
            out.append(mapped)
    out.sort(key=lambda item: float(item["start"]))
    return out


def scale_words(words: Sequence[Dict[str, Any]], clip_start: float,
                speed: float = 1.0) -> List[Dict[str, Any]]:
    """Только ускорение: слова остаются на месте, время сжимается."""
    speed = max(0.01, float(speed or 1.0))
    out: List[Dict[str, Any]] = []
    for word in words or []:
        try:
            ws = (float(word["start"]) - clip_start) / speed
            we = (float(word["end"]) - clip_start) / speed
        except (KeyError, TypeError, ValueError):
            continue
        mapped = dict(word)
        mapped["start"] = round(max(0.0, ws), 3)
        mapped["end"] = round(max(ws + 0.03, we), 3)
        out.append(mapped)
    return out


def _sample(path: Optional[Dict[str, Any]]) -> List[Tuple[float, float, float]]:
    if not path:
        return []
    times = list(path.get("times") or [])
    xs = list(path.get("x") or [])
    ys = list(path.get("y") or [])
    return [(float(t), float(x), float(y)) for t, x, y in zip(times, xs, ys)]


def _interp(points: Sequence[Tuple[float, float, float]], t: float) -> Tuple[float, float]:
    if not points:
        return 0.0, 0.0
    if t <= points[0][0]:
        return points[0][1], points[0][2]
    if t >= points[-1][0]:
        return points[-1][1], points[-1][2]
    for i in range(len(points) - 1):
        t0, x0, y0 = points[i]
        t1, x1, y1 = points[i + 1]
        if t0 <= t <= t1:
            k = 0.0 if t1 <= t0 else (t - t0) / (t1 - t0)
            return x0 + (x1 - x0) * k, y0 + (y1 - y0) * k
    return points[-1][1], points[-1][2]


def remap_crop_path(path: Optional[Dict[str, Any]], segments: Sequence[Span],
                    speed: float = 1.0) -> Optional[Dict[str, Any]]:
    """Траектория кропа на выходном таймлайне (склейки + скорость)."""
    points = _sample(path)
    if not path or not points or not segments:
        return path
    speed = max(0.01, float(speed or 1.0))

    times: List[float] = []
    xs: List[float] = []
    ys: List[float] = []
    for a, b in segments:
        for t, x, y in points:
            if a < t < b:
                times.append(remap_time(t, segments, speed))
                xs.append(x)
                ys.append(y)
        for edge in (a, b):
            x, y = _interp(points, edge)
            times.append(remap_time(edge, segments, speed))
            xs.append(x)
            ys.append(y)

    order = sorted(range(len(times)), key=lambda i: times[i])
    result = dict(path)
    result["times"] = [times[i] for i in order]
    result["x"] = [xs[i] for i in order]
    result["y"] = [ys[i] for i in order]
    return result


def plan(words: Sequence[Dict[str, Any]], start: float, end: float,
         speed: float = 1.0) -> Dict[str, Any]:
    """Готовый план для рендера: куски, слова и длительность."""
    speed = max(1.0, float(speed or 1.0))
    segments = speech_segments(words, start, end)
    total = sum(b - a for a, b in segments)
    # segments считаются от начала клипа, слова — от начала источника:
    # без сдвига remap_words не находит пересечений и возвращает пустой список.
    relative: List[Dict[str, Any]] = []
    for word in words or []:
        try:
            item = dict(word)
            item["start"] = float(word["start"]) - float(start)
            item["end"] = float(word["end"]) - float(start)
        except (KeyError, TypeError, ValueError):
            continue
        relative.append(item)
    return {
        "segments": segments,
        "words": remap_words(relative, segments, speed),
        "duration": round(max(0.4, total / speed), 3),
        "cut": len(segments) > 1,
    }


def insert_spans(segments: Sequence[Span], events: Sequence[Dict[str, Any]],
                 speed: float = 1.0, duration: Optional[float] = None) -> Dict[str, Any]:
    """Точки вставки рекламы на итоговом таймлайне.

    `start` события — секунды исходного фрагмента (0 = начало клипа).
    `at` — время до вставки (после склеек и скорости), `final_start` — после
    всех предыдущих вставок. Событие внутри вырезанной паузы прилипает к
    ближайшему сохранённому моменту через `remap_time`.
    """
    segs = list(segments) if segments else [(0.0, max(0.0, float(duration or 0.0)))]
    base = (float(duration) if duration is not None
            else sum(max(0.0, b - a) for a, b in segs) / max(0.01, float(speed or 1.0)))
    base = max(0.0, base)
    inserts: List[Dict[str, Any]] = []
    for event in events or []:
        if not isinstance(event, dict) or event.get("kind") != "replace":
            continue
        try:
            length = float(event.get("duration") or 0.0)
            start = float(event.get("start") or 0.0)
        except (TypeError, ValueError):
            continue
        if length <= 0:
            continue
        at = max(0.0, min(base, remap_time(max(0.0, start), segs, speed)))
        inserts.append({"at": round(at, 3), "duration": round(length, 3),
                        "event": event})
    inserts.sort(key=lambda item: (item["at"], item["duration"]))
    acc = 0.0
    for item in inserts:
        item["final_start"] = round(item["at"] + acc, 3)
        acc += item["duration"]
    return {"inserts": inserts, "duration": round(base + acc, 3),
            "added": round(acc, 3)}


def inserted_time(value: float, inserts: Sequence[Dict[str, Any]],
                  inclusive: bool = True) -> float:
    """Время базового таймлайна -> время с учётом вставок.

    inclusive=True для начала накладки: начавшаяся ровно во вставке, она
    появляется после неё. Для конца inclusive=False — накладка, кончающаяся
    во вставке, не растягивается.
    """
    shift = 0.0
    for item in inserts or []:
        at = float(item.get("at") or 0.0)
        if at < value or (inclusive and at <= value):
            shift += float(item.get("duration") or 0.0)
    return round(float(value) + shift, 3)


def unmap_inserted(value: float, inserts: Sequence[Dict[str, Any]]) -> float:
    """Время с учётом вставок -> время базового таймлайна.

    Попадание внутрь рекламы приближает к её началу: другого «сохранённого»
    момента рядом нет.
    """
    current = float(value)
    for item in inserts or []:
        final_start = float(item.get("final_start") or 0.0)
        length = float(item.get("duration") or 0.0)
        if current <= final_start:
            break
        if current < final_start + length:
            return round(float(item.get("at") or final_start), 3)
        current -= length
    return round(current, 3)


def unmap_time(value: float, segments: Sequence[Span],
               speed: float = 1.0) -> float:
    """Время готового клипа -> время исходного фрагмента (обратное remap_time)."""
    speed = max(0.01, float(speed or 1.0))
    segs = list(segments) or [(0.0, 0.0)]
    offs, _total = offsets(segs)
    target = max(0.0, float(value)) * speed
    for i, (a, b) in enumerate(segs):
        if target < offs[i] + max(0.0, b - a):
            return round(a + max(0.0, target - offs[i]), 3)
    return round(segs[-1][1], 3)


def insert_words(words: Sequence[Dict[str, Any]],
                 inserts: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Слова базового таймлайна -> слова с учётом вставок.

    Слово, попавшее на вставку, обрывается в её начале: во время рекламы
    субтитров нет. Слова после вставки сдвигаются.
    """
    out: List[Dict[str, Any]] = []
    for word in words or []:
        try:
            start = float(word["start"])
            end = float(word["end"])
        except (KeyError, TypeError, ValueError):
            continue
        crossing = [float(item["at"]) for item in inserts or []
                    if start < float(item["at"]) < end]
        if crossing:
            end = min(crossing)
        mapped = dict(word)
        mapped["start"] = inserted_time(start, inserts, inclusive=True)
        mapped["end"] = inserted_time(end, inserts, inclusive=False)
        if mapped["end"] - mapped["start"] < 0.03:
            continue
        out.append(mapped)
    out.sort(key=lambda item: float(item["start"]))
    return out


def shift_words(words: Sequence[Dict[str, Any]], offset: float,
                duration: Optional[float] = None) -> List[Dict[str, Any]]:
    """Слова из таймлайна дубляжа -> таймлайн видео.

    Положительный offset задерживает дубляж: его время t соответствует
    видео t + offset. Слова вне ролика отбрасываются, границы подрезаются.
    """
    shift = float(offset or 0.0)
    limit = None if duration is None else max(0.0, float(duration))
    out: List[Dict[str, Any]] = []
    for word in words or []:
        try:
            start = float(word["start"]) + shift
            end = float(word["end"]) + shift
        except (KeyError, TypeError, ValueError):
            continue
        if limit is not None:
            if end <= 0 or start >= limit:
                continue
            start = max(0.0, start)
            end = min(limit, end)
        if end - start < 0.03:
            continue
        mapped = dict(word)
        mapped["start"] = round(start, 3)
        mapped["end"] = round(end, 3)
        out.append(mapped)
    out.sort(key=lambda item: float(item["start"]))
    return out


def shift_transcript(segments: Sequence[Dict[str, Any]], offset: float,
                     duration: Optional[float] = None) -> List[Dict[str, Any]]:
    """Реплики распознавания по дубляжу -> таймлайн видео."""
    shift = float(offset or 0.0)
    limit = None if duration is None else max(0.0, float(duration))
    out: List[Dict[str, Any]] = []
    for seg in segments or []:
        words = shift_words(seg.get("words") or [], shift, limit)
        try:
            start = float(seg.get("start") or 0.0) + shift
            end = float(seg.get("end") or 0.0) + shift
        except (TypeError, ValueError):
            start, end = 0.0, 0.0
        if limit is not None:
            start = max(0.0, min(limit, start))
            end = max(0.0, min(limit, end))
        if words:
            start = min(start, float(words[0]["start"]))
            end = max(end, float(words[-1]["end"]))
        if end - start < 0.03 and not words:
            continue
        mapped = dict(seg)
        mapped["start"] = round(start, 3)
        mapped["end"] = round(max(end, start + 0.03), 3)
        mapped["words"] = words
        out.append(mapped)
    return out


def dub_pieces(segments: Sequence[Span], offset: float = 0.0,
               available: float = 0.0) -> List[Dict[str, Any]]:
    """Куски внешней дорожки под таймлайн клипа.

    offset — сдвиг дубляжа: положительный задерживает звук, отрицательный
    ускоряет. available — длительность файла дубляжа. Возвращает порядок
    воспроизведения: {"audio": True, "start", "end"} — время файла,
    {"audio": False, "duration"} — тишина на месте недостающего куска.
    """
    shift = float(offset or 0.0)
    limit = max(0.0, float(available or 0.0))
    out: List[Dict[str, Any]] = []
    for a, b in segments or []:
        length = max(0.0, float(b) - float(a))
        if length <= 0.0:
            continue
        start = float(a) - shift
        end = float(b) - shift
        lo = max(0.0, start)
        hi = min(end, limit)
        if hi - lo <= 0.03:
            out.append({"audio": False, "duration": round(length, 3)})
            continue
        head = min(length, max(0.0, lo - start))
        tail = min(max(0.0, length - head), max(0.0, end - hi))
        if head > 0.03:
            out.append({"audio": False, "duration": round(head, 3)})
        out.append({"audio": True, "start": round(lo, 3), "end": round(hi, 3)})
        if tail > 0.03:
            out.append({"audio": False, "duration": round(tail, 3)})
    return out


def event_window(local_start: float, local_end: float, *,
                 segments: Optional[Sequence[Span]], speed: float,
                 inserts: Sequence[Dict[str, Any]],
                 duration: float) -> Tuple[float, float]:
    """Окно события в финальной шкале клипа (после склеек и вставок).

    Одна формула для рендера и для интерфейса: таймлайн рекламы в редакторе
    обязан совпадать с тем, что реально попадёт в файл.
    """
    span = list(segments or [(0.0, max(0.1, float(local_end)))])
    base_start = remap_time(local_start, span, speed)
    base_end = remap_time(local_end, span, speed)
    start = inserted_time(base_start, inserts, inclusive=True)
    end = min(float(duration), inserted_time(base_end, inserts, inclusive=False))
    return start, end


def insert_window(insert: Dict[str, Any]) -> Tuple[float, float]:
    """Вставка живёт в финальной шкале ровно свою длину."""
    start = float(insert.get("final_start") or 0.0)
    return start, start + float(insert.get("duration") or 0.0)


def rebase_insert_words(words: Sequence[Dict[str, Any]], base: float,
                        inserts: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Слова с абсолютной шкалой -> сдвинутые на вставки (снова абсолютные)."""
    if not inserts:
        return list(words)
    relative = [{**word,
                 "start": float(word["start"]) - base,
                 "end": float(word["end"]) - base}
                for word in words]
    shifted = insert_words(relative, inserts)
    return [{**word,
             "start": round(float(word["start"]) + base, 3),
             "end": round(float(word["end"]) + base, 3)}
            for word in shifted]


def promo_windows(timing: str, *, duration: float,
                  start: float = 0.0, length: float = 4.0,
                  period: float = 20.0) -> List[Span]:
    """Окна показа промо-футажа в финальной шкале клипа.

    Возвращает непересекающиеся пары ``(start, end)`` в секундах от 0 до
    ``duration``. Короткие обрезки (< 0.2 с) отбрасываются.
    """
    dur = max(0.0, float(duration or 0.0))
    if dur < 0.2:
        return []
    kind = str(timing or "loop").strip().lower()
    if kind == "loop":
        return [(0.0, round(dur, 3))]

    win_len = max(0.2, float(length or 4.0))
    if kind == "start":
        s = max(0.0, float(start or 0.0))
        e = min(dur, s + win_len)
        return [(round(s, 3), round(e, 3))] if e - s >= 0.2 else []

    if kind == "end":
        s = max(0.0, dur - win_len)
        return [(round(s, 3), round(dur, 3))] if dur - s >= 0.2 else []

    if kind == "periodic":
        s = max(0.0, float(start or 0.0))
        step = max(0.5, float(period or 20.0))
        eff_len = min(win_len, step)
        out: List[Span] = []
        cursor = s
        while cursor < dur - 0.05 and len(out) < 200:
            e = min(dur, cursor + eff_len)
            if e - cursor >= 0.2:
                out.append((round(cursor, 3), round(e, 3)))
            cursor += step
        return out

    return [(0.0, round(dur, 3))]


def map_windows_to_base(windows: Sequence[Span],
                        inserts: Sequence[Dict[str, Any]]) -> List[Span]:
    """Переводит окна финального таймлайна в базовую шкалу (до вставок replace).

    Куски окон, попавшие внутрь вставки рекламы, вырезаются; смежные части
    объединяются.
    """
    if not windows:
        return []
    spans: List[Span] = []
    for raw_a, raw_b in windows:
        a, b = float(raw_a), float(raw_b)
        if b - a <= 0.02:
            continue
        pieces: List[Span] = [(a, b)]
        for item in inserts or []:
            ins_a = float(item.get("final_start") or 0.0)
            ins_b = ins_a + max(0.0, float(item.get("duration") or 0.0))
            if ins_b <= ins_a:
                continue
            next_pieces: List[Span] = []
            for pa, pb in pieces:
                if pb <= ins_a or pa >= ins_b:
                    next_pieces.append((pa, pb))
                else:
                    if pa < ins_a:
                        next_pieces.append((pa, ins_a))
                    if pb > ins_b:
                        next_pieces.append((ins_b, pb))
            pieces = next_pieces
        for pa, pb in pieces:
            if pb - pa < 0.05:
                continue
            ba = unmap_inserted(pa, inserts)
            bb = unmap_inserted(pb, inserts)
            if bb - ba >= 0.05:
                spans.append((round(ba, 3), round(bb, 3)))
    spans.sort()
    merged: List[Span] = []
    for a, b in spans:
        if merged and a <= merged[-1][1] + 0.02:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged
