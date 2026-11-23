"""Оркестрация: скачивание → распознавание → поиск моментов → рендер клипов."""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import (analyze, db, downloader, platforms, reframe, render, subtitles,
               timeline, transcribe, utils)
from .errors import Cancelled
from .config import PROJECTS_DIR

DEFAULT_OPTIONS: Dict[str, Any] = {
    "count": 10,
    "min_dur": 15,
    "max_dur": 60,
    "target_dur": 32,
    "language": "auto",
    "aspect": "9:16",
    "mode": "auto",
    "subtitles": True,
    "accent": "yellow",
    "uppercase": True,
    "show_hook": True,
    "cookies_browser": "",
    "sub_size": 118,
    "sub_font": "montserrat",
    "sub_position": "bottom",
    "sub_offset": 0,
    "sub_speed": "calm",
    "line_gap": 0,
    "keep_fps": True,
    "export_subs": False,
    "look": "none",
    "vignette": False,
    "grain": False,
    "zoom": 100,
    "bitrate": 0,
    "music_volume": 8,
    "hflip": False,
    "tilt": 0.0,
    "speed": 1.0,
    "pitch": 1.0,
    "jump_cuts": False,
    "cut_zoom": False,
    "bg_video": "random",
    "split_ratio": 0.5,
    "platform": platforms.DEFAULT_PLATFORM,
    "layout": "",
    "select": "smart",
    "subtitle_source": "auto",
    "max_height": 1080,
    "segments": False,
    "force_hd": False,
    "audio_track": -1,
    "external_audio": False,
    "external_audio_track": -1,
    "audio_offset": 0.0,
    "export_order": "chrono",
}


