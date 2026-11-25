"""Рендер вертикальных клипов: кадрирование, фон, субтитры, звук."""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .config import (ADHD_SPLIT_BACKEND_MAX, ADHD_SPLIT_BACKEND_MIN,
                     ADHD_SPLIT_UI_MAX, ADHD_SPLIT_UI_MIN,
                     ffmpeg, ffmpeg_capabilities)
from . import custom_fonts
from .errors import Cancelled
from .reframe import crop_expressions
from .timeline import dub_pieces, offsets as timeline_offsets
from .utils import MediaError, probe, probe_audio, run, subprocess_kwargs

ASPECTS = {"9:16": (1080, 1920), "1:1": (1080, 1080), "16:9": (1920, 1080), "4:5": (1080, 1350)}

# Пресеты для стримов: игра на весь кадр плюс врезка с лицом.
STREAM_LAYOUTS = ("band", "band_top")
BAND_H = 640
ADHD_FILLS = ("cover", "contain")
ADHD_SPLIT_MIN = ADHD_SPLIT_UI_MIN
ADHD_SPLIT_MAX = ADHD_SPLIT_BACKEND_MAX


def split_geometry(width: int, height: int, ratio: float = 0.5) -> Dict[str, Any]:
    """Геометрия split-screen в пикселях кадра. Чистая функция без ffmpeg.

    `ratio` — доля верхней области (основное видео), 0.25–0.85. Высота
    округляется до чётного, как в фильтре vstack.
    """
    w = max(2, int(width))
    h = max(2, int(height))
    value = max(ADHD_SPLIT_BACKEND_MIN, min(ADHD_SPLIT_MAX, float(ratio or 0.5)))
    top_h = max(2, int(math.floor(h * value / 2.0 + 0.5)) * 2)
    top_h = min(top_h, h - 2)
    bottom_h = h - top_h
    return {
        "width": w,
        "height": h,
        "ratio": round(value, 4),
        "top_h": top_h,
        "bottom_h": bottom_h,
        "top": {"x": 0, "y": 0, "w": w, "h": top_h},
        "bottom": {"x": 0, "y": top_h, "w": w, "h": bottom_h},
    }


def _esc(path: Path) -> str:
    # экранирование для аргумента фильтра ffmpeg
    p = str(path).replace("\\", "/")
    p = p.replace(":", "\\:").replace("'", "\\'")
    return p


def _stream_chain(w: int, h: int, crop_path: Optional[Dict[str, Any]],
                  facecam: Dict[str, Any], layout: str, platform: str,
                  src: str = "[0:v]", out: str = "[base]") -> str:
    """Игра на весь кадр + врезка с лицом поверх (или полосой снизу)."""
    fx, fy = float(facecam["x"]), float(facecam["y"])
    fw, fh = int(facecam["w"]), int(facecam["h"])
    fx, fy = int(fx), int(fy)
    sharp = ",unsharp=5:5:0.8:5:5:0.0"

    if crop_path:
        x_expr, y_expr = crop_expressions(crop_path)
        cw = int(crop_path["crop_w"])
        ch = int(crop_path["crop_h"])
        base = (f"{src}crop={cw}:{ch}:x='{x_expr}':y='{y_expr}',"
                f"scale={w}:{h if layout not in ('band', 'band_top') else 1280}:flags=lanczos")
    else:
        base = f"{src}scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"

    # Крупное лицо полосой во всю ширину: снизу или сверху кадра.
    face = (f"{src}crop={fw}:{fh}:{fx}:{fy},"
            f"scale={w}:{BAND_H}:force_original_aspect_ratio=increase,"
            f"crop={w}:{BAND_H},setsar=1{sharp}[face]")
    if layout == "band_top":
        top = f"{base},pad={w}:{h}:0:{BAND_H}:black[top]"
        return f"{face};{top};[top][face]overlay=0:0{out}"
    top = f"{base},pad={w}:{h}:0:0:black[top]"
    return f"{face};{top};[top][face]overlay=0:{h - BAND_H}{out}"


def _bg_chain(w: int, h: int, focus_x: float = 0.5, sharpen: bool = False,
              src: str = "[0:v]", out: str = "[base]") -> str:
    sharp = ",unsharp=5:5:0.7:5:5:0.0" if sharpen else ""
    return (
        f"{src}split=2[bg][fg];"
        f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
        f"gblur=sigma=34:steps=2,eq=brightness=-0.12:saturation=0.8[bgb];"
        f"[fg]scale={w}:-2:flags=lanczos{sharp}[fgs];"
        f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2:shortest=1{out}"
    )


def _crop_chain(w: int, h: int, focus_x: float = 0.5, focus_y: float = 0.45,
                sharpen: bool = False, src: str = "[0:v]", out: str = "[base]") -> str:
    sharp = ",unsharp=5:5:0.7:5:5:0.0" if sharpen else ""
    return (
        f"{src}scale={w}:{h}:force_original_aspect_ratio=increase{sharp},"
        f"crop={w}:{h}:(iw-{w})*{focus_x:.3f}:(ih-{h})*{focus_y:.3f}{out}"
    )


