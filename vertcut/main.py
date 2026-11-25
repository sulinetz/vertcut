"""FastAPI-приложение VertCut."""
from __future__ import annotations

import json
import os
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from . import (ads, app_settings, custom_fonts, db, jobs, pipeline, semantic,
               transcribe)
from ._version import __version__
from .config import (ADHD_SPLIT_BACKEND_MIN, ADHD_SPLIT_UI_MAX, ADHD_SPLIT_UI_MIN,
                     ASSETS_DIR, DATA_DIR, PROJECTS_DIR, WEB_DIR, ffmpeg)


class ProjectIn(BaseModel):
    url: str
    options: Dict[str, Any] = {}
    prepare_only: bool = False


class UpdateSettingsIn(BaseModel):
    enabled: bool = True


class AppSettingsIn(BaseModel):
    deepseek_key: Optional[str] = None
    gemini_key: Optional[str] = None
    deepseek_model: Optional[str] = None
    gemini_model: Optional[str] = None
    openrouter_key: Optional[str] = None
    openrouter_model: Optional[str] = None
    whisper_model: Optional[str] = None
    asr_terms: Optional[str] = None
    proxy: Optional[str] = None
    clear_deepseek_key: bool = False
    clear_gemini_key: bool = False
    clear_openrouter_key: bool = False


class AdTextIn(BaseModel):
    text: str
    color: str = "#FFFFFF"
    background: str = "#00000000"
    font_size: int = 64
    name: str = ""


class AdRenameIn(BaseModel):
    name: str


class AdMapIn(BaseModel):
    time: float
    direction: str = "to_source"
    events: Optional[List[Dict[str, Any]]] = None


class CheckKeyIn(BaseModel):
    provider: str


class RetryIn(BaseModel):
    force_hd: bool = False
    prepare_only: bool = False
    options: Dict[str, Any] = {}


class StartIn(BaseModel):
    options: Dict[str, Any] = {}


class DraftIn(BaseModel):
    title: str = ""
    url: str = ""
    options: Dict[str, Any] = {}


class ProbeIn(BaseModel):
    url: str
    cookies_browser: str = ""


class StreamIn(BaseModel):
    url: str
    options: Dict[str, Any] = Field(default_factory=dict)


class ClipEdit(BaseModel):
    text: Optional[str] = None
    start: Optional[float] = None
    end: Optional[float] = None
    hook: Optional[str] = None
    title: Optional[str] = None
    caption: Optional[str] = None
    aspect: Optional[str] = None
    mode: Optional[str] = None
    subtitles: Optional[bool] = None
    accent: Optional[str] = None
    uppercase: Optional[bool] = None
    show_hook: Optional[bool] = None
    sub_size: Optional[int] = None
    sub_font: Optional[str] = None
    sub_position: Optional[str] = None
    sub_offset: Optional[int] = None
    sub_speed: Optional[str] = None
    line_gap: Optional[int] = None
    look: Optional[str] = None
    vignette: Optional[bool] = None
    grain: Optional[bool] = None
    zoom: Optional[int] = None
    bitrate: Optional[int] = None
    music_volume: Optional[int] = None
    platform: Optional[str] = None
    layout: Optional[str] = None
    hflip: Optional[bool] = None
    tilt: Optional[float] = None
    speed: Optional[float] = None
    pitch: Optional[float] = None
    jump_cuts: Optional[bool] = None
    cut_zoom: Optional[bool] = None
    bg_video: Optional[str] = None
    split_ratio: Optional[float] = None
    adhd_bg: Optional[str] = None
    adhd_top_fill: Optional[str] = None
    adhd_bottom_fill: Optional[str] = None
    adhd_top_scale: Optional[float] = None
    adhd_top_offset_x: Optional[float] = None
    adhd_top_offset_y: Optional[float] = None
    adhd_bottom_scale: Optional[float] = None
    adhd_bottom_offset_x: Optional[float] = None
    adhd_bottom_offset_y: Optional[float] = None
    adhd_bottom_speed: Optional[float] = None
    adhd_bottom_start: Optional[float] = None
    adhd_bottom_volume: Optional[float] = None
    ads_enabled: Optional[bool] = None
    ad_events: Optional[List[Dict[str, Any]]] = None
    audio_track: Optional[int] = None
    external_audio: Optional[bool] = None
    external_audio_track: Optional[int] = None
    audio_offset: Optional[float] = None


# Лимит загрузки: интерфейс берёт значение из /api/health и проверяет сам.
# 0 или пусто — без ограничения (проекты можно хранить на большом диске).
ALLOWED_UPLOAD_SUFFIXES = {
    ".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".ts", ".mts", ".m2ts",
    ".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac",
}
MAX_UPLOAD_BYTES = int(float(os.environ.get("VERTCUT_MAX_UPLOAD_GB", "0") or "0") * 1024 ** 3)
MAX_FONT_BYTES = 24 * 1024 * 1024


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """Побочные эффекты старта — здесь, а не на импорте модуля."""
    db.init_db()
    db.reset_stale_jobs()
    custom_fonts.sync()
    from .config import ffmpeg_capabilities

    caps = ffmpeg_capabilities()
    print("[ffmpeg] " + (caps.get("version") or "версия неизвестна")
          + " · ass: " + ("да" if caps.get("ass") else "нет")
          + " · loudnorm: " + ("да" if caps.get("loudnorm") else "нет")
          + " · amix normalize: " + ("да" if caps.get("amix_normalize") else "нет"),
          flush=True)
    info = transcribe.device_info()
    print(f"[whisper] устройство: {info['device']}/{info['compute']}"
          + (f" ({info['note']})" if info.get("note") else ""), flush=True)
    yield


async def _stream_upload(file: UploadFile, target: Path, limit: int,
                         too_big: str) -> Path:
    """Потоково пишет загрузку в .part, соблюдая лимит, затем заменяет файл."""
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    written = 0
    try:
        with open(part, "wb") as fh:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if limit and written > limit:
                    raise HTTPException(413, too_big)
                fh.write(chunk)
        if written <= 0:
            raise HTTPException(400, "Файл пустой")
        os.replace(part, target)
    except HTTPException:
        part.unlink(missing_ok=True)
        raise
    except Exception:
        part.unlink(missing_ok=True)
        raise
    return target


# CORS не нужен: страница отдаётся с того же origin, что и API. Без него чужая
# вкладка в браузере не может дёргать локальный сервер (SSRF/забивка диска).
app = FastAPI(title="VertCut", version=__version__, lifespan=_lifespan)


@app.middleware("http")
async def _static_cache_headers(request, call_next):
    """Шрифты и статика неизменяемы в пределах сессии — не перекачиваем их каждым опросом."""
    response = await call_next(request)
    path = request.url.path
    # Шрифты неизменяемы, а код интерфейса — нет: иначе правки не доезжают
    # до WebView, который держит app.js в кэше.
    if path.startswith(("/fonts/", "/userfonts/")):
        response.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
    elif path.startswith("/static/") or path == "/":
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


