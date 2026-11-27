"""Генерация ASS-субтитров: шрифт, размер и положение настраиваются."""
from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

from .config import FONTS_DIR
from .utils import ass_time

PLAY_W, PLAY_H = 1080, 1920

ACCENT_PALETTE = {
    "yellow": ("#FFE24A", "&H4AE2FF&"),
    "gold": ("#FFC53D", "&H3DC5FF&"),
    "orange": ("#FF8A3D", "&H3D8AFF&"),
    "coral": ("#FF6B6B", "&H6B6BFF&"),
    "red": ("#FF3D57", "&H573DFF&"),
    "rose": ("#FF5C8A", "&H8A5CFF&"),
    "pink": ("#FF6BD6", "&HD66BFF&"),
    "magenta": ("#E84BFF", "&HFF4BE8&"),
    "violet": ("#B36BFF", "&HFF6BB3&"),
    "purple": ("#8B5CF6", "&HF65C8B&"),
    "indigo": ("#6B7CFF", "&HFF7C6B&"),
    "blue": ("#3D8BFF", "&HFF8B3D&"),
    "sky": ("#3DC8FF", "&HFFC83D&"),
    "cyan": ("#6BE8FF", "&HFFE86B&"),
    "teal": ("#2DE0C8", "&HC8E02D&"),
    "mint": ("#6BFFB0", "&HB0FF6B&"),
    "green": ("#6BFF8C", "&H8CFF6B&"),
    "lime": ("#C6FF4A", "&H4AFFC6&"),
    "peach": ("#FFB38A", "&H8AB3FF&"),
    "lavender": ("#C9B6FF", "&HFFB6C9&"),
    "white": ("#FFFFFF", "&HFFFFFF&"),
}
ACCENTS = {key: value[1] for key, value in ACCENT_PALETTE.items()}

# key -> family в TTF, файл, метрики для одинаковой визуальной высоты и переносов
FONTS: Dict[str, Dict[str, Any]] = {
    "montserrat": {
        "label": "Montserrat", "family": "Montserrat ExtraBold",
        "file": "Montserrat-ExtraBold.ttf", "cap": 0.700, "avg": 0.828,
    },
    "russo": {
        "label": "Russo One", "family": "Russo One",
        "file": "RussoOne-Regular.ttf", "cap": 0.700, "avg": 0.759,
    },
    "ptsans": {
        "label": "PT Sans Narrow", "family": "PT Sans Narrow",
        "file": "PT_Sans-Narrow-Web-Bold.ttf", "cap": 0.700, "avg": 0.546,
    },
    "lato": {
        "label": "Lato Black", "family": "Lato Black",
        "file": "Lato-Black.ttf", "cap": 0.726, "avg": 0.766,
    },
    "play": {
        "label": "Play", "family": "Play",
        "file": "Play-Bold.ttf", "cap": 0.649, "avg": 0.727,
    },
    "philosopher": {
        "label": "Philosopher", "family": "Philosopher",
        "file": "Philosopher-Bold.ttf", "cap": 0.660, "avg": 0.715,
    },
    "oswald": {
        "label": "Oswald", "family": "Oswald Bold",
        "file": "Oswald-Bold.ttf", "cap": 0.810, "avg": 0.884,
    },
    "robotocond": {
        "label": "Roboto Condensed", "family": "Roboto Condensed Bold",
        "file": "RobotoCondensed-Bold.ttf", "cap": 0.711, "avg": 0.879,
    },
    "inter": {
        "label": "Inter Black", "family": "Inter Black",
        "file": "Inter-Black.ttf", "cap": 0.728, "avg": 1.080,
    },
    "rubik": {
        "label": "Rubik ExtraBold", "family": "Rubik ExtraBold",
        "file": "Rubik-ExtraBold.ttf", "cap": 0.700, "avg": 1.113,
    },
    "manrope": {
        "label": "Manrope ExtraBold", "family": "Manrope ExtraBold",
        "file": "Manrope-ExtraBold.ttf", "cap": 0.720, "avg": 1.062,
    },
    "unbounded": {
        "label": "Unbounded", "family": "Unbounded Bold",
        "file": "Unbounded-Bold.ttf", "cap": 0.750, "avg": 1.397,
    },
    "caveat": {
        "label": "Caveat", "family": "Caveat Bold",
        "file": "Caveat-Bold.ttf", "cap": 0.610, "avg": 0.764,
    },
    "yeseva": {
        "label": "Yeseva One", "family": "Yeseva One",
        "file": "YesevaOne-Regular.ttf", "cap": 0.700, "avg": 1.090,
    },
    "exo2": {
        "label": "Exo 2", "family": "Exo 2 Bold",
        "file": "Exo2-Bold.ttf", "cap": 0.690, "avg": 1.033,
    },
    "comfortaa": {
        "label": "Comfortaa", "family": "Comfortaa Bold",
        "file": "Comfortaa-Bold.ttf", "cap": 0.781, "avg": 1.166,
    },
    "golos": {
        "label": "Golos Text", "family": "Golos Text Bold",
        "file": "GolosText-Bold.ttf", "cap": 0.700, "avg": 1.048,
    },
    "onest": {
        "label": "Onest", "family": "Onest ExtraBold",
        "file": "Onest-ExtraBold.ttf", "cap": 0.708, "avg": 1.042,
    },
    "marmelad": {
        "label": "Marmelad", "family": "Marmelad",
        "file": "Marmelad-Regular.ttf", "cap": 0.709, "avg": 0.964,
    },
    "badscript": {
        "label": "Bad Script", "family": "Bad Script",
        "file": "BadScript-Regular.ttf", "cap": 0.960, "avg": 0.755,
    },
    "marckscript": {
        "label": "Marck Script", "family": "Marck Script",
        "file": "MarckScript-Regular.ttf", "cap": 0.638, "avg": 0.868,
    },
    "ruslan": {
        "label": "Ruslan Display", "family": "Ruslan Display",
        "file": "RuslanDisplay-Regular.ttf", "cap": 0.500, "avg": 1.268,
    },
    "stalinist": {
        "label": "Stalinist One", "family": "Stalinist One",
        "file": "StalinistOne-Regular.ttf", "cap": 0.700, "avg": 1.926,
    },
    "underdog": {
        "label": "Underdog", "family": "Underdog",
        "file": "Underdog-Regular.ttf", "cap": 0.710, "avg": 0.943,
    },
}

