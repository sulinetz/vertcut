"""FastAPI-приложение VertCut."""
from __future__ import annotations

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

from . import custom_fonts, db, jobs, pipeline, transcribe
from ._version import __version__
from .config import ASSETS_DIR, DATA_DIR, PROJECTS_DIR, WEB_DIR, ffmpeg


class ProjectIn(BaseModel):
    url: str
    options: Dict[str, Any] = {}
    prepare_only: bool = False


class UpdateSettingsIn(BaseModel):
    enabled: bool = True


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
                           ("tilt", 0.0, 3.0), ("split_ratio", 0.3, 0.7)):
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


@app.get("/api/fonts")
def fonts() -> List[Dict[str, Any]]:
    from .subtitles import fonts_payload

    return list(fonts_payload()) + custom_fonts.payload()


@app.post("/api/fonts")
async def font_upload(file: UploadFile = File(...)) -> Dict[str, Any]:
    data = await file.read()
    if len(data) > MAX_FONT_BYTES:
        raise HTTPException(413, "Файл шрифта больше 24 МБ")
    try:
        return custom_fonts.save(file.filename or "font.ttf", data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Не удалось прочитать шрифт: {str(exc)[:200]}") from exc


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
            probed = utils.probe(part)
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

        tracks = utils.subtitle_streams(target)
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
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(413, "Файл субтитров больше 10 МБ")
    workdir = PROJECTS_DIR / pid
    workdir.mkdir(parents=True, exist_ok=True)
    for old in SUBTITLE_SUFFIXES:
        (workdir / f"subtitles{old}").unlink(missing_ok=True)
    target = workdir / f"subtitles{suffix}"
    target.write_bytes(data)
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


ADHD_BG_DIR = ASSETS_DIR / "adhd_bg"
ADHD_BG_SUFFIXES = {".mp4", ".webm", ".mov", ".mkv", ".m4v"}
ADHD_BG_MAX_BYTES = 300 * 1024 * 1024


def _adhd_bg_files() -> List[Dict[str, Any]]:
    if not ADHD_BG_DIR.exists():
        return []
    out: List[Dict[str, Any]] = []
    for path in sorted(ADHD_BG_DIR.iterdir()):
        if path.is_file() and path.suffix.lower() in ADHD_BG_SUFFIXES:
            out.append({"name": path.name, "size": path.stat().st_size})
    return out


@app.get("/api/adhd-bg")
def list_adhd_bg() -> Dict[str, Any]:
    return {"files": _adhd_bg_files()}


@app.post("/api/adhd-bg")
async def upload_adhd_bg(file: UploadFile = File(...)) -> Dict[str, Any]:
    """Фоновые видео для split-screen: лежат в assets/adhd_bg."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ADHD_BG_SUFFIXES:
        raise HTTPException(400, "Нужен видеофайл: mp4, webm, mov, mkv")
    data = await file.read()
    if len(data) > ADHD_BG_MAX_BYTES:
        raise HTTPException(413, "Файл больше 300 МБ")
    ADHD_BG_DIR.mkdir(parents=True, exist_ok=True)
    base = "".join(ch for ch in Path(file.filename or "bg").stem if ch.isalnum() or ch in "-_ ")[:48].strip()
    if not base:
        base = "bg"
    target = ADHD_BG_DIR / f"{base}{suffix}"
    counter = 1
    while target.exists():
        target = ADHD_BG_DIR / f"{base}_{counter}{suffix}"
        counter += 1
    target.write_bytes(data)
    return {"ok": True, "name": target.name, "size": len(data)}


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
    data = await file.read()
    if len(data) > 60 * 1024 * 1024:
        raise HTTPException(413, "Файл больше 60 МБ")
    workdir = PROJECTS_DIR / pid
    workdir.mkdir(parents=True, exist_ok=True)
    for old in MUSIC_SUFFIXES:
        (workdir / f"music{old}").unlink(missing_ok=True)
    (workdir / f"music{suffix}").write_bytes(data)
    db.merge_meta(pid, {"music": True})
    return {"ok": True, "size": len(data)}


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