def _clean_clip_edit(body: ClipEdit) -> Dict[str, Any]:
    """Проверяет правку клипа до постановки в очередь: 400 вместо «клип упал».

    Раньше значения уезжали в фоновую задачу, и клип молча переходил в error.
    """
    from . import platforms, render, subtitles

    data = {k: v for k, v in body.model_dump().items() if v is not None}
    allowed = {"text", "start", "end", "hook", "title", "caption", "focus_x"}
    allowed |= set(pipeline.CLIP_SETTING_KEYS)
    data = {k: v for k, v in data.items() if k in allowed}
    if "aspect" in data and data["aspect"] not in render.ASPECTS:
        raise HTTPException(400, "Неизвестный формат кадра")
    if "mode" in data and data["mode"] not in ("auto", "blur", "crop"):
        raise HTTPException(400, "Неизвестный режим кадрирования")
    if "accent" in data and data["accent"] not in subtitles.ACCENTS:
        raise HTTPException(400, "Неизвестный цвет акцента")
    if "sub_position" in data and data["sub_position"] not in subtitles.POSITIONS:
        raise HTTPException(400, "Неизвестное положение субтитров")
    if "sub_speed" in data and data["sub_speed"] not in subtitles.SPEEDS:
        raise HTTPException(400, "Неизвестная скорость субтитров")
    if "platform" in data and not platforms.is_known(data["platform"]):
        raise HTTPException(400, "Неизвестная площадка")
    if "layout" in data:
        from . import render as _render
        if data["layout"] not in ("", *_render.STREAM_LAYOUTS, "adhd"):
            raise HTTPException(400, "Неизвестный пресет кадра")
    if "sub_font" in data and not subtitles.font_exists(data["sub_font"]):
        raise HTTPException(400, "Шрифт не найден")
    if "sub_size" in data:
        try:
            data["sub_size"] = max(70, min(180, int(data["sub_size"])))
        except (TypeError, ValueError):
            raise HTTPException(400, "Некорректный размер субтитров") from None
    if "look" in data and data["look"] not in ("none", "warm", "cool", "contrast", "cinematic", "soft"):
        raise HTTPException(400, "Неизвестный цветовой пресет")
    for key, low, high in (("zoom", 100, 120), ("bitrate", 0, 40), ("music_volume", 0, 50)):
        if key in data:
            try:
                data[key] = max(low, min(high, int(data[key])))
            except (TypeError, ValueError):
                raise HTTPException(400, "Некорректное значение") from None
    for key, low, high in (("speed", 1.0, 1.1), ("pitch", 0.95, 1.05),
                           ("tilt", 0.0, 3.0), ("split_ratio", 0.25, 0.85)):
        if key in data:
            try:
                data[key] = max(low, min(high, round(float(data[key]), 3)))
            except (TypeError, ValueError):
                raise HTTPException(400, "Некорректное значение") from None
    for key in ("hflip", "jump_cuts", "cut_zoom"):
        if key in data:
            data[key] = bool(data[key])
    if "external_audio" in data:
        data["external_audio"] = bool(data["external_audio"])
    if "external_audio_track" in data:
        try:
            data["external_audio_track"] = max(-1, min(64, int(data["external_audio_track"])))
        except (TypeError, ValueError):
            raise HTTPException(400, "Некорректная дорожка дубляжа") from None
    if "audio_offset" in data:
        try:
            data["audio_offset"] = round(max(-300.0, min(300.0, float(data["audio_offset"]))), 2)
        except (TypeError, ValueError):
            raise HTTPException(400, "Некорректный сдвиг дубляжа") from None
    if "bg_video" in data:
        name = str(data["bg_video"] or "random").strip()
        if name != "random" and ("/" in name or "\\" in name or ".." in name):
            raise HTTPException(400, "Некорректное имя фона")
        data["bg_video"] = name or "random"
    if "adhd_bg" in data:
        name = str(data["adhd_bg"] or "").strip()
        if name and ("/" in name or "\\" in name or ".." in name):
            raise HTTPException(400, "Некорректное имя фона")
        data["adhd_bg"] = name
    for key in ("adhd_top_fill", "adhd_bottom_fill"):
        if key in data:
            value = str(data[key] or "cover").strip().lower()
            if value not in ("cover", "contain"):
                raise HTTPException(400, "Неизвестный режим заполнения области")
            data[key] = value
    for key, low, high, default in (
            ("adhd_top_scale", 0.5, 2.0, 1.0),
            ("adhd_bottom_scale", 0.5, 2.0, 1.0),
            ("adhd_top_offset_x", -0.5, 0.5, 0.0),
            ("adhd_top_offset_y", -0.5, 0.5, 0.0),
            ("adhd_bottom_offset_x", -0.5, 0.5, 0.0),
            ("adhd_bottom_offset_y", -0.5, 0.5, 0.0),
            ("adhd_bottom_speed", 0.25, 4.0, 1.0),
            ("adhd_bottom_start", -1.0, 7200.0, -1.0),
            ("adhd_bottom_volume", 0.0, 50.0, 0.0)):
        if key in data:
            try:
                data[key] = round(max(low, min(high, float(data[key]))), 3)
            except (TypeError, ValueError):
                raise HTTPException(400, "Некорректное значение настроек СДВГ") from None
    if "ad_events" in data:
        known = {asset["id"] for asset in ads.list_assets()}
        data["ad_events"] = ads.normalize_events(data["ad_events"], known)
    if "ads_enabled" in data:
        data["ads_enabled"] = bool(data["ads_enabled"])
    if "line_gap" in data:
        try:
            data["line_gap"] = max(0, min(120, int(data["line_gap"])))
        except (TypeError, ValueError):
            raise HTTPException(400, "Некорректный межстрочный интервал") from None
    if "audio_track" in data:
        try:
            data["audio_track"] = max(-1, min(64, int(data["audio_track"])))
        except (TypeError, ValueError):
            raise HTTPException(400, "Некорректная аудиодорожка") from None
    if "sub_offset" in data:
        try:
            data["sub_offset"] = max(-1600, min(1600, int(data["sub_offset"])))
        except (TypeError, ValueError):
            raise HTTPException(400, "Некорректное смещение субтитров") from None
    if "text" in data:
        data["text"] = str(data["text"] or "").strip()[:4000]
    for key in ("start", "end"):
        if key in data:
            try:
                data[key] = max(0.0, float(data[key]))
            except (TypeError, ValueError):
                raise HTTPException(400, "Некорректные границы клипа") from None
    return data


@app.get("/api/health")
def health() -> Dict[str, Any]:
    ok_ffmpeg = True
    try:
        ffmpeg()
    except Exception:
        ok_ffmpeg = False
    return {
        "ok": ok_ffmpeg,
        "ffmpeg": ok_ffmpeg,
        "whisper": transcribe.model_available(),
        "model": transcribe.model_cached(),
        "device": transcribe.device_info(),
        "projects": db.count_projects(),
        "max_upload_bytes": MAX_UPLOAD_BYTES,
        "adhd_split": {"min": round(ADHD_SPLIT_UI_MIN * 100),
                       "max": round(ADHD_SPLIT_UI_MAX * 100),
                       "backend_min": round(ADHD_SPLIT_BACKEND_MIN * 100)},
    }