POSITIONS = ("bottom", "middle", "top")

# Темп субтитров: сколько слов в реплике и сколько она висит после речи.
# «Спокойно» — короткие реплики и пауза на чтение, «Быстро» — плотная нарезка.
SPEED_PRESETS = {
    "calm": {"max_words": 8, "max_chars": 30, "max_gap": 1.10, "hold": 0.60, "min_cue": 1.8, "fade": (90, 130)},
    "normal": {"max_words": 6, "max_chars": 24, "max_gap": 0.80, "hold": 0.40, "min_cue": 1.4, "fade": (75, 105)},
    "fast": {"max_words": 4, "max_chars": 18, "max_gap": 0.55, "hold": 0.20, "min_cue": 1.1, "fade": (60, 85)},
}
SPEEDS = tuple(SPEED_PRESETS)

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {play_w}
PlayResY: {play_h}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{font_family},{sub_size},{sub_primary},{sub_secondary},&H00000000,&H78000000,0,0,0,0,100,100,1,0,1,{outline},3,2,{margin_sub},{margin_sub},320,1
Style: Hook,{font_family},{hook_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H50000000,0,0,0,0,100,100,0.5,0,1,8,4,8,{margin_hook},{margin_hook},240,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\u2190-\u21FF\u2B00-\u2BFF]+"
)

# эмпирические коэффициенты libass: кегль ~0.45 от номинала, ширина символа ~0.62
_RENDER_FACTOR = 0.45
_WIDTH_FACTOR = 0.62
_SAFE_WIDTH = 940.0
_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")
_FONT_OBJ_CACHE: Dict[Tuple[str, int], Any] = {}


def _font_ttf_path(key: str, info: Dict[str, Any]) -> Optional[Path]:
    """Путь к TTF/OTF файла шрифта для точного измерения ширины строки."""
    if key in FONTS:
        p = FONTS_DIR / str(info.get("file") or "")
        return p if p.is_file() else None
    try:
        from . import custom_fonts

        custom = custom_fonts.get(key)
        if custom and custom.get("file"):
            p = custom_fonts.CUSTOM_DIR / str(custom["file"])
            return p if p.is_file() else None
    except Exception:
        pass
    return None