def _auto_chain(w: int, h: int, crop_path: Dict[str, Any], sharpen: bool = False,
                src: str = "[0:v]", out: str = "[base]") -> str:
    """Заливка кадра с плавающим окном по лицам."""
    x_expr, y_expr = crop_expressions(crop_path)
    cw = int(crop_path["crop_w"])
    ch = int(crop_path["crop_h"])
    sharp = ",unsharp=5:5:0.7:5:5:0.0" if sharpen else ""
    return (
        f"{src}crop={cw}:{ch}:x='{x_expr}':y='{y_expr}',"
        f"scale={w}:{h}:flags=lanczos,setsar=1{sharp},format=yuv420p{out}"
    )


_HW_CACHE: Dict[str, Any] = {}

# Сколько секунд без единой строки прогресса считаем зависанием рендера.
DEFAULT_RENDER_STALL = 120.0


def _hw_works(encoder: str) -> bool:
    """Пробный энкод одного кадра: список энкодеров ещё не гарантирует железо."""
    try:
        proc = run([ffmpeg(), "-hide_banner", "-v", "error",
                    "-f", "lavfi", "-i", "color=c=black:s=320x240:r=30:d=0.2",
                    "-frames:v", "1", "-c:v", encoder, "-f", "null", "-"],
                   timeout=20)
    except Exception:  # noqa: BLE001
        return False
    return proc.returncode == 0


def hw_encoder() -> Optional[str]:
    """Аппаратный энкодер для быстрого рендера: videotoolbox / nvenc / qsv.

    Проверяем один раз и только если ffmpeg его действительно знает; при ошибке
    рендер сам откатится на libx264, поэтому «auto» безопасен.
    """
    if "value" in _HW_CACHE:
        return _HW_CACHE["value"]
    if os.environ.get("VERTCUT_HW_ENCODE", "auto").strip().lower() in ("0", "false", "no", "off"):
        _HW_CACHE["value"] = None
        return None
    preferred = {"darwin": ["h264_videotoolbox"], "win32": ["h264_nvenc", "h264_qsv"],
                 "linux": ["h264_nvenc", "h264_qsv", "h264_vaapi"]}.get(sys.platform, [])
    try:
        proc = run([ffmpeg(), "-hide_banner", "-encoders"])
        text = (proc.stdout or "") + (proc.stderr or "")
    except Exception:  # noqa: BLE001
        text = ""
    # Неудача тоже кешируется: пробный энкод не должен повторяться на каждом клипе.
    found = next((name for name in preferred if name in text and _hw_works(name)), None)
    _HW_CACHE["value"] = found
    return found


def _hw_args(encoder: str, crf: int) -> List[str]:
    if encoder == "h264_videotoolbox":
        return ["-c:v", encoder, "-b:v", "9M", "-maxrate", "14M", "-bufsize", "14M",
                "-profile:v", "high", "-pix_fmt", "yuv420p"]
    if encoder == "h264_nvenc":
        return ["-c:v", encoder, "-preset", "p5", "-rc", "vbr", "-cq", str(crf),
                "-b:v", "0", "-pix_fmt", "yuv420p"]
    if encoder == "h264_qsv":
        return ["-c:v", encoder, "-global_quality", str(crf), "-pix_fmt", "nv12"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
            "-profile:v", "high", "-pix_fmt", "yuv420p"]