@app.get("/api/system")
def system_stats() -> Dict[str, Any]:
    """Нагрузка CPU/GPU, температура GPU и свободное место — для панели в UI."""
    from . import sysmon

    return sysmon.snapshot()


@app.get("/api/update")
def update_state(force: bool = False) -> Dict[str, Any]:
    """Состояние проверки обновлений; сеть — только в фоне или по force."""
    from . import updater

    if force:
        return updater.check(force=True)
    updater.maybe_check_async()
    return updater.payload()


@app.post("/api/update/settings")
def update_settings(body: UpdateSettingsIn) -> Dict[str, Any]:
    from . import updater

    return updater.set_enabled(body.enabled)


@app.get("/api/app-settings")
def app_settings_get() -> Dict[str, Any]:
    """Модели и подсказки по ключам. Сами ключи наружу не отдаются."""
    return {
        **app_settings.public(),
        "moods": semantic.MOODS,
        "pickers": list(semantic.PICKERS),
    }


@app.post("/api/app-settings")
def app_settings_save(body: AppSettingsIn) -> Dict[str, Any]:
    if body.whisper_model:
        normalized = app_settings.normalize_whisper_model(body.whisper_model)
        if not normalized:
            raise HTTPException(400, "Неизвестная модель распознавания речи")
        body.whisper_model = normalized
    if body.asr_terms is not None and len(body.asr_terms) > 2000:
        raise HTTPException(400, "Словарь терминов длиннее 2000 символов")
    app_settings.save(body.model_dump(exclude_none=True))
    return {"ok": True, **app_settings.public()}


@app.get("/api/app-settings/models")
def app_settings_models(provider: Optional[str] = None) -> Dict[str, Any]:
    """Каталог моделей провайдеров. OpenRouter отдаёт список без ключа."""
    keys = [provider] if provider in semantic.PROVIDERS else list(semantic.PROVIDERS)
    catalogs: Dict[str, Any] = {}
    for key in keys:
        try:
            catalogs[key] = {"ok": True, "models": semantic.models_for(key)}
        except Exception as exc:  # noqa: BLE001
            fallback = app_settings.MODEL_CHOICES.get(key) or []
            catalogs[key] = {
                "ok": False,
                "error": str(exc)[:300],
                "models": [{"id": item, "name": item, "context": 0} for item in fallback],
            }
    return {"catalogs": catalogs}


@app.post("/api/app-settings/check")
def app_settings_check(body: CheckKeyIn) -> Dict[str, Any]:
    return semantic.check_key(body.provider)


@app.get("/api/fonts")
def fonts() -> List[Dict[str, Any]]:
    from .subtitles import fonts_payload

    return list(fonts_payload()) + custom_fonts.payload()


@app.post("/api/fonts")
async def font_upload(file: UploadFile = File(...)) -> Dict[str, Any]:
    suffix = Path(file.filename or "font.ttf").suffix.lower() or ".ttf"
    temp = DATA_DIR / f"font_upload{suffix}"
    try:
        await _stream_upload(file, temp, MAX_FONT_BYTES, "Файл шрифта больше 24 МБ")
        data = temp.read_bytes()
        try:
            return custom_fonts.save(file.filename or "font.ttf", data)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"Не удалось прочитать шрифт: {str(exc)[:200]}") from exc
    finally:
        temp.unlink(missing_ok=True)


@app.delete("/api/fonts/{key}")
def font_delete(key: str) -> Dict[str, Any]:
    if not custom_fonts.delete(key):
        raise HTTPException(404, "Шрифт не найден")
    return {"ok": True}


@app.get("/api/fonts.css")
def fonts_css() -> Response:
    lines = []
    for font in custom_fonts.list_custom():
        family = custom_fonts._clean_family(font.get("css") or f"VCCustom_{font['key']}").replace(" ", "_")
        lines.append(
            f'@font-face {{ font-family: "{family}"; '
            f'src: url("/userfonts/{font["file"]}"); font-display: swap; }}'
        )
    return Response("\n".join(lines), media_type="text/css")


@app.get("/api/projects")
def projects() -> List[Dict[str, Any]]:
    return db.list_projects(100)


@app.post("/api/projects")
def create_project(body: ProjectIn) -> Dict[str, Any]:
    url = (body.url or "").strip()
    if not url:
        raise HTTPException(400, "Добавьте ссылку на видео")
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "Ссылка должна начинаться с http:// или https://")
    project = db.create_project(url, pipeline.normalize_options(body.options))
    if body.prepare_only:
        jobs.submit_prepare(project["id"])
    else:
        jobs.submit_project(project["id"])
    return project


@app.post("/api/probe")
def probe_video(body: ProbeIn) -> Dict[str, Any]:
    from . import downloader

    url = (body.url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "Некорректная ссылка")
    try:
        return downloader.probe(url, browser=body.cookies_browser or None)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Не удалось получить информацию о видео: {str(exc)[:300]}") from exc


@app.post("/api/streams")
def stream_create(body: StreamIn) -> Dict[str, Any]:
    from . import live

    url = (body.url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "Ссылка должна начинаться с http:// или https://")
    options = pipeline.normalize_options(body.options)
    project = db.create_project(url, options, title="Прямой эфир")
    db.update_project(project["id"], status="running", stage="Подключаюсь к эфиру…",
                      meta={"live": True, "live_status": "connecting", "live_processed": 0,
                            "live_clips": 0, "ad_intervals": []})
    jobs.submit_stream(project["id"], options)
    return db.get_project(project["id"])


@app.get("/api/streams")
def streams_list() -> List[Dict[str, Any]]:
    return [p for p in db.list_projects(100) if (p.get("meta") or {}).get("live")]


@app.get("/api/streams/{pid}")
def stream_detail(pid: str) -> Dict[str, Any]:
    project = db.get_project(pid)
    if not project or not (project.get("meta") or {}).get("live"):
        raise HTTPException(404, "Стрим не найден")
    clips = db.list_clips(pid)
    for clip in clips:
        preview = PROJECTS_DIR / pid / "previews" / f"{clip['id']}.mp4"
        clip["has_preview"] = preview.exists()
    return {"project": project, "clips": clips}


@app.post("/api/streams/{pid}/stop")
def stream_stop(pid: str) -> Dict[str, Any]:
    from . import live

    project = db.get_project(pid)
    if not project or not (project.get("meta") or {}).get("live"):
        raise HTTPException(404, "Стрим не найден")
    live.stop_stream(pid)
    db.update_project(pid, stage="Останавливаю запись…")
    return {"ok": True}


