"""Мелкие утилиты: запуск ffmpeg, зондирование медиа, работа с временем."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import ffmpeg

# На Windows дочерние ffmpeg/yt-dlp не должны открывать чёрные консольные окна.
NO_WINDOW = 0x08000000 if sys.platform.startswith("win") else 0


def subprocess_kwargs() -> Dict[str, Any]:
    return {"creationflags": NO_WINDOW} if NO_WINDOW else {}


class MediaError(Exception):
    pass


def run(cmd: List[str], timeout: Optional[int] = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          errors="replace", **subprocess_kwargs())


_TIME_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def _to_seconds(h: str, m: str, s: str) -> float:
    return int(h) * 3600 + int(m) * 60 + float(s)


def probe(path: Path) -> Dict[str, Any]:
    """Достаёт длительность, размеры, fps и наличие звука из вывода ffmpeg."""
    proc = run([ffmpeg(), "-hide_banner", "-i", str(path)])
    text = proc.stderr or ""
    info: Dict[str, Any] = {"duration": 0.0, "width": 0, "height": 0, "fps": 30.0, "has_audio": False}
    m = _TIME_RE.search(text)
    if m:
        info["duration"] = _to_seconds(*m.groups())

    vm = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", text)
    if vm:
        info["width"], info["height"] = int(vm.group(1)), int(vm.group(2))
    fm = re.search(r"(\d+(?:\.\d+)?)\s+fps", text)
    if fm:
        info["fps"] = float(fm.group(1))
    info["has_audio"] = "Audio:" in text
    # Частота дискретизации нужна сдвигу питча: asetrate считается от неё,
    # а не от жёстких 48 кГц — иначе клип с 44.1 кГц уезжает по длительности.
    streams = parse_audio_streams(text)
    info["audio_streams"] = streams
    default_audio = next((s for s in streams if s.get("default")), streams[0] if streams else None)
    if default_audio and default_audio.get("sample_rate"):
        info["sample_rate"] = int(default_audio["sample_rate"])
    else:
        am = re.search(r"Audio:[^\n]*?,\s*(\d{4,6})\s*Hz", text)
        info["sample_rate"] = int(am.group(1)) if am else 48000

    # Поворот из метаданных (вертикальные видео с телефона)
    rm = re.search(r"rotation of (-?\d+(?:\.\d+)?) degrees", text)
    if rm:
        angle = abs(float(rm.group(1))) % 360
        if 75 <= angle <= 105:
            info["width"], info["height"] = info["height"], info["width"]
            info["rotation"] = 90
    if info["width"] == 0 or info["height"] == 0:
        raise MediaError("Не удалось прочитать видеофайл (повреждён или это не видео).")
    return info


def probe_audio(path: Path) -> Dict[str, Any]:
    """Метаданные звука: подходит и для аудиофайла, и для контейнера с дубляжом.

    `probe` требует видеодорожку, поэтому для внешней звуковой дорожки нужен
    отдельный разбор — видео в ней может не быть вовсе.
    """
    proc = run([ffmpeg(), "-hide_banner", "-i", str(path)])
    text = proc.stderr or ""
    m = _TIME_RE.search(text)
    streams = parse_audio_streams(text)
    default_audio = next((s for s in streams if s.get("default")), streams[0] if streams else None)
    return {
        "duration": _to_seconds(*m.groups()) if m else 0.0,
        "has_audio": bool(streams),
        "has_video": "Video:" in text,
        "audio_streams": streams,
        "sample_rate": int((default_audio or {}).get("sample_rate") or 48000),
    }


def audio_track_rate(streams: List[Dict[str, Any]], index: Optional[int],
                     fallback: int = 48000) -> int:
    """Частота выбранной дорожки: питч нельзя считать от чужой частоты."""
    if index is None or not (0 <= int(index) < len(streams or [])):
        return int(fallback or 48000)
    return int(streams[int(index)].get("sample_rate") or fallback or 48000)


_AUDIO_STREAM_RE = re.compile(
    r"Stream #0:(\d+)(?:\[[^\]]+\])?(?:\(([^)]+)\))?: Audio: ([^,\n]+)"
    r"(?:,\s*(\d+)\s*Hz)?(?:,\s*([^,\n]+))?(?:,\s*([^,\n]+))?"
)


def parse_audio_streams(text: str) -> List[Dict[str, Any]]:
    """Список аудиодорожек из вывода `ffmpeg -i` (язык, кодек, частота)."""
    out: List[Dict[str, Any]] = []
    for line in (text or "").splitlines():
        match = _AUDIO_STREAM_RE.search(line)
        if not match:
            continue
        channels = (match.group(5) or "").strip()
        if channels and not re.search(r"mono|stereo|channels|\d\.\d", channels):
            channels = ""
        out.append({
            "index": len(out),
            "stream": int(match.group(1)),
            "language": (match.group(2) or "").strip().lower(),
            "codec": match.group(3).strip(),
            "sample_rate": int(match.group(4)) if match.group(4) else None,
            "channels": channels,
            "default": "(default)" in line,
        })
    if out and not any(item["default"] for item in out):
        out[0]["default"] = True
    return out


def audio_streams(path: Path) -> List[Dict[str, Any]]:
    proc = run([ffmpeg(), "-hide_banner", "-i", str(path)])
    return parse_audio_streams(proc.stderr or "")


def media_duration(path: Path) -> float:
    """Длительность любого медиа, включая аудио без видеодорожки."""
    proc = run([ffmpeg(), "-hide_banner", "-i", str(path)])
    m = _TIME_RE.search(proc.stderr or "")
    return _to_seconds(*m.groups()) if m else 0.0


def extract_audio(src: Path, dst: Path, sample_rate: int = 16000,
                  audio_track: Optional[int] = None) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg(), "-y", "-v", "error", "-i", str(src)]
    if audio_track is not None:
        cmd += ["-map", f"0:a:{max(0, int(audio_track))}"]
    cmd += ["-vn", "-ac", "1", "-ar", str(sample_rate), "-c:a", "pcm_s16le", str(dst)]
    proc = run(cmd)
    if proc.returncode != 0 or not dst.exists():
        raise MediaError(f"Не удалось извлечь аудиодорожку: {(proc.stderr or '')[-300:]}")
    return dst


def extract_asr_audio(src: Path, dst: Path, sample_rate: int = 16000,
                      audio_track: Optional[int] = None) -> Path:
    """Аудио для распознавания речи: без гула, шипения и перепадов громкости.

    Распознавание ошибается в первую очередь на «грязном» звуке: низкочастотный
    гул, шипение и тихие реплики. Поэтому перед Whisper прогоняем:
    срез ниже 70 Гц и выше 7.8 кГц (речь живёт между ними), мягкое
    шумоподавление и выравнивание громкости по фразам.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    base = [ffmpeg(), "-y", "-v", "error", "-i", str(src)]
    if audio_track is not None:
        base += ["-map", f"0:a:{max(0, int(audio_track))}"]
    base += ["-vn", "-ac", "1", "-ar", str(sample_rate)]
    filters = "highpass=f=70,lowpass=f=7800,afftdn=nr=10:nf=-40,dynaudnorm=f=200:g=10"
    proc = run(base + ["-af", filters, "-c:a", "pcm_s16le", str(dst)])
    if proc.returncode != 0 or not dst.exists():
        # старые сборки ffmpeg без afftdn/dynaudnorm — хотя бы срезы и моно
        proc = run(base + ["-af", "highpass=f=70,lowpass=f=7800",
                           "-c:a", "pcm_s16le", str(dst)])
    if proc.returncode != 0 or not dst.exists():
        proc = run(base + ["-c:a", "pcm_s16le", str(dst)])
    if proc.returncode != 0 or not dst.exists():
        raise MediaError(f"Не удалось извлечь аудиодорожку: {(proc.stderr or '')[-300:]}")
    return dst