def _line_px(text: str, info: Dict[str, Any], size: int, *,
             font_key: str = "", outline: float = 7.0, spacing: float = 1.0) -> float:
    """Оценка ширины строки в пикселях PlayResX с учётом кернинга и обводки."""
    clean = str(text or "")
    if not clean:
        return 0.0
    extra = max(0, len(clean) - 1) * spacing + outline * 2.0
    ttf = _font_ttf_path(font_key, info)
    if ttf is not None:
        try:
            from PIL import ImageFont

            sz = max(12, int(size))
            cache_key = (str(ttf), sz)
            font_obj = _FONT_OBJ_CACHE.get(cache_key)
            if font_obj is None:
                font_obj = ImageFont.truetype(str(ttf), sz)
                _FONT_OBJ_CACHE[cache_key] = font_obj
            return float(font_obj.getlength(clean)) + extra
        except Exception:  # noqa: BLE001
            pass
    # Запасной расчёт при отсутствии TTF: прописные кириллицы шире строчных.
    is_upper = clean == clean.upper() and clean != clean.lower()
    factor = 0.80 if is_upper else _WIDTH_FACTOR
    advance = max(0.35, float(info.get("avg") or 0.85)) * max(12, size) * factor
    return len(clean) * advance + extra


def _split_cue_lines(tokens: List[str], info: Dict[str, Any], size: int,
                     safe_w: float, *, font_key: str = "") -> List[List[int]]:
    """Делит реплику на 1–3 строки по пробелам так, чтобы влезали в safe_w."""
    n = len(tokens)
    if n <= 1:
        return [list(range(n))] if n else []
    full = " ".join(tokens)
    if _line_px(full, info, size, font_key=font_key) <= safe_w:
        return [list(range(n))]

    # Пробуем 2 сбалансированные строки, укладывающиеся в safe_w.
    best_split = None
    best_score = 1e18
    for split in range(1, n):
        lw = _line_px(" ".join(tokens[:split]), info, size, font_key=font_key)
        rw = _line_px(" ".join(tokens[split:]), info, size, font_key=font_key)
        if lw <= safe_w and rw <= safe_w:
            diff = abs(lw - rw)
            if diff < best_score:
                best_split, best_score = split, diff
    if best_split is not None:
        return [list(range(best_split)), list(range(best_split, n))]

    # Если 2 строки не помещаются (много длинных слов) — собираем до 3 строк.
    groups: List[List[int]] = []
    cur: List[int] = []
    for idx, tok in enumerate(tokens):
        cand = " ".join(tokens[i] for i in (*cur, idx))
        if cur and _line_px(cand, info, size, font_key=font_key) > safe_w:
            groups.append(cur)
            cur = [idx]
        else:
            cur.append(idx)
    if cur:
        groups.append(cur)
    if len(groups) <= 3:
        return groups

    # Слишком много коротких слов — сводим в 2 минимально широкие строки.
    best_split = max(1, n // 2)
    best_peak = 1e18
    for split in range(1, n):
        peak = max(
            _line_px(" ".join(tokens[:split]), info, size, font_key=font_key),
            _line_px(" ".join(tokens[split:]), info, size, font_key=font_key),
        )
        if peak < best_peak:
            best_peak = peak
            best_split = split
    return [list(range(best_split)), list(range(best_split, n))]


def _fit_fontsize(lines: List[str], info: Dict[str, Any], size: int,
                  safe_w: float, *, font_key: str = "", min_size: int = 28,
                  outline: float = 7.0, spacing: float = 1.0) -> int:
    """Уменьшает кегль ровно до того, чтобы самая длинная строка влезла в экран."""
    if not lines or safe_w <= 0:
        return size
    max_px = max(_line_px(line, info, size, font_key=font_key,
                          outline=outline, spacing=spacing)
                 for line in lines)
    if max_px <= safe_w:
        return size
    fitted = max(min_size, int(size * (safe_w / max_px)))
    while fitted > min_size:
        check = max(_line_px(line, info, fitted, font_key=font_key,
                             outline=outline, spacing=spacing)
                    for line in lines)
        if check <= safe_w:
            break
        fitted -= 1
    return fitted


def font_exists(key: str) -> bool:
    if key in FONTS:
        return True
    try:
        from . import custom_fonts

        return custom_fonts.get(key) is not None
    except Exception:
        return False


def font_info(key: str) -> Dict[str, Any]:
    if key in FONTS:
        return FONTS[key]
    try:
        from . import custom_fonts

        custom = custom_fonts.get(key)
        if custom:
            return {**FONTS["montserrat"], **custom}
    except Exception:
        pass
    return FONTS["montserrat"]


def fonts_payload() -> List[Dict[str, str]]:
    return [{"key": k, "label": v["label"]} for k, v in FONTS.items()]


def _clean(text: str) -> str:
    text = _EMOJI_RE.sub("", text)
    text = text.replace("{", "(").replace("}", ")").replace("\\", "/")
    return re.sub(r"\s+", " ", text).strip()


def _chars_per_line(font: Dict[str, Any], size: int, cjk: bool = False,
                    *, play_w: int = PLAY_W) -> int:
    advance = max(0.3, float(font["avg"])) * max(20, size) * _WIDTH_FACTOR
    if cjk:
        advance *= 1.6
    safe_w = max(320.0, float(play_w or PLAY_W) - 140.0)
    return max(6, min(36, int(safe_w / advance)))


def _wrap(text: str, max_chars: int, max_lines: int = 2) -> List[str]:
    words = text.split()
    lines: List[str] = []
    cur = ""
    for w in words:
        candidate = (cur + " " + w).strip()
        if len(candidate) <= max_chars or not cur:
            cur = candidate
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines[:max_lines]


def _cues(words: List[Dict[str, Any]], max_chars: int = 32, max_words: int = 6,
          max_gap: float = 0.55) -> List[List[Dict[str, Any]]]:
    cues: List[List[Dict[str, Any]]] = []
    cur: List[Dict[str, Any]] = []
    for w in words:
        token = (w.get("word") or "").strip()
        if not token:
            continue
        if cur:
            gap = float(w["start"]) - float(cur[-1]["end"])
            length = len(" ".join(x["word"] for x in cur)) + len(token) + 1
            if gap > max_gap or length > max_chars or len(cur) >= max_words:
                cues.append(cur)
                cur = []
        cur.append(w)
        if re.search(r"[.!?…]$", token):
            cues.append(cur)
            cur = []
    if cur:
        cues.append(cur)
    return cues


def _pos_parts(position: str, offset: int, platform: str = "",
               reserve: int = 0, *, play_w: int = PLAY_W,
               play_h: int = PLAY_H) -> Tuple[int, int, int]:
    """(выравнивание, x, y) с учётом интерфейса площадки.

    Сдвиг применяется после безопасной зоны и ограничивается только рамкой
    кадра: так им можно провести субтитры от самого низа до самого верха.
    """
    from . import platforms

    pw = max(320, int(play_w or PLAY_W))
    ph = max(320, int(play_h or PLAY_H))
    y_scale = ph / float(PLAY_H)

    def frame_y(value: float) -> int:
        return int(max(40, min(ph - 40, float(value))))

    if position == "top":
        base = max(60, platforms.top_text_y(platform) + 120)
        base = platforms.clamp_y(base, platform, anchor="top")
        return 8, pw // 2, frame_y(base * y_scale - offset * y_scale)
    if position == "middle":
        _x0, y0, _x1, y1 = platforms.safe_rect(platform)
        base = max(y0 + 120, min(y1 - 120, 960))
        return 5, pw // 2, frame_y(base * y_scale - offset * y_scale)
    base = platforms.bottom_text_y(platform, reserve=reserve)
    base = platforms.clamp_y(base, platform, anchor="bottom")
    return 2, pw // 2, frame_y(base * y_scale - offset * y_scale)


def _pos_tag(position: str, offset: int, platform: str = "", reserve: int = 0) -> str:
    anchor, x, y = _pos_parts(position, offset, platform, reserve)
    return f"\\an{anchor}\\pos({x},{y})"


def _line_events(lines: List[str], layer: int, style: str, start: float, end: float,
                 anchor: int, x: int, y: int, line_h: float, gap: float,
                 tags: str) -> List[str]:
    """Одно событие на реплику или отдельные события на каждую строку.

    В ASS нет межстрочного интервала, поэтому при gap > 0 строки выводятся
    раздельно и раздвигаются вручную.
    """
    if gap <= 0.5 or len(lines) <= 1:
        body = "\\N".join(lines)
        return [f"Dialogue: {layer},{ass_time(start)},{ass_time(end)},{style},,0,0,0,,"
                f"{{\\an{anchor}\\pos({x},{y}){tags}}}{body}"]

    out: List[str] = []
    total = len(lines)
    step = line_h + gap
    durations = [sum(int(value) for value in re.findall(r"\\k(\d+)", line)) for line in lines]
    passed = 0
    for i, line in enumerate(lines):
        if anchor in (1, 2, 3):
            ly = y - (total - 1 - i) * step
        elif anchor in (7, 8, 9):
            ly = y + i * step
        else:
            ly = y + (i - (total - 1) / 2) * step
        # Каждая строка — отдельное событие, поэтому караоке следующей строки
        # должно начаться после времени предыдущих: иначе подсветка «прыгает»
        # на первую строку. \k — сотые доли секунды, как и в словах.
        prefix = f"{{\\k{passed}}}" if i > 0 and passed > 0 else ""
        out.append(f"Dialogue: {layer},{ass_time(start)},{ass_time(end)},{style},,0,0,0,,"
                   f"{{\\an{anchor}\\pos({x},{int(ly)}){tags}}}{prefix}{line}")
        passed += durations[i]
    return out


def _plain(token: str) -> str:
    return re.sub(r"[^\w]+", "", str(token or "").lower().replace("ё", "е"))


def to_srt(words: List[Dict[str, Any]], start: float, end: float,
           max_words: int = 6) -> str:
    """SRT для тех, кто монтирует сам: слова собираются в короткие реплики."""
    def stamp(seconds: float) -> str:
        seconds = max(0.0, float(seconds) - start)
        hours, rest = divmod(int(seconds), 3600)
        minutes, secs = divmod(rest, 60)
        millis = int(round((seconds - int(seconds)) * 1000))
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    cues: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    for w in words or []:
        if float(w.get("end", 0)) <= start or float(w.get("start", 0)) >= end:
            continue
        current.append(w)
        text = " ".join(x["word"] for x in current)
        if len(current) >= max_words or text.rstrip().endswith((".", "!", "?", "…")):
            cues.append(current)
            current = []
    if current:
        cues.append(current)

    lines: List[str] = []
    for index, cue in enumerate(cues, start=1):
        text = " ".join(w["word"] for w in cue).strip()
        if not text:
            continue
        lines.append(f"{index}\n{stamp(max(start, float(cue[0]['start'])))} --> "
                     f"{stamp(min(end, float(cue[-1]['end'])))}\n{text}\n")
    return "\n".join(lines)


def retime_words(words: List[Dict[str, Any]], text: str) -> List[Dict[str, Any]]:
    """Переносит правленый текст обратно на тайминги слов.

    Пользователь исправляет «бак» на «баг» или имя бренда, а субтитры должны
    остаться синхронными: неизменённые слова сохраняют свои тайминги, новые
    распределяются по времени заменённого куска. Так правка текста не требует
    ручной расстановки времени по словам.
    """
    import difflib

    clean = (text or "").strip()
    if not clean:
        return []
    original = [dict(w) for w in (words or [])]
    if not original:
        return []
    new_tokens = clean.split()
    ref = [_plain(w.get("word")) for w in original]
    hyp = [_plain(t) for t in new_tokens]

    matcher = difflib.SequenceMatcher(a=ref, b=hyp, autojunk=False)
    out: List[Dict[str, Any]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                item = dict(original[i1 + k])
                item["word"] = new_tokens[j1 + k]
                out.append(item)
            continue
        if tag == "delete":
            continue
        # replace / insert: растягиваем новые слова на время исходного куска
        if i1 < i2:
            t0 = float(original[i1]["start"])
            t1 = float(original[i2 - 1]["end"])
        else:
            if i1 < len(original):
                t0 = float(original[i1].get("start", 0.0))
                t1 = t0 + 0.4
            else:
                t0 = float(original[-1].get("end", 0.0))
                t1 = t0 + 0.4
        if j2 - j1 == 1 and i2 > i1:
            # одно слово вместо куска — оставляем ровно исходный интервал
            out.append({"word": new_tokens[j1], "start": round(t0, 3), "end": round(t1, 3)})
            continue
        count = max(1, j2 - j1)
        step = max(0.06, (t1 - t0) / count)
        for k in range(j2 - j1):
            start = t0 + k * step
            out.append({"word": new_tokens[j1 + k], "start": round(start, 3),
                        "end": round(start + step * 0.95, 3)})
    out.sort(key=lambda w: float(w.get("start", 0.0)))
    return out


def build_ass(words: List[Dict[str, Any]], clip_start: float, clip_end: float,
              hook: str = "", accent: str = "yellow", uppercase: bool = True,
              show_hook: bool = True, sub_size: int = 118, hook_size: int = 96,
              font: str = "montserrat",
              position: str = "bottom", offset: int = 0,
              speed: str = "calm", platform: str = "", bottom_reserve: int = 0,
              line_gap: int = 0, top_reserve: int = 0,
              blackouts: Optional[List[Tuple[float, float]]] = None,
              play_w: int = PLAY_W, play_h: int = PLAY_H) -> str:
    """Собирает ASS-файл для фрагмента. Тайминги слов абсолютные (от начала видео)."""
    pw = max(320, int(play_w or PLAY_W))
    ph = max(320, int(play_h or PLAY_H))
    y_scale = ph / float(PLAY_H)
    res_scale = 1.0 if (pw == PLAY_W and ph == PLAY_H) else max(0.66, min(pw / float(PLAY_W), ph / float(PLAY_H)))

    accent_color = ACCENTS.get(accent, ACCENTS["yellow"])
    info = font_info(font)
    scale = 0.700 / float(info["cap"])
    size = max(36, min(240, int(round(sub_size * scale * res_scale))))
    hook_size_eff = max(28, int(round(hook_size * scale * res_scale)))
    cjk = any(_CJK_RE.search(str(w.get("word") or "")) for w in words)
    chars = _chars_per_line(info, size, cjk, play_w=pw)
    if position not in POSITIONS:
        position = "bottom"

    margin_sub = max(40, int(round(70 * pw / float(PLAY_W))))
    margin_hook = max(48, int(round(80 * pw / float(PLAY_W))))
    sub_safe_w = max(220.0, (pw - 2 * margin_sub) / 1.04)
    hook_safe_w = max(220.0, (pw - 2 * margin_hook) / 1.04)

    preset = SPEED_PRESETS.get(str(speed), SPEED_PRESETS["calm"])
    header = ASS_HEADER.format(
        play_w=pw, play_h=ph,
        margin_sub=margin_sub, margin_hook=margin_hook,
        font_family=info["family"], sub_size=size, hook_size=hook_size_eff,
        outline=7, sub_primary=accent_color, sub_secondary="&H00FFFFFF&",
    )
    events: List[str] = []
    clip_len = max(0.1, clip_end - clip_start)
    anchor, pos_x, pos_y = _pos_parts(
        position, int(offset), platform, int(bottom_reserve),
        play_w=pw, play_h=ph,
    )
    gap = max(0, min(120, int(line_gap or 0)))

    local = []
    for w in words:
        s = max(0.0, float(w["start"]) - clip_start)
        e = max(s + 0.05, float(w["end"]) - clip_start)
        if s >= clip_len:
            continue
        token = _clean(str(w.get("word") or ""))
        if not token:
            continue
        if uppercase:
            token = token.upper()
        local.append({"word": token, "start": s, "end": min(e, clip_len)})

    # Whisper иногда даёт одинаковые/пересекающиеся тайминги слов — выравниваем,
    # иначе несколько реплик рисуются одновременно и текст накладывается.
    local.sort(key=lambda item: item["start"])
    cursor = 0.0
    for item in local:
        item["start"] = max(item["start"], cursor)
        item["end"] = max(item["end"], item["start"] + 0.08)
        cursor = item["end"]

    if show_hook and hook.strip():
        hook_text = _clean(hook).upper() if uppercase else _clean(hook)
        if len(hook_text) > 50:
            hook_text = hook_text[:49].rsplit(" ", 1)[0].rstrip(" ,.-—") + "…"
        hook_tokens = hook_text.split()
        hook_groups = _split_cue_lines(hook_tokens, info, hook_size_eff,
                                       hook_safe_w, font_key=font)
        hook_lines = [" ".join(hook_tokens[i] for i in g) for g in hook_groups[:3]]
        eff_hook = _fit_fontsize(hook_lines, info, hook_size_eff, hook_safe_w,
                                 font_key=font, outline=8.0, spacing=0.5)
        hook_fs = f"\\fs{eff_hook}" if eff_hook < hook_size_eff else ""
        start, end = 0.15, min(clip_len - 0.1, max(1.8, min(4.2, clip_len * 0.3)))
        # Хук ставим с противоположной стороны от субтитров, тоже внутри
        # безопасной области площадки.
        from . import platforms

        if position == "top":
            hook_y = int(round((platforms.bottom_text_y(platform) - 20) * y_scale))
            hook_y = max(40, min(ph - 40, hook_y))
            hook_anchor = 2
        else:
            hook_y = int(round((platforms.top_text_y(platform) + int(top_reserve or 0)) * y_scale))
            hook_y = max(40, min(ph - 40, hook_y))
            hook_anchor = 8
        events.extend(_line_events(
            hook_lines, 1, "Hook", start, end, hook_anchor, pw // 2, hook_y,
            float(eff_hook) * 1.2, float(gap),
            f"\\fad(180,220){hook_fs}\\fscx104\\fscy104",
        ))

    # Короткие реплики + караоке-подсветка: текст не «мигает» на каждом слове,
    # а плавно закрашивается цветом акцента и висит ещё немного после речи.
    cue_chars = max(12, min(int(chars * 2 - 2), int(preset["max_chars"])))
    cues = _cues(local, max_chars=cue_chars, max_words=int(preset["max_words"]),
                 max_gap=float(preset["max_gap"]))

    timed: List[Any] = []
    for index, cue in enumerate(cues):
        if not cue:
            continue
        start = max(0.0, float(cue[0]["start"]))
        end = min(clip_len, max(float(cue[-1]["end"]) + float(preset["hold"]),
                                start + float(preset["min_cue"])))
        if index + 1 < len(cues) and cues[index + 1]:
            nxt = max(start + 0.3, float(cues[index + 1][0]["start"]) - 0.02)
            end = min(end, nxt)
        timed.append((cue, start, end))

    # Вставки рекламы: субтитры не должны висеть над рекламой даже с hold.
    if blackouts:
        clipped: List[Any] = []
        for cue, cue_start, cue_end in timed:
            pieces = [(cue_start, cue_end)]
            for b_start, b_end in blackouts:
                next_pieces = []
                for a, b in pieces:
                    if b <= b_start or a >= b_end:
                        next_pieces.append((a, b))
                        continue
                    if a < b_start:
                        next_pieces.append((a, min(b, b_start)))
                    if b > b_end:
                        next_pieces.append((max(a, b_end), b))
                pieces = next_pieces
            if pieces:
                clipped.append((cue, pieces[0][0], pieces[0][1]))
        timed = clipped

    fade_in, fade_out = preset["fade"]
    for cue, cue_start, cue_end in timed:
        if cue_end - cue_start < 0.35:
            continue
        tokens = [w["word"] for w in cue]
        # Перенос по словам в пределах безопасной ширины; слишком длинное слово
        # пропорционально сжимается через \fs, чтобы никогда не уходить за экран.
        line_groups = _split_cue_lines(tokens, info, size, sub_safe_w, font_key=font)
        line_texts = [" ".join(tokens[ti] for ti in g) for g in line_groups]
        eff_size = _fit_fontsize(line_texts, info, size, sub_safe_w, font_key=font)
        fs_tag = f"\\fs{eff_size}" if eff_size < size else ""

        # длительности \k: каждое слово подсвечивается ровно в свой момент
        karaoke: List[int] = []
        for wi, word in enumerate(cue):
            nxt = float(cue[wi + 1]["start"]) if wi + 1 < len(cue) else float(cue_end)
            duration = max(0.03, nxt - float(word["start"]))
            karaoke.append(max(1, int(round(duration * 100))))

        rendered: List[str] = []
        for group in line_groups:
            rendered.append(" ".join(
                f"{{\\k{karaoke[ti]}}}{tokens[ti]}" for ti in group
            ))
        tags = (f"\\fad({int(fade_in)},{int(fade_out)}){fs_tag}"
                f"\\fscx104\\fscy104\\t(0,170,\\fscx100\\fscy100)")
        events.extend(_line_events(
            rendered, 0, "Sub", cue_start, cue_end, anchor, pos_x, pos_y,
            float(eff_size) * 1.2, float(gap), tags,
        ))

    return header + "\n".join(events) + "\n"