async def _store_upload(pid: str, file: UploadFile) -> Path:
    """Пишет загруженный файл в папку проекта, проверяя формат, размер и медиа."""
    if not file.filename:
        raise HTTPException(400, "Файл не выбран")
    suffix = Path(file.filename).suffix.lower() or ".mp4"
    if suffix not in ALLOWED_UPLOAD_SUFFIXES:
        raise HTTPException(400, f"Формат {suffix} не поддерживается — загрузите видео или аудио")
    workdir = PROJECTS_DIR / pid
    workdir.mkdir(parents=True, exist_ok=True)
    target = workdir / f"source{suffix}"
    part = workdir / f"source{suffix}.part"
    written = 0
    try:
        with open(part, "wb") as fh:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if MAX_UPLOAD_BYTES and written > MAX_UPLOAD_BYTES:
                    size_hint = (f"{MAX_UPLOAD_BYTES / 1024 ** 3:.1f} ГБ"
                                 if MAX_UPLOAD_BYTES >= 1024 ** 3
                                 else f"{MAX_UPLOAD_BYTES / 1024 ** 2:.0f} МБ")
                    raise HTTPException(
                        413,
                        f"Файл больше {size_hint} — загрузите фрагмент короче "
                        "или поднимите VERTCUT_MAX_UPLOAD_GB",
                    )
                fh.write(chunk)
        if part.stat().st_size < 1024:
            raise HTTPException(400, "Файл пустой или повреждён")
        # Проверяем временный файл: рабочий исходник подменяем только после
        # успешной проверки, иначе сбойный upload убивает прошлое видео.
        from . import utils

        probed: Dict[str, Any] = {}
        try:
            probed = await run_in_threadpool(utils.probe, part)
        except Exception:  # noqa: BLE001
            probed = {}
        if not probed.get("duration"):
            raise HTTPException(400, "Файл не похож на видео или аудио — проверьте содержимое")
        os.replace(part, target)
        for other in workdir.glob("source.*"):
            if other != target and not other.name.endswith(".part"):
                other.unlink(missing_ok=True)
    except HTTPException:
        part.unlink(missing_ok=True)
        raise
    except Exception:
        part.unlink(missing_ok=True)
        raise
    tracks = probed.get("audio_streams") or []
    if tracks:
        db.merge_meta(pid, {"audio_tracks": tracks})
    return target


@app.post("/api/projects/draft")
def create_draft(body: DraftIn) -> Dict[str, Any]:
    """Проект без исходника: пользователь сначала настраивает параметры.

    Загрузка начнётся только по кнопке «Запуск», а не сразу после выбора файла.
    """
    project = db.create_project(body.url.strip() or "local:source",
                                pipeline.normalize_options(body.options),
                                title=body.title or "Новый проект")
    db.update_project(project["id"], status="draft", stage="Настройте параметры и запустите")
    return db.get_project(project["id"]) or project


@app.post("/api/projects/{pid}/upload")
async def upload_into_project(pid: str, file: UploadFile = File(...)) -> Dict[str, Any]:
    project = db.get_project(pid)
    if not project:
        raise HTTPException(404, "Проект не найден")
    had_source = bool(project.get("source"))
    try:
        target = await _store_upload(pid, file)
    except HTTPException as exc:
        db.update_project(pid, status="error", stage="Ошибка загрузки",
                          error=str(exc.detail)[:400])
        raise
    try:
        from . import utils

        tracks = await run_in_threadpool(utils.subtitle_streams, target)
    except Exception:  # noqa: BLE001
        tracks = []
    db.update_project(pid, source=str(target), title=file.filename or project.get("title"),
                      status="review", stage="Видео готово · настройте шаблон",
                      progress=100, error=None)
    if tracks:
        db.merge_meta(pid, {"subtitle_tracks": tracks})
    # Дубляж от прошлого исходника к новому видео не подходит: убираем, чтобы
    # не получить чужой звук в клипах. Первая загрузка в черновик не считается.
    if had_source:
        _clear_dub(pid, PROJECTS_DIR / pid, drop_options=True)
    return db.get_project(pid) or project


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)) -> Dict[str, Any]:
    if not file.filename:
        raise HTTPException(400, "Файл не выбран")
    project = db.create_project("local:source", pipeline.normalize_options({}),
                                title=file.filename)
    try:
        target = await _store_upload(project["id"], file)
    except HTTPException:
        shutil.rmtree(PROJECTS_DIR / project["id"], ignore_errors=True)
        db.delete_project(project["id"])
        raise
    db.update_project(project["id"], source=str(target), title=file.filename)
    jobs.submit_prepare(project["id"])
    return db.get_project(project["id"]) or project


SUBTITLE_SUFFIXES = {".srt", ".ass", ".ssa", ".vtt"}


@app.post("/api/projects/{pid}/subtitles")
async def upload_subtitles(pid: str, file: UploadFile = File(...)) -> Dict[str, Any]:
    """Приложить свои субтитры: текст возьмётся из файла вместо распознавания."""
    project = db.get_project(pid)
    if not project:
        raise HTTPException(404, "Проект не найден")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUBTITLE_SUFFIXES:
        raise HTTPException(400, "Нужен файл .srt, .ass, .ssa или .vtt")
    workdir = PROJECTS_DIR / pid
    workdir.mkdir(parents=True, exist_ok=True)
    for old in SUBTITLE_SUFFIXES:
        (workdir / f"subtitles{old}").unlink(missing_ok=True)
    target = workdir / f"subtitles{suffix}"
    await _stream_upload(file, target, 10 * 1024 * 1024, "Файл субтитров больше 10 МБ")
    try:
        from . import utils

        segments = utils.parse_subtitles(target)
    except Exception as exc:  # noqa: BLE001
        target.unlink(missing_ok=True)
        raise HTTPException(400, f"Не удалось прочитать субтитры: {str(exc)[:120]}") from exc
    if not segments:
        target.unlink(missing_ok=True)
        raise HTTPException(400, "В файле не нашлось реплик")
    db.merge_meta(pid, {"subtitles_attached": len(segments)})
    return {"ok": True, "segments": len(segments)}


@app.get("/api/projects/{pid}")
def project_detail(pid: str) -> Dict[str, Any]:
    project = db.get_project(pid)
    if not project:
        raise HTTPException(404, "Проект не найден")
    clips = db.list_clips(pid)
    for clip in clips:
        preview = PROJECTS_DIR / pid / "previews" / f"{clip['id']}.mp4"
        clip["has_preview"] = preview.exists()
    source = project.get("source")
    preview = PROJECTS_DIR / pid / "preview.mp4"
    if preview.exists():
        project["source_url"] = f"/media/{pid}/preview.mp4"
    elif source:
        try:
            from urllib.parse import quote
            rel = Path(source).relative_to(PROJECTS_DIR).as_posix()
            project["source_url"] = "/media/" + quote(rel)
        except ValueError:
            pass
    tracks = (project.get("meta") or {}).get("audio_tracks") or []
    if source and not tracks and Path(source).exists():
        try:
            from . import utils

            tracks = utils.audio_streams(Path(source))
            if tracks:
                db.merge_meta(pid, {"audio_tracks": tracks})
                project.setdefault("meta", {})["audio_tracks"] = tracks
        except Exception:  # noqa: BLE001
            tracks = []
    project["audio_tracks"] = tracks
    adhd_choice = str((project.get("options") or {}).get("adhd_bg") or "")
    if adhd_choice.startswith("local:"):
        project["adhd_bg_url"] = f"/api/projects/{pid}/adhd-bg/file"
    else:
        project["adhd_bg_url"] = ""
    project["adhd_bg"] = adhd_choice
    sub_tracks = (project.get("meta") or {}).get("subtitle_tracks") or []
    if source and not sub_tracks and Path(source).exists():
        try:
            from . import utils

            sub_tracks = utils.subtitle_streams(Path(source))
            if sub_tracks:
                db.merge_meta(pid, {"subtitle_tracks": sub_tracks})
                project.setdefault("meta", {})["subtitle_tracks"] = sub_tracks
        except Exception:  # noqa: BLE001
            sub_tracks = []
    project["subtitle_tracks"] = sub_tracks
    dub_meta = (project.get("meta") or {}).get("dub")
    dub_file = pipeline._dub_file(PROJECTS_DIR / pid)
    if dub_file is not None:
        if not isinstance(dub_meta, dict) or not dub_meta:
            try:
                from . import utils

                probed = utils.probe_audio(dub_file)
                dub_meta = {"name": dub_file.name,
                            "duration": round(float(probed.get("duration") or 0), 2),
                            "has_video": bool(probed.get("has_video")),
                            "audio_tracks": probed.get("audio_streams") or [],
                            "sample_rate": int(probed.get("sample_rate") or 48000)}
                db.merge_meta(pid, {"dub": dub_meta})
            except Exception:  # noqa: BLE001
                dub_meta = None
        if dub_meta is not None:
            dub_meta = {**dub_meta, "ready": True}
    else:
        dub_meta = None
    project["dub"] = dub_meta
    return {"project": project, "clips": clips}