def _measure_loudness(source: Path, start: float, duration: float,
                      audio_track: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Первый проход loudnorm: измеряем громкость фрагмента."""
    try:
        cmd = [ffmpeg(), "-hide_banner", "-nostats", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
               "-i", str(source)]
        if audio_track is not None:
            cmd += ["-map", f"0:a:{max(0, int(audio_track))}"]
        cmd += ["-af", "loudnorm=I=-14:TP=-1.5:LRA=11:print_format=json",
                "-f", "null", "-"]
        proc = subprocess.run(
            cmd,
            capture_output=True, text=True, errors="replace",
            timeout=max(30.0, duration * 2.5),
            **subprocess_kwargs(),
        )
        text = proc.stderr or ""
        start_idx = text.rfind("{")
        end_idx = text.rfind("}")
        if start_idx == -1 or end_idx <= start_idx:
            return None
        data = json.loads(text[start_idx:end_idx + 1])
        keys = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
        if not all(k in data for k in keys):
            return None
        values = []
        for key in keys:
            try:
                value = float(data[key])
            except (TypeError, ValueError):
                return None
            if value in (float("inf"), float("-inf")) or not math.isfinite(value):
                return None
            values.append(value)
        if not (-99.0 <= values[0] <= 0.0):
            return None
        return data
    except Exception:
        return None


def _atempo_chain(tempo: float) -> List[str]:
    """atempo не принимает значения вне 0.5..2.0 — разбиваем на шаги."""
    out: List[str] = []
    value = float(tempo)
    while value > 2.0 - 1e-9:
        out.append("atempo=2.0")
        value /= 2.0
    while value < 0.5 + 1e-9:
        out.append("atempo=0.5")
        value /= 0.5
    if abs(value - 1.0) > 1e-4:
        out.append(f"atempo={value:.5f}")
    return out


def _normalize_segments(segments: Optional[List[Any]], src_dur: float) -> Optional[List[Tuple[float, float]]]:
    if not segments:
        return None
    out: List[Tuple[float, float]] = []
    for item in segments:
        try:
            a = max(0.0, float(item[0]))
            b = min(src_dur, float(item[1]))
        except (TypeError, ValueError, IndexError):
            continue
        if b - a > 0.05:
            out.append((a, b))
    return out or None


def _dub_audio_filters(src: str, segments: List[Tuple[float, float]], offset: float,
                       available: float, sample_rate: int,
                       out: str = "[seq_a]") -> List[str]:
    """Звук дубляжа по тем же кускам, что и видео, с учётом сдвига.

    Положительный offset задерживает дорожку, отрицательный ускоряет; то, чего
    в файле не хватает (начало раньше нуля или файл короче), заменяется тишиной,
    чтобы звук не отставал от картинки после склеек.
    """
    rate = int(sample_rate or 48000)
    pieces = dub_pieces(segments, offset, available)
    if not pieces:
        total = max(0.05, sum(max(0.0, b - a) for a, b in segments))
        pieces = [{"audio": False, "duration": round(total, 3)}]
    filters: List[str] = []
    count = len(pieces)
    for i, piece in enumerate(pieces):
        label = out if count == 1 else f"[dp{i}]"
        if piece.get("audio"):
            filters.append(
                f"{src}atrim=start={float(piece['start']):.3f}:end={float(piece['end']):.3f},"
                f"asetpts=PTS-STARTPTS,aresample={rate},"
                f"aformat=sample_fmts=fltp:sample_rates={rate}:channel_layouts=stereo{label}"
            )
        else:
            filters.append(
                f"aevalsrc=0|0:s={rate}:d={max(0.03, float(piece['duration'])):.3f},"
                f"asetpts=PTS-STARTPTS,"
                f"aformat=sample_fmts=fltp:sample_rates={rate}:channel_layouts=stereo{label}"
            )
    if count > 1:
        joined = "".join(f"[dp{i}]" for i in range(count))
        filters.append(f"{joined}concat=n={count}:v=0:a=1{out}")
    return filters


def _run_ffmpeg(cmd: List[str], duration: float,
                on_progress: Optional[Callable[[float], None]] = None,
                is_cancelled: Optional[Callable[[], bool]] = None,
                stall: Optional[float] = None) -> Dict[str, Any]:
    """Один запуск ffmpeg: прогресс, дренаж stdout/stderr и watchdog.

    stdout обязателен: ffmpeg пишет туда `-progress pipe:1`. Если его не читать,
    труба заполняется и процесс встаёт навсегда (так зависал откат энкодера).
    Watchdog следит за отсутствием прогресса, а не за общим временем: долгий,
    но живой рендер не убивается.
    """
    if stall is None:
        try:
            stall = float(os.environ.get("VERTCUT_RENDER_STALL", DEFAULT_RENDER_STALL))
        except ValueError:
            stall = DEFAULT_RENDER_STALL
    stall = max(1.0, float(stall))

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, errors="replace", bufsize=1,
                            **subprocess_kwargs())
    tail: List[str] = []
    state = {"killed": "", "cancel": False, "last": time.monotonic()}
    stop = threading.Event()

    def drain_stderr() -> None:
        if proc.stderr is None:
            return
        for line in proc.stderr:
            tail.append(line)
            if len(tail) > 40:
                tail.pop(0)

    def watchdog() -> None:
        while not stop.wait(0.2):
            if proc.poll() is not None:
                return
            if time.monotonic() - state["last"] > stall:
                state["killed"] = f"нет прогресса больше {stall:.0f} с"
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass
                return

    reader = threading.Thread(target=drain_stderr, daemon=True)
    reader.start()
    pilot = threading.Thread(target=watchdog, daemon=True)
    pilot.start()
    returncode: Optional[int] = None
    try:
        if proc.stdout is not None:
            for line in proc.stdout:
                state["last"] = time.monotonic()
                if is_cancelled is not None and is_cancelled():
                    state["cancel"] = True
                    state["killed"] = state["killed"] or "отменено"
                    try:
                        proc.kill()
                    except Exception:  # noqa: BLE001
                        pass
                    break
                text = line.strip()
                if text.startswith("out_time_us=") and on_progress:
                    try:
                        done = int(text.split("=", 1)[1]) / 1_000_000
                    except ValueError:
                        continue
                    on_progress(round(min(0.99, done / max(0.001, duration)), 3))
        returncode = proc.wait()
    finally:
        stop.set()
        reader.join(timeout=2)
        pilot.join(timeout=2)
    code = returncode if returncode is not None else proc.poll()
    return {"returncode": code, "tail": "".join(tail),
            "killed": state["killed"], "cancelled": state["cancel"]}


def _amix_filter(normalize: bool) -> str:
    """Микс музыки с речью без просадки уровня.

    amix по умолчанию делит громкость на число входов; normalize=0 (ffmpeg 4.4+)
    это отключает. На старых сборках компенсируем weights и loudnorm после микса.
    """
    base = "amix=inputs=2:duration=first:dropout_transition=0"
    if normalize:
        return base + ":normalize=0"
    return base + ":weights='1 1',loudnorm=I=-14:TP=-1.5:LRA=11"


def render_clip(source: Path, clip_start: float, clip_end: float, out_path: Path,
                ass_path: Optional[Path] = None, aspect: str = "9:16",
                mode: str = "blur", focus_x: float = 0.5,
                on_progress: Optional[Callable[[float], None]] = None,
                crf: int = 21, preset: str = "veryfast",
                crop_path: Optional[Dict[str, Any]] = None,
                layout: str = "", facecam: Optional[Dict[str, Any]] = None,
                platform: str = "", fps: Optional[float] = None,
                look: str = "none", vignette: bool = False, grain: bool = False,
                zoom: int = 100, bitrate: int = 0,
                music_path: Optional[Path] = None,
                music_volume: float = 0.08,
                hflip: bool = False, tilt: float = 0.0,
                speed: float = 1.0, pitch: float = 1.0,
                segments: Optional[List[Any]] = None, cut_zoom: bool = False,
                bg_path: Optional[Path] = None, bg_start: float = 0.0,
                split_ratio: float = 0.5, audio_track: Optional[int] = None,
                external_audio: Optional[Path] = None, audio_offset: float = 0.0,
                external_audio_track: Optional[int] = None,
                is_cancelled: Optional[Callable[[], bool]] = None,
                adhd_top_fill: str = "cover",
                adhd_bottom_fill: str = "cover",
                adhd_top_scale: float = 1.0,
                adhd_top_offset_x: float = 0.0,
                adhd_top_offset_y: float = 0.0,
                adhd_bottom_scale: float = 1.0,
                adhd_bottom_offset_x: float = 0.0,
                adhd_bottom_offset_y: float = 0.0,
                adhd_bottom_speed: float = 1.0,
                adhd_bottom_volume: float = 0.0) -> Dict[str, Any]:
    if is_cancelled is not None and is_cancelled():
        raise Cancelled()
    speed = max(1.0, min(1.25, float(speed or 1.0)))
    pitch = max(0.85, min(1.15, float(pitch or 1.0)))
    tilt = max(0.0, min(5.0, float(tilt or 0.0)))
    ratio = max(ADHD_SPLIT_BACKEND_MIN, min(ADHD_SPLIT_MAX, float(split_ratio or 0.5)))
    is_adhd = layout == "adhd"
    top_fill = str(adhd_top_fill or "cover").strip().lower()
    if top_fill not in ADHD_FILLS:
        top_fill = "cover"
    bottom_fill = str(adhd_bottom_fill or "cover").strip().lower()
    if bottom_fill not in ADHD_FILLS:
        bottom_fill = "cover"
    top_scale = max(0.5, min(2.0, float(adhd_top_scale or 1.0)))
    bottom_scale = max(0.5, min(2.0, float(adhd_bottom_scale or 1.0)))
    top_dx = max(-0.5, min(0.5, float(adhd_top_offset_x or 0.0)))
    top_dy = max(-0.5, min(0.5, float(adhd_top_offset_y or 0.0)))
    bottom_dx = max(-0.5, min(0.5, float(adhd_bottom_offset_x or 0.0)))
    bottom_dy = max(-0.5, min(0.5, float(adhd_bottom_offset_y or 0.0)))
    bottom_speed = max(0.25, min(4.0, float(adhd_bottom_speed or 1.0)))
    bottom_level = max(0.0, min(0.5, float(adhd_bottom_volume or 0.0)))

    w, h = ASPECTS.get(aspect, ASPECTS["9:16"])
    if is_adhd or (layout in STREAM_LAYOUTS and facecam):
        w, h = ASPECTS["9:16"]

    src_dur = max(0.4, clip_end - clip_start)
    segs = _normalize_segments(segments, src_dur)
    out_dur = (sum(b - a for a, b in segs) if segs else src_dur) / speed
    out_dur = max(0.4, out_dur)
    duration = out_dur

    info = probe(source)
    if info["height"] >= 1000:
        crf = min(crf, 20)
        preset = "veryfast"

    sharpen = info["width"] < w * 0.75

    vg: List[str] = []
    if segs:
        seq_src = "[seq]"
        if len(segs) == 1:
            a, b = segs[0]
            vg.append(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[seq]")
        else:
            for i, (a, b) in enumerate(segs):
                vg.append(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v{i}]")
            joined = "".join(f"[v{i}]" for i in range(len(segs)))
            vg.append(f"{joined}concat=n={len(segs)}:v=1:a=0[seq]")
    else:
        seq_src = "[0:v]"

    top_h = split_geometry(w, h, ratio)["top_h"]
    bot_h = h - top_h

    # Входы: 0 — источник, затем фон ADHD, музыка и внешняя дорожка (дубляж).
    bg_idx = 1 if (is_adhd and bg_path is not None) else None
    next_idx = 2 if bg_idx is not None else 1
    music_idx = None
    if music_path is not None:
        music_idx = next_idx
        next_idx += 1

    dub_path: Optional[Path] = None
    dub_info: Optional[Dict[str, Any]] = None
    if external_audio is not None:
        candidate = Path(external_audio)
        if candidate.is_file():
            try:
                info_dub = probe_audio(candidate)
            except Exception:  # noqa: BLE001
                info_dub = None
            if info_dub and info_dub.get("has_audio"):
                dub_path = candidate
                dub_info = info_dub
    dub_track: Optional[int] = None
    if dub_path is not None:
        try:
            wanted = int(external_audio_track) if external_audio_track is not None else -1
        except (TypeError, ValueError):
            wanted = -1
        dub_streams = (dub_info or {}).get("audio_streams") or []
        if 0 <= wanted < len(dub_streams):
            dub_track = wanted
    dub_idx = None
    if dub_path is not None:
        dub_idx = next_idx
        next_idx += 1
    use_dub = dub_idx is not None
    bg_audio_ok = False
    if is_adhd and bg_idx is not None and bg_path is not None and bottom_level > 0:
        try:
            bg_audio_ok = bool(probe(bg_path).get("has_audio"))
        except Exception:  # noqa: BLE001
            bg_audio_ok = False

    if is_adhd:
        top_sharpen = info["width"] < w * 0.75
        top_label = "[top]"
        if top_fill == "contain":
            fit_w = max(2, int(round(w * top_scale / 2.0)) * 2)
            fit_h = max(2, int(round(top_h * top_scale / 2.0)) * 2)
            vg.append(f"{seq_src}scale={fit_w}:{fit_h}:force_original_aspect_ratio=decrease,"
                      f"setsar=1[topfit]")
            vg.append(f"color=c=black:s={w}x{top_h}:r=30:d={out_dur + 1:.3f}[topbg]")
            vg.append(
                f"[topbg][topfit]overlay=x=(W-w)/2+{top_dx * w:.1f}:"
                f"y=(H-h)/2+{top_dy * top_h:.1f}:shortest=1,format=yuv420p[top]"
            )
        else:
            if mode == "auto" and crop_path:
                vg.append(_auto_chain(w, top_h, crop_path, top_sharpen, src=seq_src, out="[top]"))
            elif mode == "blur":
                vg.append(_bg_chain(w, top_h, focus_x, top_sharpen, src=seq_src, out="[top]"))
            else:
                vg.append(_crop_chain(w, top_h, focus_x, sharpen=top_sharpen, src=seq_src, out="[top]"))
            if (abs(top_scale - 1.0) > 1e-4 or abs(top_dx) > 1e-4
                    or abs(top_dy) > 1e-4):
                scaled_w = w * top_scale
                scaled_h = top_h * top_scale
                margin_x = max(0.0, (scaled_w - w) / 2.0)
                margin_y = max(0.0, (scaled_h - top_h) / 2.0)
                shift_x = margin_x + max(-margin_x, min(margin_x, top_dx * w))
                shift_y = margin_y + max(-margin_y, min(margin_y, top_dy * top_h))
                vg.append(
                    f"[top]scale=iw*{top_scale:.4f}:ih*{top_scale:.4f},"
                    f"crop={w}:{top_h}:{shift_x:.1f}:{shift_y:.1f},setsar=1[top2]"
                )
                top_label = "[top2]"

        if bg_idx is not None:
            if bottom_fill == "contain":
                fit_w = max(2, int(round(w * bottom_scale / 2.0)) * 2)
                fit_h = max(2, int(round(bot_h * bottom_scale / 2.0)) * 2)
                vg.append(f"[{bg_idx}:v]scale={fit_w}:{fit_h}:"
                          f"force_original_aspect_ratio=decrease,setsar=1[botfit]")
                vg.append(f"color=c=black:s={w}x{bot_h}:r=30:d={out_dur + 1:.3f}[botbg]")
                vg.append(
                    f"[botbg][botfit]overlay=x=(W-w)/2+{bottom_dx * w:.1f}:"
                    f"y=(H-h)/2+{bottom_dy * bot_h:.1f}:shortest=1,"
                    f"format=yuv420p[bottom]"
                )
            elif (abs(bottom_scale - 1.0) <= 1e-4 and abs(bottom_dx) <= 1e-4
                    and abs(bottom_dy) <= 1e-4):
                # Прежний график: при нейтральных настройках команда не меняется.
                vg.append(
                    f"[{bg_idx}:v]scale={w}:{bot_h}:force_original_aspect_ratio=increase,"
                    f"crop={w}:{bot_h},setsar=1,format=yuv420p[bottom]"
                )
            else:
                fit_w = max(2, int(round(w * bottom_scale)))
                fit_h = max(2, int(round(bot_h * bottom_scale)))
                margin_x = max(0.0, (fit_w - w) / 2.0)
                margin_y = max(0.0, (fit_h - bot_h) / 2.0)
                shift_x = margin_x + max(-margin_x, min(margin_x, bottom_dx * w))
                shift_y = margin_y + max(-margin_y, min(margin_y, bottom_dy * bot_h))
                vg.append(
                    f"[{bg_idx}:v]scale={fit_w}:{fit_h}:force_original_aspect_ratio=increase,"
                    f"crop={w}:{bot_h}:{shift_x:.1f}:{shift_y:.1f},"
                    f"setsar=1,format=yuv420p[bottom]"
                )
        else:
            vg.append(
                f"color=c=0x101116:s={w}x{bot_h}:r=30:d={out_dur + 1:.3f},"
                f"format=yuv420p[bottom]"
            )

        bottom_label = "[bottom]"
        if abs(bottom_speed - 1.0) > 1e-4:
            vg.append(f"[bottom]setpts=PTS/{bottom_speed:.6f}[bottom2]")
            bottom_label = "[bottom2]"
        vg.append(f"{top_label}{bottom_label}vstack=inputs=2[base]")
    elif layout in STREAM_LAYOUTS and facecam:
        vg.append(_stream_chain(w, h, crop_path, facecam, layout, platform,
                                src=seq_src, out="[base]"))
    elif mode == "auto" and crop_path:
        sharpen = float(crop_path.get("crop_w", info["width"])) < w * 1.15
        vg.append(_auto_chain(w, h, crop_path, sharpen, src=seq_src, out="[base]"))
    elif mode == "blur":
        vg.append(_bg_chain(w, h, focus_x, sharpen, src=seq_src, out="[base]"))
    else:
        vg.append(_crop_chain(w, h, focus_x, sharpen=sharpen, src=seq_src, out="[base]"))

    current = "[base]"
    if abs(speed - 1.0) > 1e-4:
        vg.append(f"[base]setpts=PTS/{speed:.6f}[spd]")
        current = "[spd]"

    # Лёгкое чередование зума на склейках: режем уже собранный кадр по границам.
    if cut_zoom and segs and 1 < len(segs) <= 24:
        offs, total = timeline_offsets(segs)
        bounds = [o / speed for o in offs] + [total / speed]
        vg.append(f"{current}split={len(segs)}"
                  + "".join(f"[cz{i}]" for i in range(len(segs))))
        for i in range(len(segs)):
            trim = (f"trim=start={bounds[i]:.3f}:end={bounds[i + 1]:.3f},"
                    f"setpts=PTS-STARTPTS")
            if i % 2 == 1:
                vg.append(f"[cz{i}]{trim},scale=iw*1.06:ih*1.06,crop={w}:{h},setsar=1[zc{i}]")
            else:
                vg.append(f"[cz{i}]{trim},setsar=1[zc{i}]")
        vg.append("".join(f"[zc{i}]" for i in range(len(segs)))
                  + f"concat=n={len(segs)}:v=1:a=0[czv]")
        current = "[czv]"

    style: List[str] = []
    if hflip:
        style.append("hflip")
    if tilt > 0.05:
        # Поворот с запасом 12%: после обрезки чёрных углов не остаётся.
        angle = math.radians(tilt)
        style.append(
            f"scale=iw*1.12:ih*1.12,rotate={angle:.6f}:ow=iw:oh=ih:c=black,"
            f"crop={w}:{h}"
        )
    z = max(100, min(120, int(zoom or 100)))
    if z > 100:
        factor = z / 100.0
        style.append(f"scale=iw*{factor:.3f}:ih*{factor:.3f},crop={w}:{h}")
    looks = {
        "warm": "eq=saturation=1.10:gamma_r=1.04:gamma_b=0.96",
        "cool": "eq=saturation=1.06:gamma_b=1.05:gamma_r=0.96",
        "contrast": "eq=contrast=1.12:saturation=1.10",
        "cinematic": "eq=contrast=1.08:saturation=0.92:gamma=0.98",
        "soft": "eq=contrast=0.96:saturation=1.04:brightness=0.02",
    }
    if look in looks:
        style.append(looks[look])
    if vignette:
        style.append("vignette=PI/5")
    if grain:
        style.append("noise=alls=8:allf=t+u")
    prefix = current + (",".join(style) + "," if style else "")

    if ass_path is not None:
        vg.append(
            f"{prefix}ass=filename='{_esc(ass_path)}':fontsdir='{_esc(custom_fonts.libass_dir())}':alpha=1,"
            f"format=yuv420p[v]"
        )
    else:
        vg.append(f"{prefix}scale=in_range=auto:out_range=tv,format=yuv420p[v]")

    cmd = [ffmpeg(), "-y", "-hide_banner", "-v", "error", "-nostats",
           "-progress", "pipe:1",
           "-ss", f"{clip_start:.3f}", "-t", f"{src_dur:.3f}", "-i", str(source)]
    if bg_idx is not None and bg_path is not None:
        cmd += ["-stream_loop", "-1", "-ss", f"{max(0.0, float(bg_start)):.3f}",
                "-i", str(bg_path)]
    if music_idx is not None and music_path is not None:
        cmd += ["-stream_loop", "-1", "-i", str(music_path)]
    if dub_idx is not None and dub_path is not None:
        cmd += ["-i", str(dub_path)]

    source_rate = int(info.get("sample_rate") or 48000)
    audio_index: Optional[int] = None
    if audio_track is not None:
        try:
            audio_index = max(0, int(audio_track))
        except (TypeError, ValueError):
            audio_index = None
    streams = info.get("audio_streams") or []
    if audio_index is not None and streams and not (0 <= audio_index < len(streams)):
        audio_index = None
    audio_src = f"[0:a:{audio_index}]" if audio_index is not None else "[0:a]"
    if audio_index is not None and 0 <= audio_index < len(streams):
        rate = streams[audio_index].get("sample_rate")
        if rate:
            source_rate = int(rate)
    audio: List[str] = []
    audio_label: Optional[str] = None
    if info["has_audio"] or use_dub:
        if use_dub:
            dub_streams = (dub_info or {}).get("audio_streams") or []
            dub_src = f"[{dub_idx}:a:{dub_track}]" if dub_track is not None else f"[{dub_idx}:a]"
            if dub_track is not None and 0 <= dub_track < len(dub_streams):
                source_rate = int(dub_streams[dub_track].get("sample_rate") or source_rate)
            elif dub_info and dub_info.get("sample_rate"):
                source_rate = int(dub_info["sample_rate"])
            audio += _dub_audio_filters(dub_src,
                                        [(float(clip_start) + a, float(clip_start) + b)
                                         for a, b in (segs or [(0.0, src_dur)])],
                                        float(audio_offset or 0.0),
                                        float((dub_info or {}).get("duration") or 0.0),
                                        source_rate)
        elif segs:
            if len(segs) == 1:
                a, b = segs[0]
                audio.append(f"{audio_src}atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[seq_a]")
            else:
                for i, (a, b) in enumerate(segs):
                    audio.append(f"{audio_src}atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[ai{i}]")
                audio.append("".join(f"[ai{i}]" for i in range(len(segs)))
                             + f"concat=n={len(segs)}:v=0:a=1[seq_a]")
        else:
            audio.append(f"{audio_src}anull[seq_a]")

        afilters: List[str] = []
        if abs(pitch - 1.0) > 1e-4:
            afilters.append(
                f"asetrate={source_rate}*{pitch:.5f},aresample={source_rate}")
        afilters.extend(_atempo_chain(speed / pitch))

        measured = None
        if use_dub and dub_path is not None:
            dub_dur = float((dub_info or {}).get("duration") or 0.0)
            m_start = max(0.0, clip_start - float(audio_offset or 0.0))
            m_dur = min(src_dur, max(0.0, dub_dur - m_start))
            if m_dur > 0.2:
                measured = _measure_loudness(dub_path, m_start, m_dur, audio_track=dub_track)
        else:
            measured = _measure_loudness(source, clip_start, src_dur, audio_track=audio_index)
        if measured:
            afilters.append(
                "loudnorm=I=-14:TP=-1.5:LRA=11"
                f":measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
                f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
                f":offset={measured['target_offset']}:linear=true"
            )
        else:
            afilters.append("loudnorm=I=-14:TP=-1.5:LRA=11")
        fade_out = max(0.0, duration - 0.06)
        afilters.append(f"afade=t=in:st=0:d=0.03,afade=t=out:st={fade_out:.3f}:d=0.05")
        audio.append("[seq_a]" + ",".join(afilters) + "[a0]")

        base_audio = "[a0]"
        if bg_audio_ok and bg_idx is not None:
            bottom_chain = (f"[{bg_idx}:a]volume={bottom_level:.3f}"
                            + ("," + ",".join(_atempo_chain(bottom_speed))
                               if abs(bottom_speed - 1.0) > 1e-4 else "")
                            + ",afade=t=in:st=0:d=0.3[bga]")
            audio.append(bottom_chain)
            audio.append(base_audio + "[bga]"
                         + _amix_filter(bool(ffmpeg_capabilities().get("amix_normalize", True)))
                         + "[a0b]")
            base_audio = "[a0b]"

        if music_idx is not None:
            level = max(0.0, min(0.5, float(music_volume or 0.0)))
            end_fade = max(0.0, duration - 1.6)
            audio.append(
                f"[{music_idx}:a]volume={level:.3f},afade=t=in:st=0:d=1.2,"
                f"afade=t=out:st={end_fade:.3f}:d=1.6[m]"
            )
            audio.append(base_audio + "[m]"
                         + _amix_filter(bool(ffmpeg_capabilities().get("amix_normalize", True)))
                         + "[aout]")
            audio_label = "[aout]"
        else:
            audio_label = base_audio
    elif music_idx is not None or bg_audio_ok:
        # Немое видео: музыка и/или звук нижнего ролика становятся дорожкой.
        mix_base = ""
        if bg_audio_ok and bg_idx is not None:
            bottom_chain = (f"[{bg_idx}:a]volume={bottom_level:.3f}"
                            + ("," + ",".join(_atempo_chain(bottom_speed))
                               if abs(bottom_speed - 1.0) > 1e-4 else "")
                            + ",afade=t=in:st=0:d=0.3[a0]")
            audio.append(bottom_chain)
            mix_base = "[a0]"
        if music_idx is not None:
            level = max(0.0, min(0.5, float(music_volume or 0.0)))
            end_fade = max(0.0, duration - 1.6)
            if not mix_base:
                # Прежний график для немого видео с музыкой не меняем.
                audio.append(
                    f"[{music_idx}:a]volume={level:.3f},afade=t=in:st=0:d=1.2,"
                    f"afade=t=out:st={end_fade:.3f}:d=1.6[aout]"
                )
                audio_label = "[aout]"
            else:
                audio.append(
                    f"[{music_idx}:a]volume={level:.3f},afade=t=in:st=0:d=1.2,"
                    f"afade=t=out:st={end_fade:.3f}:d=1.6[m]"
                )
                audio.append(mix_base + "[m]"
                             + _amix_filter(bool(ffmpeg_capabilities().get("amix_normalize", True)))
                             + "[aout]")
                audio_label = "[aout]"
        else:
            audio_label = mix_base

    filter_complex = ";".join(vg + audio)
    cmd += ["-filter_complex", filter_complex, "-map", "[v]"]
    if audio_label is not None:
        cmd += ["-map", audio_label,
                "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"]
    else:
        cmd += ["-an"]

    hw = hw_encoder()
    video_args = _hw_args(hw, crf) if hw else ["-c:v", "libx264", "-preset", preset,
                                               "-crf", str(crf), "-profile:v", "high",
                                               "-pix_fmt", "yuv420p"]
    mbps = max(2, min(40, int(bitrate))) if bitrate else 0
    if mbps:
        video_args += ["-maxrate", f"{mbps}M", "-bufsize", f"{mbps * 2}M"]
    out_fps = 30.0
    if fps:
        out_fps = round(float(fps), 2)
    elif info.get("fps"):
        out_fps = round(float(info["fps"]), 2)
    cmd += video_args + ["-t", f"{duration:.3f}", "-r", str(out_fps),
                         "-map_metadata", "-1", "-map_chapters", "-1",
                         "-movflags", "+faststart", "-shortest", str(out_path)]

    result = _run_ffmpeg(cmd, duration, on_progress, is_cancelled)
    if result["cancelled"]:
        out_path.unlink(missing_ok=True)
        raise Cancelled()
    if result["killed"]:
        out_path.unlink(missing_ok=True)
        raise MediaError(f"Рендер остановлен: {result['killed']}. Попробуйте ещё раз.")
    fallback_used = False
    if hw and (result["returncode"] != 0 or not out_path.exists()):
        # аппаратный энкодер не завёлся (нет GPU/драйвера) — повторяем на libx264.
        # Заменяем ровно те аргументы, что добавили, иначе срезается хвост команды.
        hw_error = (result["tail"] or "")[-300:]
        print(f"[render] {hw} не сработал, повтор на libx264: {hw_error}",
              file=sys.stderr, flush=True)
        fallback_used = True
        fallback = ["-c:v", "libx264", "-preset", preset, "-crf", str(crf),
                    "-profile:v", "high", "-pix_fmt", "yuv420p"]
        if mbps:
            fallback += ["-maxrate", f"{mbps}M", "-bufsize", f"{mbps * 2}M"]
        idx = cmd.index("-c:v")
        cmd[idx:idx + len(video_args)] = fallback
        out_path.unlink(missing_ok=True)
        result = _run_ffmpeg(cmd, duration, on_progress, is_cancelled)
        if result["cancelled"]:
            out_path.unlink(missing_ok=True)
            raise Cancelled()
        if result["killed"]:
            out_path.unlink(missing_ok=True)
            raise MediaError(f"Рендер остановлен: {result['killed']}. Попробуйте ещё раз.")
    if result["returncode"] != 0 or not out_path.exists() or out_path.stat().st_size < 10000:
        raise MediaError("Не удалось отрендерить клип: " + (result["tail"] or "")[-600:])

    if on_progress:
        on_progress(1.0)
    return {"path": out_path, "duration": round(duration, 2), "width": w, "height": h,
            "encoder": "libx264" if (not hw or fallback_used) else hw,
            "fallback": fallback_used}


def make_preview(clip_path: Path, out_path: Path, width: int = 540) -> Optional[Path]:
    """Лёгкая копия для быстрого предпросмотра в интерфейсе."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg(), "-y", "-v", "error", "-i", str(clip_path),
           "-vf", f"scale={width}:-2", "-c:v", "libx264", "-preset", "veryfast",
           "-crf", "30", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart",
           str(out_path)]
    proc = run(cmd)
    return out_path if proc.returncode == 0 and out_path.exists() else None


def make_thumb(clip_path: Path, out_path: Path, at: float = 0.6) -> Optional[Path]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg(), "-y", "-v", "error", "-ss", f"{at:.2f}", "-i", str(clip_path),
           "-frames:v", "1", "-vf", "scale=540:-2", "-q:v", "3", str(out_path)]
    proc = run(cmd)
    return out_path if proc.returncode == 0 and out_path.exists() else None


