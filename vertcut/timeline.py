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
    return {
        "segments": segments,
        "words": remap_words(words, segments, speed),
        "duration": round(max(0.4, total / speed), 3),
        "cut": len(segments) > 1,
    }


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