@app.post("/api/projects/{pid}/start")
def project_start(pid: str, body: StartIn = StartIn()) -> Dict[str, Any]:
    project = db.get_project(pid)
    if not project:
        raise HTTPException(404, "Проект не найден")
    if project.get("status") != "review":
        hints = {
            "draft": "Сначала выберите файл или ссылку и запустите обработку",
            "queued": "Обработка уже стоит в очереди",
            "preparing": "Видео ещё скачивается — дождитесь окончания",
            "running": "Обработка уже идёт",
            "processing": "Обработка уже идёт",
            "done": "Видео уже обработано — откройте его в истории",
            "cancelled": "Обработка отменена — нажмите «Повторить»",
            "error": "Прошлая попытка упала — нажмите «Повторить»",
        }
        raise HTTPException(400, hints.get(project.get("status"),
                                           "Видео ещё не готово к настройке"))
    if jobs.is_running(pid):
        raise HTTPException(409, "Обработка уже идёт — дождитесь окончания или отмените")
    options = pipeline.normalize_options(body.options or project.get("options"))
    pipeline.clear_cancel(pid)
    pending = [c for c in db.list_clips(pid) if c["status"] == "pending"]
    if not (options.get("segments") and pending):
        db.clear_clips(pid)
    db.update_project(pid, status="queued", stage="В очереди", progress=0, error=None,
                      options=options)
    jobs.submit_process(pid)
    return db.get_project(pid) or project


@app.post("/api/projects/{pid}/options")
def project_options(pid: str, body: StartIn = StartIn()) -> Dict[str, Any]:
    """Сохранить проектную настройку без запуска обработки (например, порядок экспорта)."""
    project = db.get_project(pid)
    if not project:
        raise HTTPException(404, "Проект не найден")
    current = project.get("options") or {}
    options = pipeline.normalize_options({**current, **(body.options or {})})
    db.update_project(pid, options=options)
    return db.get_project(pid) or project


@app.post("/api/projects/{pid}/cancel")
def project_cancel(pid: str) -> Dict[str, Any]:
    project = db.get_project(pid)
    if not project:
        raise HTTPException(404, "Проект не найден")
    if project.get("status") not in ("queued", "preparing", "running", "processing"):
        raise HTTPException(409, "Проект уже не обрабатывается — отменять нечего")
    pipeline.request_cancel(pid)
    db.update_project(pid, status="cancelled", stage="Отменено", error=None)
    return {"ok": True}


@app.post("/api/projects/{pid}/retry")
def project_retry(pid: str, body: RetryIn = RetryIn()) -> Dict[str, Any]:
    project = db.get_project(pid)
    if not project:
        raise HTTPException(404, "Проект не найден")
    if jobs.is_running(pid):
        # текущая обработка ещё останавливается — поставим повтор в очередь
        pipeline.request_cancel(pid)
    options = pipeline.normalize_options(body.options or project.get("options"))
    options["force_hd"] = bool(body.force_hd)
    # Флаг отмены снимает jobs._guarded перед стартом новой задачи: иначе
    # текущая (ещё останавливающаяся) обработка потеряет сигнал отмены.
    db.clear_clips(pid)
    db.update_project(pid, status="queued", stage="В очереди", progress=0, error=None,
                      options=options)
    if body.prepare_only:
        jobs.submit_prepare(pid)
    else:
        jobs.submit_project(pid)
    return db.get_project(pid) or project


@app.delete("/api/projects/{pid}")
def project_delete(pid: str) -> Dict[str, Any]:
    if not db.get_project(pid):
        raise HTTPException(404, "Проект не найден")
    from . import live

    # Сначала гасим запись/рендер и даём потокам увидеть отмену: иначе ffmpeg
    # продолжает писать в папку, которую мы сейчас удаляем.
    live.stop_stream(pid)
    pipeline.request_cancel(pid)
    db.delete_project(pid)
    pipeline.delete_project_files(pid)
    return {"ok": True}