def read_audio_mono(src: Path, sample_rate: int = 16000) -> Any:
    """Возвращает numpy-массив float32 [-1, 1] с аудио."""
    import numpy as np

    cmd = [ffmpeg(), "-v", "error", "-i", str(src), "-vn", "-ac", "1",
           "-ar", str(sample_rate), "-f", "s16le", "-"]
    proc = subprocess.run(cmd, capture_output=True, **subprocess_kwargs())
    if proc.returncode != 0 or not proc.stdout:
        raise MediaError("Не удалось прочитать аудио.")
    return np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def fmt_ts(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    m, s = divmod(seconds, 60)
    h, m = divmod(int(m), 60)
    if h:
        return f"{h}:{m:02d}:{s:04.1f}"
    return f"{m}:{s:04.1f}"


_WIN_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_filename(text: str, fallback: str = "clip", max_len: int = 80) -> str:
    """Имя файла из названия клипа: без запрещённых символов и с запасом."""
    name = _INVALID_FILENAME.sub(" ", str(text or ""))
    name = re.sub(r"\s+", " ", name).strip(" .")
    if name.lower().endswith(".mp4"):
        name = name[:-4].rstrip(" .")
    if not name:
        name = fallback
    if name.split(".")[0].upper() in _WIN_RESERVED:
        name = "_" + name
    if len(name) > max_len:
        name = name[:max_len].rstrip(" .")
        if " " in name:
            name = name[:name.rfind(" ")].rstrip(" .")
    return name or fallback


def ordered_clips(clips: List[Dict[str, Any]], order: str = "chrono") -> List[Dict[str, Any]]:
    """Порядок для экспорта: хронология источника или лучшие оценки."""
    if order == "score":
        return sorted(
            clips,
            key=lambda c: (-float(c.get("score") or 0.0),
                           float(c.get("start") or 0.0),
                           int(c.get("idx") or 0)),
        )
    return sorted(
        clips,
        key=lambda c: (float(c.get("start") or 0.0),
                       float(c.get("end") or 0.0),
                       int(c.get("idx") or 0)),
    )


def named_exports(clips: List[Dict[str, Any]], order: str = "chrono") -> List[tuple]:
    """Пары (клип, имя файла) с хронологическим/рейтинговым префиксом."""
    ordered = ordered_clips(clips, order)
    width = max(2, len(str(len(ordered))))
    used: set = set()
    out: List[tuple] = []
    for position, clip in enumerate(ordered, 1):
        title = safe_filename(clip.get("title") or clip.get("hook") or "clip")
        stem = f"{position:0{width}d} — {title}"
        name = f"{stem}.mp4"
        counter = 2
        while name.casefold() in used:
            name = f"{stem} ({counter}).mp4"
            counter += 1
        used.add(name.casefold())
        out.append((clip, name))
    return out


def group_sibling_files(folder: Path, video: Path) -> List[Dict[str, Any]]:
    """Файлы-спутники одного видео: 1.avi + 1.srt + 1.mka + 1.ru.srt.

    Сравниваем по основе имени: точное совпадение или «основа.язык».
    Возвращает список {path, name, kind, suffix}, kind = subtitles/audio/video.
    """
    folder = Path(folder)
    video = Path(video)
    stem = video.stem.lower()
    subtitle_suffixes = {".srt", ".ass", ".ssa", ".vtt"}
    audio_suffixes = {".mka", ".m4a", ".mp3", ".wav", ".ogg", ".flac", ".opus",
                      ".aac", ".ac3", ".eac3", ".dts"}
    video_suffixes = {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi", ".ts"}
    out: List[Dict[str, Any]] = []
    try:
        entries = sorted(folder.iterdir())
    except OSError:
        return out
    for path in entries:
        if not path.is_file() or path.resolve() == video.resolve():
            continue
        name_stem = path.stem.lower()
        if not (name_stem == stem or name_stem.startswith(stem + ".")):
            continue
        suffix = path.suffix.lower()
        if suffix in subtitle_suffixes:
            kind = "subtitles"
        elif suffix in audio_suffixes:
            kind = "audio"
        elif suffix in video_suffixes:
            kind = "video"
        else:
            continue
        out.append({"path": str(path), "name": path.name, "kind": kind, "suffix": suffix})
    return out


def ass_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    cs = int(round(seconds * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def parse_vtt(path: Path) -> List[Dict[str, Any]]:
    """Парсер WebVTT: понимает и HH:MM:SS.mmm, и MM:SS.mmm.

    Автосубтитры YouTube «плывут»: каждая следующая реплика повторяет
    предыдущую строку и добавляет новую. Такие реплики схлопываем.
    """
    raw = Path(path).read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"\n\s*\n", raw.replace("\r\n", "\n"))
    ts = re.compile(r"(?:(\d{1,2}):)?(\d{2}):(\d{2})[.,](\d{3})")
    segs: List[Dict[str, Any]] = []

    def stamp_of(text: str) -> Optional[float]:
        m = ts.search(text or "")
        if not m:
            return None
        hours = int(m.group(1) or 0)
        return hours * 3600 + int(m.group(2)) * 60 + int(m.group(3)) + int(m.group(4)) / 1000

    for block in blocks:
        lines = [ln for ln in block.split("\n")
                 if ln.strip() and not ln.startswith(("WEBVTT", "NOTE", "Kind:", "Language:"))]
        stamp = None
        text_lines = []
        for ln in lines:
            if "-->" in ln:
                left, right = ln.split("-->", 1)
                start, end = stamp_of(left), stamp_of(right)
                if start is not None and end is not None and end > start:
                    stamp = (start, end)
            elif stamp:
                text_lines.append(re.sub(r"<[^>]+>", "", ln).strip())
        if not stamp or not text_lines:
            continue
        text = " ".join(text_lines).strip()
        words_raw = text.split()
        if not words_raw:
            continue
        span = max(0.05, stamp[1] - stamp[0])
        step = span / len(words_raw)
        words = [{"word": w, "start": round(stamp[0] + i * step, 3),
                  "end": round(stamp[0] + (i + 1) * step, 3)}
                 for i, w in enumerate(words_raw)]
        seg = {"start": stamp[0], "end": stamp[1], "text": text, "words": words}
        if segs and _merge_rolling(segs[-1], seg):
            continue
        segs.append(seg)
    return segs


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def _merge_rolling(prev: Dict[str, Any], seg: Dict[str, Any]) -> bool:
    """Схлопывает «плывущую» реплику автосубтитров в предыдущую.

    Новая реплика обычно содержит предыдущую строку целиком и добавляет
    следующую: берём более полный текст, но оставляем раннее начало.
    """
    a, b = _norm_text(prev.get("text")), _norm_text(seg.get("text"))
    if not a or not b:
        return False
    if a == b:
        prev["end"] = max(float(prev["end"]), float(seg["end"]))
        return True
    if b.startswith(a):
        start = min(float(prev["start"]), float(seg["start"]))
        prev["text"] = seg["text"]
        prev["words"] = list(seg.get("words") or [])
        prev["start"] = start
        prev["end"] = max(float(prev["end"]), float(seg["end"]))
        return True
    if a.endswith(b):
        prev["end"] = max(float(prev["end"]), float(seg["end"]))
        return True
    return False


# --- Субтитры ---------------------------------------------------------------

_SUB_STREAM_RE = re.compile(
    r"Stream #\d+:\d+(?:\[[^\]]+\])?(?:\(([a-z]{2,3})\))?(?:\[[^\]]+\])?"
    r".*?: Subtitle: ([a-zA-Z0-9_]+)")


def subtitle_streams(path: Path) -> List[Dict[str, Any]]:
    """Текстовые дорожки субтитров внутри файла (для .mkv и подобных).

    index — номер именно субтитровой дорожки для `-map 0:s:N`: ffmpeg считает
    все субтитры, включая картинные, поэтому счётчик общий, а текстовые
    возвращаются отдельно.
    """
    proc = run([ffmpeg(), "-hide_banner", "-i", str(path)])
    text = proc.stderr or ""
    out: List[Dict[str, Any]] = []
    position = 0
    for line in text.splitlines():
        m = _SUB_STREAM_RE.search(line)
        if not m:
            continue
        codec = m.group(2).lower()
        index = position
        position += 1
        # bitmap-дорожки (pgs/dvdsub) не превратить в текст
        if codec in ("hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "xsub"):
            continue
        out.append({"index": index, "codec": codec, "language": m.group(1) or ""})
    return out


def extract_subtitles(path: Path, dst: Path, index: int = 0) -> Optional[Path]:
    """Достаёт текстовую дорожку в SRT. Возвращает путь или None."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg(), "-y", "-v", "error", "-i", str(path),
           "-map", f"0:s:{index}", "-c:s", "srt", str(dst)]
    proc = run(cmd)
    if proc.returncode != 0 or not dst.exists() or dst.stat().st_size < 8:
        dst.unlink(missing_ok=True)
        return None
    return dst


_SRT_TIME = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})")
_ASS_TIME = re.compile(r"(\d+):(\d{2}):(\d{2})\.(\d{2})")


def _stamp(h: str, m: str, s: str, frac: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(frac.ljust(3, "0")[:3]) / 1000.0


def _words_from_text(text: str, start: float, end: float) -> List[Dict[str, Any]]:
    tokens = [w for w in text.split() if w]
    if not tokens:
        return []
    span = max(0.05, end - start)
    step = span / len(tokens)
    return [{"word": tok, "start": round(start + i * step, 3),
             "end": round(start + (i + 1) * step, 3)} for i, tok in enumerate(tokens)]


def _segments_from_cues(cues: List[tuple], merge: bool = True) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for start, end, text in cues:
        text = re.sub(r"<[^>]+>", "", text).strip()
        if not text or end <= start:
            continue
        words = _words_from_text(text, start, end)
        if not words:
            continue
        if merge and out and text == out[-1]["text"]:
            out[-1]["end"] = round(max(out[-1]["end"], end), 3)
            continue
        out.append({"start": round(start, 3), "end": round(end, 3),
                    "text": text, "words": words})
    return out


def parse_srt(path: Path) -> List[Dict[str, Any]]:
    raw = Path(path).read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
    cues: List[tuple] = []
    for block in re.split(r"\n\s*\n", raw):
        lines = block.split("\n")
        stamp = None
        text_lines: List[str] = []
        for ln in lines:
            m = _SRT_TIME.search(ln)
            if m:
                g = m.groups()
                stamp = (_stamp(*g[:4]), _stamp(*g[4:]))
                continue
            if stamp is None:
                # до таймкода идёт только номер реплики — его и пропускаем
                continue
            if ln.strip():
                text_lines.append(ln.strip())
        if stamp and text_lines:
            cues.append((stamp[0], stamp[1], " ".join(text_lines)))
    return _segments_from_cues(cues)


def parse_ass(path: Path) -> List[Dict[str, Any]]:
    raw = Path(path).read_text(encoding="utf-8", errors="replace")
    cues: List[tuple] = []
    for line in raw.splitlines():
        if not line.lower().startswith("dialogue:"):
            continue
        parts = line.split(",", 9)
        if len(parts) < 10:
            continue
        m1 = _ASS_TIME.match(parts[1].strip())
        m2 = _ASS_TIME.match(parts[2].strip())
        if not m1 or not m2:
            continue
        start = int(m1.group(1)) * 3600 + int(m1.group(2)) * 60 + int(m1.group(3)) + int(m1.group(4)) / 100
        end = int(m2.group(1)) * 3600 + int(m2.group(2)) * 60 + int(m2.group(3)) + int(m2.group(4)) / 100
        text = re.sub(r"\{[^}]*\}", "", parts[9]).replace("\\N", " ").replace("\\n", " ")
        text = text.replace("\\h", " ")
        cues.append((start, end, text))
    cues.sort(key=lambda c: c[0])
    return _segments_from_cues(cues)


def parse_subtitles(path: Path) -> List[Dict[str, Any]]:
    """Читает .srt, .ass/.ssa или .vtt и возвращает сегменты со словами."""
    suffix = Path(path).suffix.lower()
    if suffix in (".ass", ".ssa"):
        return parse_ass(path)
    if suffix == ".vtt":
        return parse_vtt(path)
    if suffix == ".srt":
        return parse_srt(path)
    # неизвестное расширение — пробуем по содержимому
    head = Path(path).read_text(encoding="utf-8", errors="replace")[:400].lower()
    if "[script info]" in head or "dialogue:" in head:
        return parse_ass(path)
    if "webvtt" in head:
        return parse_vtt(path)
    return parse_srt(path)