def normalize_options(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    opts = dict(DEFAULT_OPTIONS)
    if raw:
        for key, value in raw.items():
            if value is not None:
                opts[key] = value
    try:
        opts["count"] = int(opts["count"])
    except Exception:
        opts["count"] = 10
    opts["count"] = max(0, min(200, opts["count"]))
    try:
        opts["min_dur"] = max(8, min(120, int(opts["min_dur"])))
        opts["max_dur"] = max(opts["min_dur"] + 5, min(180, int(opts["max_dur"])))
        opts["target_dur"] = max(opts["min_dur"], min(opts["max_dur"], int(opts["target_dur"])))
    except Exception:
        opts.update({"min_dur": 15, "max_dur": 60, "target_dur": 32})
    if opts["aspect"] not in render.ASPECTS:
        opts["aspect"] = "9:16"
    if opts["mode"] not in ("auto", "blur", "crop"):
        opts["mode"] = "auto"
    if opts["accent"] not in subtitles.ACCENTS:
        opts["accent"] = "yellow"
    try:
        size = int(opts.get("sub_size", 118))
        if size < 70:
            size = 118
        opts["sub_size"] = max(70, min(180, size))
    except Exception:
        opts["sub_size"] = 118
    if not subtitles.font_exists(opts.get("sub_font") or ""):
        opts["sub_font"] = "montserrat"
    if opts.get("sub_position") not in subtitles.POSITIONS:
        opts["sub_position"] = "middle" if opts.get("layout") == "adhd" else "bottom"
    if (opts.get("layout") == "adhd" and (raw or {}).get("sub_position") is None
            and (raw or {}).get("layout") == "adhd"):
        opts["sub_position"] = "middle"
    if opts.get("sub_speed") not in subtitles.SPEEDS:
        opts["sub_speed"] = "calm"
    opts["keep_fps"] = bool(opts.get("keep_fps", True))
    opts["export_subs"] = bool(opts.get("export_subs", False))
    if opts.get("look") not in ("none", "warm", "cool", "contrast", "cinematic", "soft"):
        opts["look"] = "none"
    opts["vignette"] = bool(opts.get("vignette", False))
    opts["grain"] = bool(opts.get("grain", False))
    try:
        opts["zoom"] = max(100, min(120, int(opts.get("zoom", 100))))
    except (TypeError, ValueError):
        opts["zoom"] = 100
    try:
        opts["bitrate"] = max(0, min(40, int(opts.get("bitrate", 0))))
    except (TypeError, ValueError):
        opts["bitrate"] = 0
    try:
        opts["music_volume"] = max(0, min(50, int(opts.get("music_volume", 8))))
    except (TypeError, ValueError):
        opts["music_volume"] = 8
    opts["hflip"] = bool(opts.get("hflip", False))
    opts["jump_cuts"] = bool(opts.get("jump_cuts", False))
    opts["cut_zoom"] = bool(opts.get("cut_zoom", False))
    try:
        opts["tilt"] = max(0.0, min(3.0, round(float(opts.get("tilt", 0.0) or 0.0), 2)))
    except (TypeError, ValueError):
        opts["tilt"] = 0.0
    try:
        opts["speed"] = max(1.0, min(1.1, round(float(opts.get("speed", 1.0) or 1.0), 3)))
    except (TypeError, ValueError):
        opts["speed"] = 1.0
    try:
        opts["pitch"] = max(0.95, min(1.05, round(float(opts.get("pitch", 1.0) or 1.0), 3)))
    except (TypeError, ValueError):
        opts["pitch"] = 1.0
    try:
        opts["split_ratio"] = max(0.3, min(0.7, round(float(opts.get("split_ratio", 0.5) or 0.5), 2)))
    except (TypeError, ValueError):
        opts["split_ratio"] = 0.5
    bg = str(opts.get("bg_video") or "random").strip()
    if not bg or "/" in bg or "\\" in bg or ".." in bg:
        bg = "random"
    opts["bg_video"] = bg
    try:
        opts["line_gap"] = max(0, min(120, int(opts.get("line_gap", 0))))
    except (TypeError, ValueError):
        opts["line_gap"] = 0
    if not platforms.is_known(opts.get("platform")):
        opts["platform"] = platforms.DEFAULT_PLATFORM
    if opts.get("layout") not in ("", *render.STREAM_LAYOUTS, "adhd"):
        opts["layout"] = ""
    if opts.get("select") not in ("smart", "even"):
        opts["select"] = "smart"
    if opts.get("subtitle_source") not in ("auto", "whisper"):
        opts["subtitle_source"] = "auto"
    try:
        opts["audio_track"] = max(-1, min(64, int(opts.get("audio_track", -1))))
    except (TypeError, ValueError):
        opts["audio_track"] = -1
    try:
        opts["external_audio_track"] = max(-1, min(64, int(opts.get("external_audio_track", -1))))
    except (TypeError, ValueError):
        opts["external_audio_track"] = -1
    try:
        opts["audio_offset"] = round(max(-300.0, min(300.0, float(opts.get("audio_offset", 0.0) or 0.0))), 2)
    except (TypeError, ValueError):
        opts["audio_offset"] = 0.0
    opts["external_audio"] = bool(opts.get("external_audio", False))
    if opts.get("export_order") not in ("chrono", "score"):
        opts["export_order"] = "chrono"
    try:
        opts["sub_offset"] = max(-1600, min(1600, int(opts.get("sub_offset", 0))))
    except Exception:
        opts["sub_offset"] = 0
    try:
        mh = int(opts.get("max_height", 1080))
    except Exception:
        mh = 1080
    opts["max_height"] = mh if mh in (2160, 1440, 1080, 720, 480, 360) else 1080
    opts["segments"] = bool(opts.get("segments"))
    opts["force_hd"] = bool(opts.get("force_hd"))
    opts["language"] = str(opts.get("language") or "auto")
    if opts["language"] == "auto":
        opts["language"] = ""
    return opts


CANCELLED: set = set()


def request_cancel(pid: str) -> None:
    CANCELLED.add(pid)


def clear_cancel(pid: str) -> None:
    CANCELLED.discard(pid)


def _check_cancel(pid: str) -> None:
    if pid in CANCELLED:
        raise Cancelled()


def _update(pid: str, **fields: Any) -> None:
    db.update_project(pid, **fields)


def _heartbeat(pid: str, label: str):
    """Обновляет этап раз в 5 секунд, чтобы интерфейс не выглядел зависшим."""
    import threading

    stop = threading.Event()
    started = time.time()

    def run() -> None:
        while not stop.wait(5):
            try:
                # Только этап: статус и прогресс остаются за рабочим потоком.
                db.set_stage_if_active(pid, f"{label} · {int(time.time() - started)} с")
            except Exception:
                pass

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return stop, thread


def _download_phase(pid: str, project: Dict[str, Any], opts: Dict[str, Any],
                    workdir: Path, progress: Callable[[float, str], None]) -> Path:
    """Скачивает исходник, пишет метаданные и возвращает путь к файлу."""
    # Повтор после отмены не должен заново качать часовое видео: исходник уже
    # лежит в папке проекта. Единственное исключение — принудительное HD.
    if not opts.get("force_hd"):
        for name in ("source.mp4", "source.mkv", "source.webm", "source.mov", "source.m4a", "source.mp3"):
            cached = workdir / name
            if cached.exists() and cached.stat().st_size > 1024:
                try:
                    info = utils.probe(cached)
                except Exception:  # noqa: BLE001
                    break
                if info.get("duration", 0) >= 5:
                    progress(0.98, "Исходник уже скачан · пропускаю загрузку")
                    _update(pid, source=str(cached), duration=round(info["duration"], 2))
                    db.merge_meta(pid, {"width": info["width"], "height": info["height"],
                                        "source_height": info["height"],
                                        "audio_tracks": info.get("audio_streams") or []})
                    return cached
    if project["url"].startswith("local:"):
        source = Path(project.get("source") or (workdir / "source.mp4"))
        if not source.exists():
            raise RuntimeError("Загруженный файл не найден, попробуйте загрузить снова.")
        meta = {"path": source, "title": project.get("title"), "duration": None,
                "uploader": None, "extractor": "upload"}
    else:
        try:
            if downloader.is_direct_media(project["url"]):
                meta = downloader.download_file(
                    project["url"], workdir,
                    progress=lambda p, st: progress(p * 0.9, st))
            else:
                meta = downloader.download(
                    project["url"], workdir,
                    progress=lambda p, st: progress(p * 0.9, st),
                    browser=opts.get("cookies_browser") or None,
                    force_hd=opts.get("force_hd", False),
                    max_height=int(opts.get("max_height", 1080)),
                )
        except downloader.DownloadError as exc:
            raise RuntimeError(str(exc)) from exc

    source: Path = meta["path"]
    info = utils.probe(source)
    duration = info["duration"] or meta.get("duration") or 0
    if duration < 5:
        raise RuntimeError("Видео слишком короткое для нарезки.")
    _update(pid, title=meta.get("title") or project["title"], duration=round(duration, 2),
            source=str(source), thumb=None)
    db.merge_meta(pid, {
        "width": info["width"], "height": info["height"],
        "source_height": info["height"], "quality": meta.get("quality"),
        "max_height": meta.get("max_height"),
        "selected_format": meta.get("selected_format"),
        "vcodec": meta.get("vcodec"), "fps": meta.get("fps"),
        "download_seconds": meta.get("download_seconds"),
        "merge_seconds": meta.get("merge_seconds"),
        "avg_speed_mbps": meta.get("avg_speed_mbps"),
        "fallback": meta.get("fallback"),
        "fallback_reason": meta.get("fallback_reason"),
        "uploader": meta.get("uploader"), "extractor": meta.get("extractor"),
        "audio_tracks": info.get("audio_streams") or [],
    })
    return source


def _clip_settings(opts: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "aspect": opts["aspect"], "mode": opts["mode"], "subtitles": opts["subtitles"],
        "accent": opts["accent"], "uppercase": opts["uppercase"],
        "show_hook": opts["show_hook"], "focus_x": 0.5, "sub_size": opts["sub_size"],
        "sub_font": opts["sub_font"], "sub_position": opts["sub_position"],
        "sub_offset": opts["sub_offset"], "sub_speed": opts["sub_speed"],
        "line_gap": opts["line_gap"],
        "platform": opts["platform"], "layout": opts["layout"],
        "fps": None if opts.get("keep_fps", True) else 30.0,
        "export_subs": bool(opts.get("export_subs", False)),
        "look": opts["look"], "vignette": opts["vignette"], "grain": opts["grain"],
        "zoom": opts["zoom"], "bitrate": opts["bitrate"],
        "music_volume": opts["music_volume"],
        "hflip": opts["hflip"], "tilt": opts["tilt"],
        "speed": opts["speed"], "pitch": opts["pitch"],
        "jump_cuts": opts["jump_cuts"], "cut_zoom": opts["cut_zoom"],
        "bg_video": opts["bg_video"], "split_ratio": opts["split_ratio"],
        "segments": bool(opts.get("segments")),
        "audio_track": int(opts.get("audio_track", -1)),
        "external_audio": bool(opts.get("external_audio", False)),
        "external_audio_track": int(opts.get("external_audio_track", -1)),
        "audio_offset": float(opts.get("audio_offset", 0.0) or 0.0),
    }


def _audio_track(opts: Dict[str, Any]) -> Optional[int]:
    return _track_index(opts.get("audio_track", -1))


def _track_index(value: Any) -> Optional[int]:
    try:
        index = int(value)
    except (TypeError, ValueError):
        return None
    return index if index >= 0 else None


def _prepare_segments(pid: str, project: Dict[str, Any], opts: Dict[str, Any],
                      workdir: Path, progress: Callable[[float, str], None]) -> None:
    """Экономный режим: аудио → анализ → предпросмотр одного момента."""
    progress(0.02, "Скачивание аудио")
    audio = downloader.download_audio(
        project["url"], workdir, browser=opts.get("cookies_browser") or None,
        progress=lambda p, st: progress(0.02 + p * 0.28, st),
    )
    duration = float(audio.get("duration") or 0) or utils.media_duration(audio["path"])
    if duration < 5:
        raise RuntimeError("Видео слишком короткое для нарезки.")

    select = opts.get("select") or "smart"
    transcript: Optional[Dict[str, Any]] = None
    no_speech = False
    if select == "even" and not opts.get("subtitles") and not opts.get("export_subs"):
        progress(0.55, "Нарезка на равные части")
    else:
        progress(0.32, "Распознавание речи")
        stop_hb, hb_thread = _heartbeat(pid, "Распознавание речи")
        try:
            transcript = transcribe.transcribe(
                audio["path"], workdir, language=opts.get("language") or None,
                on_progress=lambda p, st: progress(0.32 + p * 0.38, f"{st} {int(p*100)}%"),
            )
        except transcribe.TranscriptionError:
            # музыку и клипы без речи режем на равные части вместо ошибки
            traceback.print_exc()
            no_speech = True
        finally:
            stop_hb.set(); hb_thread.join(timeout=1)

    engine = (transcript or {}).get("engine")
    save_transcript(workdir, transcript)
    if engine is None and (no_speech or select == "even"):
        engine = "even-split"
    _update(pid, title=audio.get("title") or project["title"], duration=round(duration, 2),
            source=str(audio["path"]), language=(transcript or {}).get("language"))
    db.merge_meta(pid, {"width": 0, "height": 0, "segments_mode": True,
                        "audio_size": audio.get("size"), "engine": engine,
                        "no_speech": bool(no_speech),
                        "segments": len((transcript or {}).get("segments") or [])})

    if select == "even" or no_speech:
        progress(0.72, "Нарезка на равные части")
        found = _even_segments(duration, opts, transcript)
    else:
        progress(0.72, "Поиск вирусных моментов")
        found = analyze.find_segments(
            transcript["segments"], audio["path"], duration,
            count=opts["count"] or 0, min_dur=opts["min_dur"],
            max_dur=opts["max_dur"], target_dur=opts["target_dur"],
        )
    if not found:
        raise RuntimeError("Не нашлось связных фрагментов. Попробуйте увеличить длину клипа.")

    settings = _clip_settings(opts)
    db.clear_clips(pid)
    for i, cand in enumerate(found):
        db.add_clip(pid, i, cand["start"], cand["end"], cand["score"], cand["title"],
                    cand["hook"], cand["caption"], cand["words"],
                    {**settings, "score_parts": cand.get("parts") or {}}, status="pending")

    # короткий предпросмотр первого момента, чтобы окно шаблона было с видео
    first = found[0]
    preview_path = workdir / "preview.mp4"
    try:
        progress(0.78, "Скачивание предпросмотра")
        sec_start = max(0.0, first["start"] - 0.5)
        sec_end = min(duration, first["end"] + 0.5)
        part = downloader.download_section(
            project["url"], workdir / "preview_src", sec_start, sec_end,
            progress=lambda p, st: progress(0.78 + p * 0.16, st),
            browser=opts.get("cookies_browser") or None, max_height=360,
        )
        shutil.copy2(part, preview_path)
        shutil.rmtree(workdir / "preview_src", ignore_errors=True)
    except Exception:
        preview_path.unlink(missing_ok=True)
        traceback.print_exc()

    _update(pid, status="review", progress=100, error=None,
            stage=f"Найдено {len(found)} моментов · настройте субтитры")
    db.merge_meta(pid, {"pending": len(found)})


def _process_segments(pid: str, project: Dict[str, Any], opts: Dict[str, Any],
                      workdir: Path, progress: Callable[[float, str], None]) -> None:
    started = time.time()
    clips = [c for c in db.list_clips(pid) if c["status"] == "pending"]
    total = len(clips)
    if not total:
        raise RuntimeError("Список моментов пуст — запустите анализ заново.")
    duration = float(project.get("duration") or 0)
    rendered = 0
    sections = workdir / "sections"
    sections.mkdir(parents=True, exist_ok=True)
    settings = _clip_settings(opts)
    for i, clip in enumerate(clips):
        _check_cancel(pid)
        base = i / total
        label = f"Момент {i + 1} из {total}"
        db.update_clip(clip["id"], status="rendering", settings=settings)


        def sub_progress(p: float, st: str, _i: int = i) -> None:
            progress(0.55 + (_i + p) / total * 0.45, f"{st} · {label}")

        try:
            sec_start = max(0.0, float(clip["start"]) - 0.5)
            sec_end = min(duration or float(clip["end"]) + 1, float(clip["end"]) + 0.5)
            part = downloader.download_section(
                project["url"], sections / clip["id"], sec_start, sec_end,
                progress=sub_progress, browser=opts.get("cookies_browser") or None,
                max_height=int(opts.get("max_height", 1080)),
            )
            actual = utils.media_duration(part)
            offset = max(0.0, float(clip["start"]) - sec_start)
            words = []
            for w in clip["words"]:
                words.append({**w, "start": float(w["start"]) - sec_start,
                              "end": float(w["end"]) - sec_start})
            virtual = {**clip, "start": offset,
                       "end": min(actual, offset + (float(clip["end"]) - float(clip["start"]))),
                       "words": words}
            # Скачанный фрагмент содержит одну дорожку — индекс полного исходника
            # к нему неприменим, как и внешний дубляж: он разложен по всему видео.
            _render_one(part, workdir, virtual,
                        {**settings, "audio_track": -1, "external_audio": False},
                        lambda p, _i=i: progress(0.55 + (_i + p) / total * 0.45, label),
                        is_cancelled=lambda: pid in CANCELLED)
            db.update_clip(clip["id"], status="ready", error=None)
            rendered += 1
            shutil.rmtree(sections / clip["id"], ignore_errors=True)
        except Cancelled:
            raise
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            db.update_clip(clip["id"], status="error", error=str(exc)[:400])

    elapsed = round(time.time() - started, 1)
    if rendered == 0:
        raise RuntimeError("Не удалось скачать и отрендерить ни одного момента.")
    _update(pid, status="done", progress=100, stage=f"Готово: {rendered} клипов",
            error=None)
    db.merge_meta(pid, {"clips": rendered})


def prepare_project(pid: str) -> None:
    """Скачивает видео и переводит проект в режим настройки субтитров."""
    project = db.get_project(pid)
    if not project:
        return
    opts = normalize_options(project.get("options"))
    workdir = PROJECTS_DIR / pid
    workdir.mkdir(parents=True, exist_ok=True)

    def progress(value: float, stage: str) -> None:
        _check_cancel(pid)
        _update(pid, progress=round(max(0.0, min(1.0, value)) * 100, 1), stage=stage,
                status="preparing")

    try:
        progress(0.01, "Подготовка")
        _update(pid, status="preparing", error=None)
        if opts.get("segments"):
            _prepare_segments(pid, project, opts, workdir, progress)
            return
        progress(0.02, "Загрузка видео")
        source = _download_phase(pid, project, opts, workdir, progress)
        info = utils.probe(source)
        took = (db.get_project(pid) or {}).get("meta", {}).get("download_seconds")
        took_txt = f" за {took:.0f} с" if took else ""
        if info["width"] and info["width"] < info["height"]:
            res_txt = f"{info['width']}×{info['height']}"
        else:
            res_txt = f"{info['height']}p"
        _update(pid, status="review", progress=100, error=None,
                stage=f"Видео готово ({res_txt}{took_txt}) · настройте субтитры")
    except Cancelled:
        _update(pid, status="cancelled", stage="Загрузка отменена", error=None)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        _update(pid, status="error", error=str(exc)[:600], stage="Ошибка загрузки")


def _even_segments(duration: float, opts: Dict[str, Any],
                   transcript: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ровная нарезка: делит видео на равные части без анализа речи.

    Нужна, когда «умные моменты» не требуются — например, нарезка серии
    на равные куски. Если субтитры включены, слова вырезаются из транскрипта
    по времени, чтобы караоке работало.
    """
    duration = max(1.0, float(duration))
    count = int(opts.get("count") or 0)
    target = max(1.0, float(opts.get("target_dur") or 60))
    explicit = count > 0
    if count <= 0:
        count = int(round(duration / target))
    count = max(1, min(200, count))
    max_dur = max(5.0, float(opts.get("max_dur") or 60))
    min_dur = max(3.0, float(opts.get("min_dur") or 15))
    step = duration / count
    # Если количество задано вручную — делим ровно на столько частей.
    # Иначе подгоняем число кусков под выбранную длительность.
    if not explicit:
        while step > max_dur and count < 200:
            count = min(200, count + max(1, int(step / max_dur)))
            step = duration / count
        while step < min_dur and count > 1:
            count -= 1
            step = duration / count

    segments = (transcript or {}).get("segments") or []
    out: List[Dict[str, Any]] = []
    for i in range(count):
        start = round(i * step, 2)
        end = round(min(duration, (i + 1) * step), 2)
        if end - start < 1.0:
            continue
        words = [
            w for seg in segments
            if float(seg.get("end") or 0) > start and float(seg.get("start") or 0) < end
            for w in (seg.get("words") or [])
        ]
        out.append({
            "start": start, "end": end, "score": 0.5,
            "title": f"Часть {i + 1}", "hook": "", "caption": "",
            "words": words, "parts": {},
        })
    return out


def _hook_allowed(transcript: Dict[str, Any]) -> bool:
    """Хук имеет смысл для кириллицы и латиницы, но не для CJK."""
    text = " ".join(str(s.get("text") or "") for s in (transcript.get("segments") or [])[:3])
    return not re.search(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]", text)


def _existing_subtitles(source: Path, workdir: Path,
                        dub: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Готовые субтитры: приложенные вручную, в дубляже или вшитые в видео.

    При включённом дубляже вшитые субтитры исходника не берём: они на языке
    оригинальной озвучки и разойдутся с русским звуком. Вместо них — дорожки
    контейнера дубляжа, если они там есть.
    """
    for name in ("subtitles.srt", "subtitles.ass", "subtitles.ssa", "subtitles.vtt"):
        path = workdir / name
        if path.exists() and path.stat().st_size > 8:
            segs = utils.parse_subtitles(path)
            if segs:
                return {"language": "", "duration": 0.0, "segments": segs,
                        "engine": f"subtitles-{path.suffix.lstrip('.').lower()}"}

    if dub is not None:
        embedded = _dub_subtitles(dub, workdir)
        if embedded is not None:
            return embedded
        return None

    cached = workdir / "source_subs.srt"
    if not cached.exists() or cached.stat().st_size < 8:
        if not utils.subtitle_streams(source):
            return None
        if not utils.extract_subtitles(source, cached):
            return None
    segs = utils.parse_subtitles(cached)
    if not segs:
        return None
    return {"language": "", "duration": 0.0, "segments": segs, "engine": "embedded-subtitles"}


def _dub_subtitles(dub: Path, workdir: Path) -> Optional[Dict[str, Any]]:
    """Текстовые субтитры внутри контейнера дубляжа; русские — первыми."""
    try:
        tracks = utils.subtitle_streams(dub)
    except Exception:  # noqa: BLE001
        return None
    if not tracks:
        return None
    tracks = sorted(tracks, key=lambda t: 0 if str(t.get("language") or "").lower()
                    in ("ru", "rus") else 1)
    for i, track in enumerate(tracks):
        dst = workdir / f"dub_subs_{i}.srt"
        if not dst.exists() or dst.stat().st_size < 8:
            if not utils.extract_subtitles(dub, dst, index=int(track.get("index", 0))):
                continue
        try:
            segs = utils.parse_subtitles(dst)
        except Exception:  # noqa: BLE001
            continue
        if segs:
            return {"language": "", "duration": 0.0, "segments": segs,
                    "engine": "dub-subtitles", "language_track": track.get("language") or ""}
    return None


def process_project(pid: str) -> None:
    """Распознаёт речь и рендерит нарезки из уже скачанного исходника."""
    project = db.get_project(pid)
    if not project:
        return
    source_raw = project.get("source")
    if not source_raw or not Path(source_raw).exists():
        _update(pid, status="error", error="Исходное видео не найдено. Загрузите его заново.",
                stage="Ошибка")
        return
    source = Path(source_raw)
    opts = normalize_options(project.get("options"))
    workdir = PROJECTS_DIR / pid
    started = time.time()

    def progress(value: float, stage: str) -> None:
        _check_cancel(pid)
        _update(pid, progress=round(max(0.0, min(1.0, value)) * 100, 1), stage=stage,
                status="running")

    if opts.get("segments"):
        pending = [c for c in db.list_clips(pid) if c["status"] == "pending"]
        if pending:
            try:
                _process_segments(pid, project, opts, workdir, progress)
            except Cancelled:
                _update(pid, status="cancelled", stage="Обработка отменена", error=None)
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                _update(pid, status="error", error=str(exc)[:600], stage="Ошибка")
            return

    try:
        info = utils.probe(source)
        duration = info["duration"]

        select = opts.get("select") or "smart"
        transcript: Optional[Dict[str, Any]] = None
        need_text = (select != "even" or bool(opts.get("subtitles"))
                     or bool(opts.get("export_subs")))
        hook_ok = False
        prepared = None
        no_speech = False
        dub = _external_audio_path(workdir, opts)
        dub_offset = float(opts.get("audio_offset", 0.0) or 0.0)
        if need_text and opts.get("subtitle_source", "auto") != "whisper":
            try:
                prepared = _existing_subtitles(source, workdir, dub=dub)
            except Exception:  # noqa: BLE001
                traceback.print_exc()
        if prepared is not None:
            progress(0.35, "Использую готовые субтитры")
            transcript = prepared
            _update(pid, language=None)
            hook_ok = _hook_allowed(transcript)
            db.merge_meta(pid, {
                "engine": transcript.get("engine"),
                "segments": len(transcript.get("segments") or []),
            })
        elif need_text:
            progress(0.05, "Распознавание речи")
            if not transcribe.model_cached():
                progress(0.05, "Скачиваю модель распознавания речи (~460 МБ, один раз)")
            stop_hb, hb_thread = _heartbeat(pid, "Распознавание речи")
            try:
                if dub is not None:
                    # Дубляж: распознаём русский звук; его время сдвинуто на offset.
                    transcript = transcribe.transcribe(
                        dub, workdir, language=opts.get("language") or None,
                        on_progress=lambda p, s: progress(0.05 + p * 0.45, f"{s} {int(p*100)}%"),
                        audio_track=_track_index(opts.get("external_audio_track")),
                    )
                    if dub_offset:
                        transcript["segments"] = timeline.shift_transcript(
                            transcript.get("segments") or [], dub_offset, duration)
                else:
                    transcript = transcribe.transcribe(
                        source, workdir, language=opts.get("language") or None,
                        on_progress=lambda p, s: progress(0.05 + p * 0.45, f"{s} {int(p*100)}%"),
                        audio_track=_audio_track(opts),
                    )
                stop_hb.set(); hb_thread.join(timeout=1)
            except Cancelled:
                stop_hb.set(); hb_thread.join(timeout=1)
                raise
            except Exception as exc:  # noqa: BLE001
                stop_hb.set(); hb_thread.join(timeout=1)
                sub_path = None
                sub_lang = ""
                if not project["url"].startswith("local:"):
                    found_sub = downloader.fetch_subtitles(
                        project["url"], workdir,
                        browser=opts.get("cookies_browser") or None)
                    if found_sub:
                        sub_path, sub_lang = found_sub
                if sub_path:
                    segs = utils.parse_vtt(Path(sub_path))
                    if segs:
                        transcript = {"language": sub_lang, "duration": duration,
                                      "segments": segs, "engine": "source-subtitles"}
                if transcript is None and isinstance(exc, transcribe.TranscriptionError):
                    no_speech = True
                elif transcript is None:
                    raise RuntimeError("Не удалось распознать речь. " + str(exc)[:300]) from exc

            _update(pid, language=(transcript or {}).get("language"))
            hook_ok = _hook_allowed(transcript or {})
            db.merge_meta(pid, {
                "engine": (transcript or {}).get("engine"),
                "segments": len((transcript or {}).get("segments") or []),
            })
        else:
            _update(pid, language=None)
            db.merge_meta(pid, {"engine": "even-split"})

        save_transcript(workdir, transcript)

        if select == "smart" and no_speech:
            select = "even"
            progress(0.55, "Речи не нашлось — режу на равные части")
            db.merge_meta(pid, {"engine": "even-split", "no_speech": True})
        if select == "even":
            progress(0.55, "Нарезка на равные части")
            found = _even_segments(duration, opts, transcript)
        else:
            progress(0.55, "Поиск вирусных моментов")
            found = analyze.find_segments(
                transcript["segments"], source, duration,
                count=opts["count"] or 0,
                min_dur=opts["min_dur"], max_dur=opts["max_dur"],
                target_dur=opts["target_dur"],
            )
        if not found:
            raise RuntimeError("Не нашлось связных фрагментов. Попробуйте увеличить длину клипа.")

        clip_settings = {
            "aspect": opts["aspect"], "mode": opts["mode"], "subtitles": opts["subtitles"],
            "accent": opts["accent"], "uppercase": opts["uppercase"],
            "show_hook": bool(opts["show_hook"]) and hook_ok,
            "focus_x": 0.5, "sub_size": opts["sub_size"],
            "sub_font": opts["sub_font"], "sub_position": opts["sub_position"],
            "sub_offset": opts["sub_offset"], "sub_speed": opts["sub_speed"],
            "line_gap": opts["line_gap"],
            "platform": opts["platform"], "layout": opts["layout"],
            "fps": None if opts.get("keep_fps", True) else 30.0,
            "export_subs": bool(opts.get("export_subs", False)),
            "look": opts["look"], "vignette": opts["vignette"], "grain": opts["grain"],
            "zoom": opts["zoom"], "bitrate": opts["bitrate"],
            "music_volume": opts["music_volume"],
            "hflip": opts["hflip"], "tilt": opts["tilt"],
            "speed": opts["speed"], "pitch": opts["pitch"],
            "jump_cuts": opts["jump_cuts"], "cut_zoom": opts["cut_zoom"],
            "bg_video": opts["bg_video"], "split_ratio": opts["split_ratio"],
            "audio_track": int(opts.get("audio_track", -1)),
            "external_audio": bool(opts.get("external_audio", False)),
            "external_audio_track": int(opts.get("external_audio_track", -1)),
            "audio_offset": float(opts.get("audio_offset", 0.0) or 0.0),
        }
        _check_cancel(pid)
        total = len(found)
        progress(0.60, f"Рендер {total} клипов")
        clips = []
        for i, cand in enumerate(found):
            clip = db.add_clip(
                pid, i, cand["start"], cand["end"], cand["score"], cand["title"],
                cand["hook"], cand["caption"], cand["words"],
                {**clip_settings, "score_parts": cand.get("parts") or {}},
            )
            clips.append(clip)

        from concurrent.futures import ThreadPoolExecutor, as_completed

        lock = threading.Lock()
        state = {"done": 0, "failed": 0, "cancel": False}

        def render_one(clip) -> bool:
            if state["cancel"]:
                return False
            try:
                _check_cancel(pid)
            except Cancelled:
                with lock:
                    state["cancel"] = True
                return False
            try:
                _render_one(source, workdir, clip, clip_settings, lambda p: None,
                            is_cancelled=lambda: pid in CANCELLED)
            except Cancelled:
                with lock:
                    state["cancel"] = True
                return False
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc()
                db.update_clip(clip["id"], status="error", error=str(exc)[:400])
                with lock:
                    state["failed"] += 1
                    state["done"] += 1
                    done, failed = state["done"], state["failed"]
                progress(0.60 + (done / max(1, total)) * 0.40,
                         f"Рендер: {done} из {total} готово" + (f" · ошибок {failed}" if failed else ""))
                return False
            with lock:
                state["done"] += 1
                done = state["done"]
            progress(0.60 + (done / max(1, total)) * 0.40, f"Рендер: {done} из {total} готово")
            return True

        workers = min(_render_workers(), max(1, total))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(render_one, clip) for clip in clips]
            rendered = sum(1 for fut in as_completed(futures) if fut.result())
        if state["cancel"]:
            raise Cancelled()

        elapsed = round(time.time() - started, 1)
        if rendered == 0:
            raise RuntimeError("Не удалось отрендерить ни одного клипа.")
        word = "клип" if rendered % 10 == 1 and rendered % 100 != 11 else (
            "клипа" if 2 <= rendered % 10 <= 4 and not 12 <= rendered % 100 <= 14 else "клипов")
        _update(pid, status="done", progress=100, error=None,
                stage=f"Готово: {rendered} {word} за {elapsed:.0f} с")
        db.merge_meta(pid, {"elapsed": elapsed, "clips": rendered})

    except Cancelled:
        _update(pid, status="cancelled", stage="Обработка отменена", error=None)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        _update(pid, status="error", error=str(exc)[:600], stage="Ошибка")


def _render_workers() -> int:
    """Сколько клипов рендерить параллельно.

    Один ffmpeg занимает ~3 ядра, поэтому на 8–10 ядрах это 2–3 рендера: суммарно
    в 1.5–2 раза быстрее, а машина остаётся отзывчивой.
    """
    raw = os.environ.get("VERTCUT_RENDER_WORKERS")
    if raw:
        try:
            return max(1, min(8, int(raw)))
        except ValueError:
            pass
    cpu = os.cpu_count() or 4
    return max(1, min(3, cpu // 3))


def run_project(pid: str) -> None:
    """Полный цикл: скачать → подготовить → обработать (для ретраев/API без превью)."""
    prepare_project(pid)
    project = db.get_project(pid)
    if not project or project.get("status") != "review":
        return
    process_project(pid)


MUSIC_SUFFIXES = (".mp3", ".m4a", ".aac", ".wav", ".ogg", ".flac", ".opus")
# Дубляж: отдельный аудиофайл или контейнер, внутри которого лежит дорожка.
DUB_SUFFIXES = (".mka", ".mkv", ".mp4", ".m4v", ".mov", ".webm", ".mp3", ".m4a",
                ".aac", ".wav", ".ogg", ".flac", ".opus", ".ac3", ".eac3", ".dts", ".ts")


def _music_file(workdir: Path) -> Optional[Path]:
    """Приложенная музыка: первый файл music.* в папке проекта."""
    for suffix in MUSIC_SUFFIXES:
        path = workdir / f"music{suffix}"
        if path.exists() and path.stat().st_size > 1024:
            return path
    return None


def _dub_file(workdir: Path) -> Optional[Path]:
    """Внешняя звуковая дорожка (дубляж): первый файл dub.* в папке проекта."""
    for suffix in DUB_SUFFIXES:
        path = workdir / f"dub{suffix}"
        if path.exists() and path.stat().st_size > 1024:
            return path
    return None


def _external_audio_path(workdir: Path, settings: Dict[str, Any]) -> Optional[Path]:
    """Дубляж только если он включён и файл на месте; иначе рендер как раньше."""
    if not settings.get("external_audio"):
        return None
    return _dub_file(workdir)


def _adhd_bg_file(choice: str) -> Optional[Path]:
    """Фон для split-screen: выбранный файл или случайный из папки."""
    from .config import ASSETS_DIR

    folder = ASSETS_DIR / "adhd_bg"
    if not folder.exists():
        return None
    files = [p for p in folder.iterdir()
             if p.is_file() and p.suffix.lower() in (".mp4", ".webm", ".mov", ".mkv", ".m4v")]
    if not files:
        return None
    if choice and choice != "random":
        for path in files:
            if path.name == choice:
                return path
    import random

    return random.choice(files)


def save_transcript(workdir: Path, transcript: Optional[Dict[str, Any]]) -> None:
    """Кладёт транскрипт рядом с проектом: перерендер может расширить границы.

    Пишем атомарно, чтобы оборванная обработка не оставила половину JSON.
    """
    if not transcript:
        return
    path = workdir / "transcript.json"
    part = workdir / "transcript.json.part"
    try:
        part.write_text(json.dumps(transcript, ensure_ascii=False), encoding="utf-8")
        os.replace(part, path)
    except OSError:
        part.unlink(missing_ok=True)


def load_transcript(workdir: Path) -> Optional[Dict[str, Any]]:
    path = workdir / "transcript.json"
    if not path.exists() or path.stat().st_size < 8:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def clip_timeline(clip: Dict[str, Any], settings: Dict[str, Any]) -> Dict[str, Any]:
    """Слова и длительность клипа после склеек и скорости.

    Одна и та же шкала нужна и для вжигания ASS, и для экспорта SRT:
    иначе файл субтитров живёт в абсолютном времени источника.
    """
    speed = max(1.0, min(1.1, float(settings.get("speed", 1.0) or 1.0)))
    words = list(clip["words"] or [])
    segs: Optional[List[Any]] = None
    base = float(clip["start"])
    length = float(clip["end"]) - base
    if settings.get("jump_cuts") and words:
        plan = timeline.plan(words, clip["start"], clip["end"], speed=speed)
        if plan["cut"]:
            segs = plan["segments"]
            words = plan["words"]
            base = 0.0
            length = plan["duration"]
    if segs is None and speed != 1.0:
        words = timeline.scale_words(words, clip["start"], speed)
        base = 0.0
        length = (float(clip["end"]) - float(clip["start"])) / speed
    return {"words": words, "segments": segs, "base": base, "length": length, "speed": speed}


def _render_one(source: Path, workdir: Path, clip: Dict[str, Any],
                settings: Dict[str, Any], on_progress: Optional[Callable[[float], None]] = None,
                is_cancelled: Optional[Callable[[], bool]] = None) -> None:
    out_dir = workdir / "clips"
    ass_dir = workdir / "ass"
    out_dir.mkdir(parents=True, exist_ok=True)
    ass_dir.mkdir(parents=True, exist_ok=True)

    layout = settings.get("layout") or ""
    if layout not in ("", *render.STREAM_LAYOUTS, "adhd"):
        layout = ""

    speed = float(settings.get("speed", 1.0) or 1.0)
    speed = max(1.0, min(1.1, speed))
    pitch = float(settings.get("pitch", 1.0) or 1.0)
    pitch = max(0.95, min(1.05, pitch))
    tl = clip_timeline(clip, settings)
    segs: Optional[List[Any]] = tl["segments"]
    words = tl["words"]
    ass_base = float(tl["base"])
    ass_len = float(tl["length"])
    out_duration = ass_len

    sub_position = settings.get("sub_position", "bottom")
    ass_path = None
    burn_subs = bool(settings.get("subtitles", True))
    export_subs = bool(settings.get("export_subs", False))
    if words and (burn_subs or export_subs):
        text = subtitles.build_ass(
            words, ass_base, ass_base + ass_len,
            hook=clip.get("hook") or clip.get("title") or "",
            accent=settings.get("accent", "yellow"),
            uppercase=settings.get("uppercase", True),
            show_hook=settings.get("show_hook", True),
            sub_size=int(settings.get("sub_size", 118)),
            font=settings.get("sub_font", "montserrat"),
            position=sub_position,
            offset=int(settings.get("sub_offset", 0)),
            speed=settings.get("sub_speed", "calm"),
            line_gap=int(settings.get("line_gap", 0) or 0),
            platform=settings.get("platform", platforms.DEFAULT_PLATFORM),
            bottom_reserve=(render.BAND_H if layout == "band" else 0),
            top_reserve=(render.BAND_H if layout == "band_top" else 0),
        )
        ass_path = ass_dir / f"{clip['id']}.ass"
        ass_path.write_text(text, encoding="utf-8")

    # Субтитры не вжигаем, но файл оставляем для экспорта в редактор.
    if not burn_subs:
        ass_path = None

    out_path = out_dir / f"clip_{clip['idx'] + 1:02d}.mp4"
    crop_path = None
    mode = settings.get("mode", "auto")
    platform = settings.get("platform", "")
    facecam: Optional[Dict[str, Any]] = None
    exclude = avoid = None
    crop_aspect = settings.get("aspect", "9:16")
    ratio = float(settings.get("split_ratio", 0.5) or 0.5)

    if layout == "adhd":
        # Верх — видео, низ — фон. Окно кадрирования считаем под верхнюю часть.
        top_h = max(2, int(round(1920 * ratio / 2.0)) * 2)
        crop_aspect = f"1080:{top_h}"
    elif layout in render.STREAM_LAYOUTS:
        # Пресет стрима: находим врезку и не даём окну кадрирования её накрыть.
        try:
            facecam = reframe.detect_facecam(source, clip["start"], clip["end"])
            if facecam:
                # координаты врезки нужны предпросмотру в редакторе
                settings = {**settings, "facecam": facecam}
                db.update_clip(clip["id"], settings=settings)
        except Exception:
            facecam = None
        if facecam:
            exclude = (facecam["x"], facecam["y"],
                       facecam["x"] + facecam["w"], facecam["y"] + facecam["h"])
            avoid = exclude
            crop_aspect = "27:32" if layout in ("band", "band_top") else "9:16"
        else:
            layout = ""

    if mode == "auto" or layout:
        try:
            crop_path = reframe.build_crop_path(
                source, clip["start"], clip["end"], aspect=crop_aspect,
                exclude=exclude, avoid=avoid)
        except Exception:
            crop_path = None
        # если лиц почти нет (скринкаст, слайды) — сохраняем весь кадр на размытом фоне
        if not layout and crop_path and crop_path.get("coverage", 1.0) < 0.18:
            mode = "blur"
            crop_path = None

    if crop_path and (segs is not None or speed != 1.0):
        span = segs if segs is not None else [(0.0, float(clip["end"]) - float(clip["start"]))]
        # Кроп применяется к кадру до setpts=PTS/speed, поэтому скорость здесь
        # учитывать нельзя: иначе окно кадрирования отстаёт от картинки.
        crop_path = timeline.remap_crop_path(crop_path, span, 1.0)

    bg_path = None
    bg_start = 0.0
    if layout == "adhd":
        bg_path = _adhd_bg_file(str(settings.get("bg_video") or "random"))
        if bg_path is not None:
            try:
                bg_info = utils.probe(bg_path)
                span = max(0.0, float(bg_info.get("duration") or 0) - 3.0)
                if span > 0:
                    import random

                    bg_start = round(random.uniform(0.0, span), 2)
            except Exception:
                bg_start = 0.0

    result = render.render_clip(
        source, clip["start"], clip["end"], out_path, ass_path=ass_path,
        aspect=settings.get("aspect", "9:16"), mode=mode,
        focus_x=float(settings.get("focus_x", 0.5)), on_progress=on_progress,
        crop_path=crop_path, layout=layout, facecam=facecam, platform=platform,
        fps=settings.get("fps"),
        look=settings.get("look", "none"),
        vignette=bool(settings.get("vignette")),
        grain=bool(settings.get("grain")),
        zoom=int(settings.get("zoom", 100) or 100),
        bitrate=int(settings.get("bitrate", 0) or 0),
        music_path=_music_file(workdir),
        music_volume=float(settings.get("music_volume", 8) or 0) / 100.0,
        hflip=bool(settings.get("hflip")),
        tilt=float(settings.get("tilt", 0.0) or 0.0),
        speed=speed,
        pitch=pitch,
        segments=segs,
        cut_zoom=bool(settings.get("cut_zoom")),
        bg_path=bg_path,
        bg_start=bg_start,
        split_ratio=ratio,
        audio_track=settings.get("audio_track"),
        external_audio=_external_audio_path(workdir, settings),
        audio_offset=float(settings.get("audio_offset", 0.0) or 0.0),
        external_audio_track=_track_index(settings.get("external_audio_track")),
        is_cancelled=is_cancelled,
    )
    settings = {**settings, "render_encoder": result.get("encoder", "libx264")}
    thumb_path = workdir / "thumbs" / f"{clip['id']}.jpg"
    render.make_thumb(out_path, thumb_path, at=min(1.2, max(0.2, out_duration * 0.15)))
    render.make_preview(out_path, workdir / "previews" / f"{clip['id']}.mp4")
    db.update_clip(clip["id"], status="ready", path=str(out_path),
                   settings=settings,
                   thumb=str(thumb_path) if thumb_path.exists() else None, error=None)


def rerender_clip(clip_id: str, payload: Dict[str, Any],
                  on_progress: Optional[Callable[[float], None]] = None) -> Dict[str, Any]:
    clip = db.get_clip(clip_id)
    if not clip:
        raise RuntimeError("Клип не найден")
    project = db.get_project(clip["project_id"])
    if not project:
        raise RuntimeError("Клип не найден")
    workdir = PROJECTS_DIR / project["id"]
    live_recording = (workdir / "segments" / "times.jsonl").exists()
    if not project.get("source") and not live_recording:
        raise RuntimeError("Исходное видео не найдено: запись эфира удалена или ещё не началась.")
    settings = dict(clip["settings"])
    if settings.get("segments"):
        raise RuntimeError("Клип собран в экономном режиме из фрагмента. Шаблон меняется до запуска нарезки.")
    for key in ("aspect", "mode", "subtitles", "accent", "uppercase", "show_hook", "focus_x",
                "sub_size", "sub_font", "sub_position", "sub_offset", "sub_speed", "line_gap",
                "platform", "layout", "look", "vignette", "grain", "zoom", "bitrate",
                "music_volume", "hflip", "tilt", "speed", "pitch", "jump_cuts", "cut_zoom",
                "bg_video", "split_ratio", "fps", "audio_track", "external_audio",
                "external_audio_track", "audio_offset"):
        if key in payload and payload[key] is not None:
            settings[key] = payload[key]
    if (payload.get("layout") == "adhd" and payload.get("sub_position") is None
            and (clip.get("settings") or {}).get("layout") != "adhd"):
        # Первое включение split-screen: субтитры на стык кадров.
        settings["sub_position"] = "middle"
    start = float(payload.get("start", clip["start"]))
    end = float(payload.get("end", clip["end"]))
    if end - start < 3:
        raise RuntimeError("Клип слишком короткий")
    words = list(clip["words"] or [])
    if not project.get("source"):
        from . import live
        # старые live-клипы хранили слова относительно окна эфира
        words = live._absolute_words(words, float(clip["start"]))
    if start != clip["start"] or end != clip["end"]:
        source_words = list(words)
        if project.get("source"):
            saved = load_transcript(workdir)
            if saved:
                # Расширяем окно по полному транскрипту: в clip.words только
                # слова, попавшие в исходные границы клипа.
                source_words = [w for seg in saved.get("segments") or []
                                for w in seg.get("words") or []]
        words = [w for w in source_words if float(w["end"]) > start and float(w["start"]) < end]
    # правка текста субтитров: сохраняем тайминги, меняем только слова
    if payload.get("text") is not None and str(payload.get("text")).strip():
        words = subtitles.retime_words(words, str(payload["text"]))
    db.update_clip(clip_id, status="rendering", start=start, end=end, words=words,
                   hook=payload.get("hook", clip["hook"]), title=payload.get("title", clip["title"]),
                   caption=payload.get("caption", clip["caption"]),
                   settings=settings, error=None)
    updated = db.get_clip(clip_id)
    if project.get("source"):
        _render_one(Path(project["source"]), workdir, updated, settings, on_progress,
                    is_cancelled=lambda: clip["project_id"] in CANCELLED)
    else:
        from . import live
        # клип из прямого эфира: берём фрагмент из записанных сегментов
        live._render_live_clip(workdir, updated, 0.0, settings)
    return db.get_clip(clip_id) or updated


def build_named_exports(project_id: str) -> Path:
    """Папка named/ с человеческими именами: префикс порядка + название."""
    project = db.get_project(project_id)
    workdir = PROJECTS_DIR / project_id
    named = workdir / "named"
    named.mkdir(parents=True, exist_ok=True)
    clips = [c for c in db.list_clips(project_id) if c["status"] == "ready" and c["path"]]
    order = ((project or {}).get("options") or {}).get("export_order", "chrono")
    desired = {}
    for clip, name in utils.named_exports(clips, order):
        src = Path(clip["path"])
        if src.exists():
            desired[name] = (src, clip["id"])
    for old in named.iterdir():
        if old.is_file() and old.name not in desired:
            try:
                old.unlink()
            except OSError:
                pass
    for name, (src, _cid) in desired.items():
        target = named / name
        try:
            target.unlink(missing_ok=True)
            try:
                os.link(src, target)
            except OSError:
                shutil.copy2(src, target)
        except OSError:
            continue
    return named


def export_zip(project_id: str, dest: Path) -> Path:
    project = db.get_project(project_id)
    clips = [c for c in db.list_clips(project_id) if c["status"] == "ready" and c["path"]]
    if not clips:
        raise RuntimeError("Нет готовых клипов для экспорта")
    import zipfile

    order = ((project or {}).get("options") or {}).get("export_order", "chrono")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_STORED) as zf:
        for clip, name in utils.named_exports(clips, order):
            src = Path(clip["path"])
            if src.exists():
                zf.write(src, arcname=name)
    return dest


def delete_project_files(project_id: str) -> None:
    shutil.rmtree(PROJECTS_DIR / project_id, ignore_errors=True)