@app.get("/api/projects/{pid}/frame.jpg")
def project_frame(pid: str, t: float = 0.0, width: int = 720):
    """Кадр источника для живого предпросмотра кадрирования в мастере."""
    project = db.get_project(pid)
    if not project or not project.get("source"):
        raise HTTPException(404, "Исходное видео не найдено")
    source = Path(project["source"])
    if not source.exists():
        raise HTTPException(404, "Исходное видео не найдено")
    frames = PROJECTS_DIR / pid / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    width = max(240, min(1280, int(width)))
    target = frames / f"f_{int(max(0.0, float(t)) * 1000)}_{width}.jpg"
    if not target.exists() or target.stat().st_size < 1000:
        from . import utils

        proc = utils.run([ffmpeg(), "-y", "-v", "error",
                          "-ss", f"{max(0.0, float(t)):.3f}", "-i", str(source),
                          "-frames:v", "1", "-vf", f"scale={width}:-2",
                          "-q:v", "3", str(target)])
        if proc.returncode != 0 or not target.exists() or target.stat().st_size < 1000:
            target.unlink(missing_ok=True)
            raise HTTPException(400, "Не удалось взять кадр из видео")
    return FileResponse(target, media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=3600"})


@app.get("/api/projects/{pid}/frame-info")
def project_frame_info(pid: str, t: float = -1.0, aspect: str = "9:16"):
    """Случайное время и окно кадрирования для предпросмотра."""
    import random

    from . import reframe, render, utils

    project = db.get_project(pid)
    if not project or not project.get("source"):
        raise HTTPException(404, "Исходное видео не найдено")
    source = Path(project["source"])
    if not source.exists():
        raise HTTPException(404, "Исходное видео не найдено")
    duration = float(project.get("duration") or 0) or utils.media_duration(source)
    if duration <= 0:
        raise HTTPException(400, "Не удалось определить длительность видео")
    if t < 0:
        t = random.uniform(0.05, 0.95) * duration
    t = max(0.0, min(max(0.0, duration - 0.2), float(t)))
    if aspect not in render.ASPECTS:
        aspect = "9:16"
    box = reframe.frame_box(source, t, aspect)
    return {"time": round(t, 2), "duration": round(duration, 2), "box": box}


@app.get("/api/clips/{cid}/subtitles.srt")
def clip_srt(cid: str) -> Response:
    """SRT для монтажа в своём редакторе: правленый текст уже внутри."""
    clip = db.get_clip(cid)
    if not clip:
        raise HTTPException(404, "Клип не найден")
    from . import subtitles

    data = pipeline.clip_timeline(clip, clip.get("settings") or {})
    body = subtitles.to_srt(data["words"], data["base"], data["base"] + data["length"])
    if not body.strip():
        raise HTTPException(400, "В клипе нет субтитров")
    title = (clip.get("title") or "clip").replace("/", " ").replace('"', "").strip()[:60] or "clip"
    # кириллица в заголовке не влезает в latin-1 — отдаём имя по RFC 5987
    from urllib.parse import quote

    disposition = (f"attachment; filename=\"clip.srt\"; "
                   f"filename*=UTF-8''{quote(title + '.srt')}")
    return Response(content=body, media_type="application/x-subrip",
                    headers={"Content-Disposition": disposition})


@app.get("/api/ads")
def ads_list() -> Dict[str, Any]:
    return {"assets": ads.list_assets()}


@app.post("/api/ads")
async def ads_upload(file: UploadFile = File(...)) -> Dict[str, Any]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ads.IMAGE_SUFFIXES and suffix not in ads.VIDEO_SUFFIXES:
        raise HTTPException(400, "Нужен PNG, JPG, WEBP или видео MP4/WEBM/MOV/MKV")
    temp = DATA_DIR / f"ads_upload{suffix}"
    try:
        await _stream_upload(file, temp, ads.MAX_VIDEO_BYTES, "Файл больше 300 МБ")
        asset = ads.add_file(file.filename or f"asset{suffix}", temp)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        temp.unlink(missing_ok=True)
    return {"ok": True, "asset": asset}


@app.post("/api/ads/text")
def ads_add_text(body: AdTextIn) -> Dict[str, Any]:
    try:
        asset = ads.add_text(body.text, color=body.color, background=body.background,
                             font_size=body.font_size, name=body.name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "asset": asset}


@app.patch("/api/ads/{asset_id}")
def ads_rename(asset_id: str, body: AdRenameIn) -> Dict[str, Any]:
    try:
        return {"ok": True, "asset": ads.rename(asset_id, body.name)}
    except KeyError:
        raise HTTPException(404, "Ассет не найден") from None


@app.delete("/api/ads/{asset_id}")
def ads_delete(asset_id: str) -> Dict[str, Any]:
    if not ads.delete(asset_id):
        raise HTTPException(404, "Ассет не найден")
    return {"ok": True}


@app.get("/api/ads/{asset_id}/file")
def ads_file(asset_id: str) -> FileResponse:
    path = ads.asset_path(asset_id)
    if path is None:
        raise HTTPException(404, "Ассет не найден")
    suffix = path.suffix.lower()
    media = ("video/mp4" if suffix in ads.VIDEO_SUFFIXES
             else "image/png" if suffix == ".png"
             else "image/jpeg" if suffix in (".jpg", ".jpeg")
             else "image/webp")
    return FileResponse(path, media_type=media)


def _clip_ad_context(cid: str, events: Optional[List[Dict[str, Any]]] = None) -> tuple:
    clip = db.get_clip(cid)
    if not clip:
        raise HTTPException(404, "Клип не найден")
    settings = dict(clip.get("settings") or {})
    if events is not None:
        settings["ad_events"] = ads.normalize_events(events)
    info = pipeline.ad_timeline(clip, settings)
    return clip, settings, info


@app.get("/api/clips/{cid}/ad-timeline")
def clip_ad_timeline(cid: str, events: Optional[str] = None) -> Dict[str, Any]:
    from . import timeline

    override = None
    if events:
        try:
            parsed = json.loads(events)
            override = parsed if isinstance(parsed, list) else None
        except ValueError:
            override = None
    clip, settings, info = _clip_ad_context(cid, override)
    span = [(0.0, max(0.1, float(clip["end"]) - float(clip["start"])))]
    segments = info["segments"] or span
    events = []
    inserts_by_id = {str(item["event"].get("id")): item for item in info["inserts"]}
    for event in settings.get("ad_events") or []:
        if not isinstance(event, dict):
            continue
        try:
            local = max(0.0, float(event.get("start") or 0.0) - float(clip["start"]))
            length = max(0.2, float(event.get("duration") or 1.0))
        except (TypeError, ValueError):
            continue
        base_start = timeline.remap_time(local, segments, info["speed"])
        base_end = timeline.remap_time(local + length, segments, info["speed"])
        own = inserts_by_id.get(str(event.get("id"))) if event.get("kind") == "replace" else None
        if own is not None:
            start = own["final_start"]
            end = round(start + own["duration"], 3)
        else:
            start = timeline.inserted_time(base_start, info["inserts"], inclusive=True)
            end = timeline.inserted_time(base_end, info["inserts"], inclusive=False)
        events.append({**event, "start_final": start, "end_final": end})
    return {"base_length": info["length"], "duration": info["duration"],
            "speed": info["speed"],
            "inserts": [{**item["event"], "at": item["at"],
                         "final_start": item["final_start"],
                         "duration": item["duration"]}
                        for item in info["inserts"]],
            "events": events}


@app.post("/api/clips/{cid}/ad-map")
def clip_ad_map(cid: str, body: AdMapIn) -> Dict[str, Any]:
    from . import timeline

    clip, _settings, info = _clip_ad_context(cid, body.events)
    span = [(0.0, max(0.1, float(clip["end"]) - float(clip["start"])))]
    segments = info["segments"] or span
    if body.direction == "to_final":
        local = max(0.0, float(body.time) - float(clip["start"]))
        base = timeline.remap_time(local, segments, info["speed"])
        value = timeline.inserted_time(base, info["inserts"], inclusive=True)
    else:
        base = timeline.unmap_inserted(float(body.time), info["inserts"])
        value = timeline.unmap_time(base, segments, info["speed"]) + float(clip["start"])
    return {"time": round(max(0.0, value), 3)}


ADHD_BG_DIR = ASSETS_DIR / "adhd_bg"
ADHD_BG_SUFFIXES = {".mp4", ".webm", ".mov", ".mkv", ".m4v"}
ADHD_BG_MAX_BYTES = 300 * 1024 * 1024
_ADHD_BG_CACHE: Dict[str, Any] = {}


def _adhd_bg_info(path: Path) -> Dict[str, Any]:
    """Длительность и размеры фона; кэш по mtime/size, чтобы не звать ffmpeg каждый раз."""
    try:
        stat = path.stat()
    except OSError:
        return {}
    key = (int(stat.st_mtime), stat.st_size)
    cached = _ADHD_BG_CACHE.get(str(path))
    if cached and cached.get("key") == key:
        return dict(cached["info"])
    from . import utils

    try:
        probed = utils.probe(path)
    except Exception:  # noqa: BLE001
        return {}
    info = {"duration": round(float(probed.get("duration") or 0), 2),
            "width": int(probed.get("width") or 0),
            "height": int(probed.get("height") or 0)}
    _ADHD_BG_CACHE[str(path)] = {"key": key, "info": info}
    return dict(info)


def _adhd_bg_files() -> List[Dict[str, Any]]:
    if not ADHD_BG_DIR.exists():
        return []
    out: List[Dict[str, Any]] = []
    for path in sorted(ADHD_BG_DIR.iterdir()):
        if path.is_file() and path.suffix.lower() in ADHD_BG_SUFFIXES:
            out.append({"name": path.name, "size": path.stat().st_size,
                        **_adhd_bg_info(path)})
    return out


@app.get("/api/adhd-bg")
def list_adhd_bg() -> Dict[str, Any]:
    return {"files": _adhd_bg_files()}


@app.get("/api/adhd-bg/file/{name}")
def adhd_bg_file(name: str) -> FileResponse:
    safe = Path(name).name
    if safe != name or not safe:
        raise HTTPException(400, "Некорректное имя фона")
    target = ADHD_BG_DIR / safe
    if target.suffix.lower() not in ADHD_BG_SUFFIXES or not target.exists():
        raise HTTPException(404, "Фон не найден")
    return FileResponse(target, media_type="video/mp4")


@app.get("/api/projects/{pid}/adhd-bg/file")
def project_adhd_bg_file(pid: str) -> FileResponse:
    project = db.get_project(pid)
    if not project:
        raise HTTPException(404, "Проект не найден")
    for path in (PROJECTS_DIR / pid).glob("adhd_bottom.*"):
        if path.is_file() and path.suffix.lower() in ADHD_BG_SUFFIXES:
            return FileResponse(path, media_type="video/mp4")
    raise HTTPException(404, "Нижнее видео не загружено")


@app.post("/api/adhd-bg")
async def upload_adhd_bg(file: UploadFile = File(...)) -> Dict[str, Any]:
    """Фоновые видео для split-screen: лежат в assets/adhd_bg."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ADHD_BG_SUFFIXES:
        raise HTTPException(400, "Нужен видеофайл: mp4, webm, mov, mkv")
    ADHD_BG_DIR.mkdir(parents=True, exist_ok=True)
    base = "".join(ch for ch in Path(file.filename or "bg").stem if ch.isalnum() or ch in "-_ ")[:48].strip()
    if not base:
        base = "bg"
    target = ADHD_BG_DIR / f"{base}{suffix}"
    counter = 1
    while target.exists():
        target = ADHD_BG_DIR / f"{base}_{counter}{suffix}"
        counter += 1
    await _stream_upload(file, target, ADHD_BG_MAX_BYTES, "Файл больше 300 МБ")
    return {"ok": True, "name": target.name, "size": target.stat().st_size}


@app.post("/api/projects/{pid}/adhd-bg")
async def upload_project_adhd_bg(pid: str, file: UploadFile = File(...)) -> Dict[str, Any]:
    """Своё нижнее видео для проекта: лежит рядом с проектом, не в общей библиотеке."""
    project = db.get_project(pid)
    if not project:
        raise HTTPException(404, "Проект не найден")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ADHD_BG_SUFFIXES:
        raise HTTPException(400, "Нужен видеофайл: mp4, webm, mov, mkv")
    workdir = PROJECTS_DIR / pid
    workdir.mkdir(parents=True, exist_ok=True)
    for old in workdir.glob("adhd_bottom.*"):
        old.unlink(missing_ok=True)
    target = workdir / f"adhd_bottom{suffix}"
    await _stream_upload(file, target, ADHD_BG_MAX_BYTES, "Файл больше 300 МБ")
    options = pipeline.normalize_options({
        **(project.get("options") or {}),
        "layout": "adhd",
        "adhd_bg": f"local:{target.name}",
    })
    db.update_project(pid, options=options)
    return {"ok": True, "name": target.name, "size": target.stat().st_size,
            **_adhd_bg_info(target)}


@app.delete("/api/projects/{pid}/adhd-bg")
def delete_project_adhd_bg(pid: str) -> Dict[str, Any]:
    project = db.get_project(pid)
    if not project:
        raise HTTPException(404, "Проект не найден")
    workdir = PROJECTS_DIR / pid
    for old in workdir.glob("adhd_bottom.*"):
        old.unlink(missing_ok=True)
    options = pipeline.normalize_options({
        **(project.get("options") or {}), "adhd_bg": ""})
    db.update_project(pid, options=options)
    return {"ok": True}


@app.delete("/api/adhd-bg/{name}")
def delete_adhd_bg(name: str) -> Dict[str, Any]:
    safe = Path(name).name
    if safe != name or not safe:
        raise HTTPException(400, "Некорректное имя фона")
    target = ADHD_BG_DIR / safe
    if target.suffix.lower() not in ADHD_BG_SUFFIXES or not target.exists():
        raise HTTPException(404, "Фон не найден")
    target.unlink(missing_ok=True)
    return {"ok": True}


MUSIC_SUFFIXES = {".mp3", ".m4a", ".aac", ".wav", ".ogg", ".flac", ".opus"}


@app.post("/api/projects/{pid}/music")
async def upload_music(pid: str, file: UploadFile = File(...)) -> Dict[str, Any]:
    """Фоновая музыка: тихо подмешивается к оригинальной дорожке."""
    project = db.get_project(pid)
    if not project:
        raise HTTPException(404, "Проект не найден")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in MUSIC_SUFFIXES:
        raise HTTPException(400, "Нужен аудиофайл: mp3, m4a, wav, ogg, flac")
    workdir = PROJECTS_DIR / pid
    workdir.mkdir(parents=True, exist_ok=True)
    for old in MUSIC_SUFFIXES:
        (workdir / f"music{old}").unlink(missing_ok=True)
    target = workdir / f"music{suffix}"
    await _stream_upload(file, target, 60 * 1024 * 1024, "Файл больше 60 МБ")
    db.merge_meta(pid, {"music": True})
    return {"ok": True, "size": target.stat().st_size}


@app.delete("/api/projects/{pid}/music")
def delete_music(pid: str) -> Dict[str, Any]:
    project = db.get_project(pid)
    if not project:
        raise HTTPException(404, "Проект не найден")
    for old in MUSIC_SUFFIXES:
        (PROJECTS_DIR / pid / f"music{old}").unlink(missing_ok=True)
    db.merge_meta(pid, {"music": False})
    return {"ok": True}


DUB_SUFFIXES = set(pipeline.DUB_SUFFIXES)


def _clear_dub(pid: str, workdir: Path, drop_options: bool = False) -> None:
    """Убирает файл дубляжа и кэш его субтитров, чтобы не осталось чужих дорожек."""
    for suffix in DUB_SUFFIXES:
        (workdir / f"dub{suffix}").unlink(missing_ok=True)
    for cached in workdir.glob("dub_subs_*.srt"):
        cached.unlink(missing_ok=True)
    db.merge_meta(pid, {"dub": None})
    if drop_options:
        project = db.get_project(pid)
        options = (project or {}).get("options") or {}
        if options.get("external_audio"):
            db.update_project(pid, options=pipeline.normalize_options(
                {**options, "external_audio": False}))


@app.post("/api/projects/{pid}/dub")
async def upload_dub(pid: str, file: UploadFile = File(...)) -> Dict[str, Any]:
    """Внешняя звуковая дорожка (дубляж): заменяет звук исходного видео."""
    project = db.get_project(pid)
    if not project:
        raise HTTPException(404, "Проект не найден")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in DUB_SUFFIXES:
        raise HTTPException(400, "Нужен аудиофайл (mka, aac, mp3, flac…) или контейнер (mkv, mp4)")
    workdir = PROJECTS_DIR / pid
    workdir.mkdir(parents=True, exist_ok=True)
    target = workdir / f"dub{suffix}"
    part = workdir / f"dub{suffix}.part"
    written = 0
    try:
        with open(part, "wb") as fh:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if MAX_UPLOAD_BYTES and written > MAX_UPLOAD_BYTES:
                    size_hint = (f"{MAX_UPLOAD_BYTES / 1024 ** 3:.1f} ГБ"
                                 if MAX_UPLOAD_BYTES >= 1024 ** 3
                                 else f"{MAX_UPLOAD_BYTES / 1024 ** 2:.0f} МБ")
                    raise HTTPException(413, f"Файл больше {size_hint} — поднимите VERTCUT_MAX_UPLOAD_GB")
                fh.write(chunk)
        # Проверяем временный файл: старый дубляж остаётся, пока новый не прошёл
        # проверку. Иначе сбойная загрузка оставляет проект без звука.
        from . import utils

        info: Dict[str, Any] = {}
        try:
            info = utils.probe_audio(part)
        except Exception:  # noqa: BLE001
            info = {}
        if not info.get("has_audio") or float(info.get("duration") or 0) < 1:
            raise HTTPException(400, "В файле нет звуковой дорожки — проверьте содержимое")
        os.replace(part, target)
        for old in DUB_SUFFIXES:
            path = workdir / f"dub{old}"
            if path != target:
                path.unlink(missing_ok=True)
        for cached in workdir.glob("dub_subs_*.srt"):
            cached.unlink(missing_ok=True)
    except HTTPException:
        part.unlink(missing_ok=True)
        raise
    except Exception:
        part.unlink(missing_ok=True)
        raise
    meta = {
        "name": file.filename or target.name,
        "duration": round(float(info.get("duration") or 0), 2),
        "has_video": bool(info.get("has_video")),
        "audio_tracks": info.get("audio_streams") or [],
        "sample_rate": int(info.get("sample_rate") or 48000),
    }
    db.merge_meta(pid, {"dub": meta})
    options = pipeline.normalize_options(
        {**(project.get("options") or {}), "external_audio": True})
    db.update_project(pid, options=options)
    return {"ok": True, "dub": meta, "project": db.get_project(pid) or project}


@app.delete("/api/projects/{pid}/dub")
def delete_dub(pid: str) -> Dict[str, Any]:
    project = db.get_project(pid)
    if not project:
        raise HTTPException(404, "Проект не найден")
    _clear_dub(pid, PROJECTS_DIR / pid, drop_options=True)
    return {"ok": True}


@app.get("/api/clips/{cid}/download")
def clip_download(cid: str) -> FileResponse:
    """Скачать клип с человеческим именем в выбранном порядке проекта."""
    clip = db.get_clip(cid)
    if not clip or not clip.get("path"):
        raise HTTPException(404, "Клип не найден")
    path = Path(clip["path"])
    if not path.exists():
        raise HTTPException(404, "Файл клипа не найден на диске")
    from . import utils

    project = db.get_project(clip["project_id"]) or {}
    order = ((project.get("options") or {}).get("export_order") or "chrono")
    ready = [c for c in db.list_clips(clip["project_id"]) if c["status"] == "ready"]
    name = next((name for c, name in utils.named_exports(ready, order) if c["id"] == cid), None)
    name = name or f"{utils.safe_filename(clip.get('title') or 'clip')}.mp4"
    return FileResponse(path, media_type="video/mp4", filename=name)


@app.get("/api/clips/{cid}/subtitles.ass")
def clip_ass(cid: str) -> FileResponse:
    """Тот же ASS, что вжигается в видео — для монтажа в своём редакторе."""
    clip = db.get_clip(cid)
    if not clip:
        raise HTTPException(404, "Клип не найден")
    path = PROJECTS_DIR / clip["project_id"] / "ass" / f"{clip['id']}.ass"
    if not path.exists():
        raise HTTPException(404, "Субтитры для этого клипа ещё не собраны")
    title = (clip.get("title") or "clip").replace("/", " ").strip()[:60] or "clip"
    from urllib.parse import quote

    disposition = (f"attachment; filename=\"clip.ass\"; "
                   f"filename*=UTF-8''{quote(title + '.ass')}")
    return FileResponse(path, media_type="text/x-ssa",
                        headers={"Content-Disposition": disposition})


@app.post("/api/clips/{cid}/rerender")
def clip_rerender(cid: str, body: ClipEdit) -> Dict[str, Any]:
    clip = db.get_clip(cid)
    if not clip:
        raise HTTPException(404, "Клип не найден")
    project = db.get_project(clip["project_id"])
    if project and not project.get("source"):
        # клип из прямого эфира: режем из записанных сегментов
        if not (PROJECTS_DIR / project["id"] / "segments" / "times.jsonl").exists():
            raise HTTPException(400, "Запись эфира не найдена — перерендер невозможен")
        recorded = float((project.get("meta") or {}).get("live_duration") or 0)
        if body.end and recorded and body.end > recorded + 0.5:
            raise HTTPException(400, "Конец клипа выходит за пределы записанной части эфира")
    payload = _clean_clip_edit(body)
    start = float(payload.get("start", clip["start"]))
    end = float(payload.get("end", clip["end"]))
    if end <= start:
        raise HTTPException(400, "Конец клипа должен быть позже начала")
    if project and project.get("source"):
        limit = float(project.get("duration") or 0)
        if limit and end > limit + 0.5:
            raise HTTPException(400, "Конец клипа выходит за пределы видео")
    jobs.submit_rerender(cid, payload)
    return {"ok": True, "clip": db.get_clip(cid)}


@app.get("/api/projects/{pid}/zip")
def project_zip(pid: str) -> FileResponse:
    project = db.get_project(pid)
    if not project:
        raise HTTPException(404, "Проект не найден")
    dest = PROJECTS_DIR / pid / f"vertcut_{pid}.zip"
    try:
        pipeline.export_zip(pid, dest)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc)) from exc
    return FileResponse(dest, filename="vertcut_clips.zip", media_type="application/zip")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


custom_fonts.CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/fonts", StaticFiles(directory=str(ASSETS_DIR / "fonts")), name="fonts")
app.mount("/userfonts", StaticFiles(directory=str(custom_fonts.CUSTOM_DIR)), name="userfonts")
app.mount("/media", StaticFiles(directory=str(PROJECTS_DIR)), name="media")
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
