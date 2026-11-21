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


def media_duration(path: Path) -> float:
    """Длительность любого медиа, включая аудио без видеодорожки."""
    proc = run([ffmpeg(), "-hide_banner", "-i", str(path)])
    m = _TIME_RE.search(proc.stderr or "")
    return _to_seconds(*m.groups()) if m else 0.0


def extract_audio(src: Path, dst: Path, sample_rate: int = 16000) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg(), "-y", "-v", "error", "-i", str(src), "-vn",
           "-ac", "1", "-ar", str(sample_rate), "-c:a", "pcm_s16le", str(dst)]
    proc = run(cmd)
    if proc.returncode != 0 or not dst.exists():
        raise MediaError(f"Не удалось извлечь аудиодорожку: {(proc.stderr or '')[-300:]}")
    return dst


def extract_asr_audio(src: Path, dst: Path, sample_rate: int = 16000) -> Path:
    """Аудио для распознавания речи: без гула, шипения и перепадов громкости.

    Распознавание ошибается в первую очередь на «грязном» звуке: низкочастотный
    гул, шипение и тихие реплики. Поэтому перед Whisper прогоняем:
    срез ниже 70 Гц и выше 7.8 кГц (речь живёт между ними), мягкое
    шумоподавление и выравнивание громкости по фразам.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    base = [ffmpeg(), "-y", "-v", "error", "-i", str(src), "-vn",
            "-ac", "1", "-ar", str(sample_rate)]
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


def ass_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    cs = int(round(seconds * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def parse_vtt(path: Path) -> List[Dict[str, Any]]:
    """Простой парсер WebVTT в сегменты с приблизительными таймингами слов."""
    raw = Path(path).read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"\n\s*\n", raw.replace("\r\n", "\n"))
    segs: List[Dict[str, Any]] = []
    ts = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[.,](\d{3})")
    for block in blocks:
        lines = [ln for ln in block.split("\n") if ln.strip() and not ln.startswith(("WEBVTT", "NOTE", "Kind:", "Language:"))]
        stamp = None
        text_lines = []
        for ln in lines:
            m = ts.search(ln)
            if m:
                g = list(map(int, m.groups()))
                stamp = (g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000,
                         g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000)
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
        words = [{"word": w, "start": stamp[0] + i * step, "end": stamp[0] + (i + 1) * step}
                 for i, w in enumerate(words_raw)]
        segs.append({"start": stamp[0], "end": stamp[1], "text": text, "words": words})
    # склейка дублей (автосубтитры YouTube дают «плывущие» строки)
    out: List[Dict[str, Any]] = []
    for s in segs:
        if out and s["text"] == out[-1]["text"]:
            out[-1]["end"] = s["end"]
            continue
        out.append(s)
    return out


# --- Субтитры ---------------------------------------------------------------

_SUB_STREAM_RE = re.compile(
    r"Stream #\d+:\d+(?:\(([a-z]{2,3})\))?.*?: Subtitle: ([a-zA-Z0-9_]+)")


def subtitle_streams(path: Path) -> List[Dict[str, Any]]:
    """Текстовые дорожки субтитров внутри файла (для .mkv и подобных)."""
    proc = run([ffmpeg(), "-hide_banner", "-i", str(path)])
    text = proc.stderr or ""
    out: List[Dict[str, Any]] = []
    for line in text.splitlines():
        m = _SUB_STREAM_RE.search(line)
        if not m:
            continue
        codec = m.group(2).lower()
        # bitmap-дорожки (pgs/dvdsub) не превратить в текст
        if codec in ("hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "xsub"):
            continue
        out.append({"index": len(out), "codec": codec, "language": m.group(1) or ""})
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
        lines = [ln for ln in block.split("\n") if ln.strip()]
        stamp = None
        text_lines: List[str] = []
        for ln in lines:
            m = _SRT_TIME.search(ln)
            if m:
                g = m.groups()
                stamp = (_stamp(*g[:4]), _stamp(*g[4:]))
            elif stamp and not ln.strip().isdigit():
                text_lines.append(ln)
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
