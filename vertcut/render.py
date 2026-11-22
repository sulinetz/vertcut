"""Рендер вертикальных клипов: кадрирование, фон, субтитры, звук."""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .config import ffmpeg
from . import custom_fonts
from .reframe import crop_expressions
from .timeline import offsets as timeline_offsets
from .utils import MediaError, probe, run, subprocess_kwargs

ASPECTS = {"9:16": (1080, 1920), "1:1": (1080, 1080), "16:9": (1920, 1080), "4:5": (1080, 1350)}

# Пресеты для стримов: игра на весь кадр плюс врезка с лицом.
STREAM_LAYOUTS = ("band", "band_top")
BAND_H = 640


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
    except Exception:
        text = ""
    found = next((name for name in preferred if name in text), None)
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
                split_ratio: float = 0.5, audio_track: Optional[int] = None) -> Dict[str, Any]:
    speed = max(1.0, min(1.25, float(speed or 1.0)))
    pitch = max(0.85, min(1.15, float(pitch or 1.0)))
    tilt = max(0.0, min(5.0, float(tilt or 0.0)))
    ratio = max(0.25, min(0.75, float(split_ratio or 0.5)))
    is_adhd = layout == "adhd"

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

    top_h = max(2, int(round(h * ratio / 2.0)) * 2)
    bot_h = h - top_h

    # Входы: 0 — источник, затем фон ADHD, затем музыка.
    bg_idx = 1 if (is_adhd and bg_path is not None) else None
    music_idx = None
    if music_path is not None:
        music_idx = 2 if bg_idx is not None else 1

    if is_adhd:
        top_sharpen = info["width"] < w * 0.75
        if mode == "auto" and crop_path:
            vg.append(_auto_chain(w, top_h, crop_path, top_sharpen, src=seq_src, out="[top]"))
        elif mode == "blur":
            vg.append(_bg_chain(w, top_h, focus_x, top_sharpen, src=seq_src, out="[top]"))
        else:
            vg.append(_crop_chain(w, top_h, focus_x, sharpen=top_sharpen, src=seq_src, out="[top]"))
        if bg_idx is not None:
            vg.append(
                f"[{bg_idx}:v]scale={w}:{bot_h}:force_original_aspect_ratio=increase,"
                f"crop={w}:{bot_h},setsar=1,format=yuv420p[bottom]"
            )
        else:
            vg.append(
                f"color=c=0x101116:s={w}x{bot_h}:r=30:d={out_dur + 1:.3f},"
                f"format=yuv420p[bottom]"
            )
        vg.append("[top][bottom]vstack=inputs=2[base]")
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
    if info["has_audio"]:
        if segs:
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

        if music_idx is not None:
            level = max(0.0, min(0.5, float(music_volume or 0.0)))
            end_fade = max(0.0, duration - 1.6)
            audio.append(
                f"[{music_idx}:a]volume={level:.3f},afade=t=in:st=0:d=1.2,"
                f"afade=t=out:st={end_fade:.3f}:d=1.6[m]"
            )
            audio.append("[a0][m]amix=inputs=2:duration=first:dropout_transition=0[aout]")
            audio_label = "[aout]"
        else:
            audio_label = "[a0]"
    elif music_idx is not None:
        # Немое видео: музыка становится единственной дорожкой, а не теряется.
        level = max(0.0, min(0.5, float(music_volume or 0.0)))
        end_fade = max(0.0, duration - 1.6)
        audio.append(
            f"[{music_idx}:a]volume={level:.3f},afade=t=in:st=0:d=1.2,"
            f"afade=t=out:st={end_fade:.3f}:d=1.6[aout]"
        )
        audio_label = "[aout]"

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
    cmd += video_args + ["-r", str(out_fps),
                         "-map_metadata", "-1", "-map_chapters", "-1",
                         "-movflags", "+faststart", "-shortest", str(out_path)]

    # -progress в cmd даёт машинно-читаемый прогресс: UI не «замирает» на минуту.
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            errors="replace", bufsize=1, **subprocess_kwargs())
    assert proc.stdout is not None and proc.stderr is not None

    tail: list = []
    killed = {"hit": False, "reason": ""}

    def _drain_stderr() -> None:
        for line in proc.stderr:  # type: ignore[union-attr]
            tail.append(line)
            if len(tail) > 40:
                tail.pop(0)

    reader = threading.Thread(target=_drain_stderr, daemon=True)
    reader.start()

    # Щедрый, но конечный предел: зависший ffmpeg не должен держать клип вечно.
    limit = max(180.0, max(src_dur, duration) * 8.0)

    def _watchdog() -> None:
        if proc.poll() is not None:
            return
        killed["hit"] = True
        killed["reason"] = f"нет прогресса больше {limit:.0f} с"
        try:
            proc.kill()
        except Exception:
            pass

    timer = threading.Timer(limit, _watchdog)
    timer.daemon = True
    timer.start()
    try:
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("out_time_us=") and on_progress:
                try:
                    done = int(line.split("=", 1)[1]) / 1_000_000
                except ValueError:
                    continue
                on_progress(round(min(0.99, done / duration), 3))
        proc.wait()
    finally:
        timer.cancel()
        reader.join(timeout=2)

    if killed["hit"]:
        out_path.unlink(missing_ok=True)
        raise MediaError(f"Рендер остановлен: {killed['reason']}. Попробуйте ещё раз.")
    fallback_used = False
    if hw and (proc.returncode != 0 or not out_path.exists()):
        # аппаратный энкодер не завёлся (нет GPU/драйвера) — повторяем на libx264.
        # Заменяем ровно те аргументы, что добавили, иначе срезается хвост команды.
        hw_error = "".join(tail)[-300:]
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
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, errors="replace", bufsize=1, **subprocess_kwargs())
        tail = []
        if proc.stderr is not None:
            for line in proc.stderr:
                tail.append(line)
                if len(tail) > 40:
                    tail.pop(0)
        proc.wait()
    if proc.returncode != 0 or not out_path.exists() or out_path.stat().st_size < 10000:
        raise MediaError("Не удалось отрендерить клип: " + "".join(tail)[-600:])

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


