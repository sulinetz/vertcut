"""Загрузка исходного видео через yt-dlp (YouTube, TikTok, Instagram, VK, прямые ссылки)."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .config import ASSETS_DIR, ensure_path, ffmpeg, ffmpeg_bin_dir
from .errors import Cancelled
from .utils import subprocess_kwargs

ProgressCb = Optional[Callable[[float, str], None]]

# YouTube отдаёт форматы по-разному в зависимости от клиента. android_vr обычно
# даёт HD без PO-token, android — стабильный SD-запасной вариант.
CLIENTS_HD = ["android_vr", "android", "tv", "ios", "web"]
CLIENTS_SD = ["android", "tv"]

FORMAT_HD = (
    "bv*[ext=mp4][vcodec^=avc1][height<=1080]+ba[ext=m4a]/"
    "bv*[ext=mp4][height<=1080]+ba[ext=m4a]/"
    "bv*[height<=1080]+ba/"
    "b[height<=1080]/b"
)
FORMAT_SD = "18/b[height<=360][ext=mp4]/b[width<=360][ext=mp4]/b[height<=360]/b[width<=360]/b"


class DownloadError(Exception):
    pass


class StalledDownload(Exception):
    """Скорость упала почти до нуля — переподключаемся."""


def is_youtube(url: str) -> bool:
    try:
        from urllib.parse import urlparse

        host = (urlparse(url).hostname or "").lower()
        return host.endswith("youtube.com") or host.endswith("youtu.be") or host.endswith("youtube-nocookie.com")
    except Exception:
        return False


def _setup_plugins() -> None:
    """Подключаем PO-token плагин из бандла (в .app нет site-packages)."""
    try:
        from yt_dlp.globals import plugin_dirs

        if (ASSETS_DIR / "plugins" / "yt_dlp_plugins").is_dir():
            plugin_dirs.value = [str(ASSETS_DIR)]
    except Exception:
        pass


_setup_plugins()


def _fmt_err(exc: Exception) -> str:
    msg = str(exc)
    low = msg.lower()
    if "sign in" in low or "login" in low or "cookies" in low or "not a bot" in low:
        return ("Сайт требует авторизацию. Включите «Cookies из браузера» в настройках "
                "или загрузите видео файлом.")
    if "needs to be reloaded" in low:
        return ("YouTube запросил повторную загрузку страницы (антибот-проверка). "
                "Нажмите «Повторить обработку»; если не помогает — включите cookies из браузера.")
    if "requested format is not available" in low:
        return ("Источник не отдал выбранное качество. Перезапустите загрузку — "
                "Вайралкат подберёт формат заново.")
    if "no video formats found" in low:
        return "Источник не отдал ни одного видеоформата. Попробуйте другую ссылку или файл."
    if "private" in low:
        return "Видео приватное — доступ запрещён."
    if "age" in low and ("confirm" in low or "restricted" in low):
        return ("Видео с возрастным ограничением: включите «Cookies из браузера» "
                "или загрузите файл вручную.")
    if "unavailable" in low or "not available" in low:
        return "Видео недоступно: удалено, скрыто или заблокировано по региону."
    if "unsupported url" in low:
        return "Ссылка не поддерживается. Проверьте адрес или загрузите файл."
    if "http error 403" in low or "forbidden" in low:
        return ("Источник отклонил загрузку (403). Обычно помогает повторная попытка "
                "или cookies из браузера.")
    if "ffmpeg" in low:
        return f"Ошибка склейки видео через ffmpeg: {msg[-300:]}"
    return msg[-500:]


def _cookie_opts(browser: Optional[str]) -> Dict[str, Any]:
    if not browser:
        return {}
    return {"cookiesfrombrowser": (browser, None, None, None)}


def _clean_partials(dest_dir: Path) -> None:
    for pattern in ("source.*.part", "source.*.ytdl", "source.part", "source.mp4.part"):
        for path in dest_dir.glob(pattern):
            try:
                path.unlink()
            except OSError:
                pass
    for pattern in ("audio.*.part", "audio.part", "audio.*.ytdl", "section.*.part", "section.*.ytdl"):
        for path in dest_dir.glob(pattern):
            try:
                path.unlink()
            except OSError:
                pass


def _pot_enabled() -> bool:
    return bool(os.environ.get("VERTCUT_POT_URL") and os.environ.get("VERTCUT_NODE"))


def _attempt(url: str, dest_dir: Path, fmt: str, clients: Optional[List[str]],
             browser: Optional[str], progress: ProgressCb,
             pot: bool = False, extractor_args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    import yt_dlp

    ensure_path()
    outtmpl = str(dest_dir / "source.%(ext)s")

    timings: Dict[str, Any] = {"download_started": None, "download_finished": None,
                               "merge_started": None, "merge_finished": None,
                               "bytes": 0, "speed": 0.0, "slow_since": None}

    def hook(d: Dict[str, Any]) -> None:
        status = d.get("status")
        if status == "downloading":
            if timings["download_started"] is None:
                timings["download_started"] = time.time()
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            got = d.get("downloaded_bytes") or 0
            pct = (got / total * 100) if total else 0
            speed = float(d.get("speed") or 0)
            if speed:
                timings["speed"] = speed
            timings["bytes"] = max(timings["bytes"], got)
            # автопереподключение при «залипании» на низкой скорости
            now = time.time()
            if speed and speed < 45 * 1024 and pct < 95:
                if timings["slow_since"] is None:
                    timings["slow_since"] = now
                elif now - timings["slow_since"] > 45:
                    raise StalledDownload("скорость ниже 45 КБ/с более 45 секунд")
            else:
                timings["slow_since"] = None
            if progress:
                mb = speed / 1024 / 1024
                speed_txt = f"{mb:.2f} МБ/с ({mb*8:.1f} Мбит/с)" if speed else "…"
                eta = d.get("eta")
                eta_txt = ""
                if eta:
                    eta_txt = f" · осталось {int(eta)//60}:{int(eta)%60:02d}"
                progress(min(pct, 99.0) / 100.0, f"Скачивание {pct:.0f}% · {speed_txt}{eta_txt}")
        elif status == "finished":
            timings["download_finished"] = timings["download_finished"] or time.time()
            if progress:
                progress(0.99, "Дорожки скачаны · объединение через FFmpeg…")

    def pp_hook(d: Dict[str, Any]) -> None:
        if d.get("status") == "started":
            timings["merge_started"] = time.time()
            if progress:
                progress(0.995, "Объединение дорожек (FFmpeg, без перекодирования)")
        elif d.get("status") == "finished":
            timings["merge_finished"] = time.time()

    opts: Dict[str, Any] = {
        "outtmpl": outtmpl,
        "format": fmt,
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "progress_hooks": [hook],
        "postprocessor_hooks": [pp_hook],
        "restrictfilenames": True,
        "retries": 3,
        "fragment_retries": 5,
        "concurrent_fragment_downloads": 4,
        "writesubtitles": False,
        "postprocessors": [{"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}],
        "ffmpeg_location": str(ffmpeg_bin_dir()),
        "socket_timeout": 30,
    }
    if extractor_args:
        opts["extractor_args"] = {k: (list(v) if isinstance(v, list) else v)
                                  for k, v in extractor_args.items()}
    elif clients:
        youtube_args: Dict[str, Any] = {"player_client": clients}
        if pot:
            youtube_args["fetch_pot"] = ["always"]
        opts["extractor_args"] = {"youtube": youtube_args}
    if pot and os.environ.get("VERTCUT_POT_URL"):
        opts.setdefault("extractor_args", {})["youtubepot-bgutilhttp"] = {
            "base_url": [os.environ["VERTCUT_POT_URL"]]}
        if os.environ.get("VERTCUT_NODE"):
            opts["js_runtimes"] = {"node": {"path": os.environ["VERTCUT_NODE"]}}
    opts.update(_cookie_opts(browser))

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)

    if info and "entries" in info:
        entries = [e for e in info["entries"] if e]
        info = entries[0] if entries else info

    candidates = sorted(dest_dir.glob("source.*"), key=lambda p: p.stat().st_size, reverse=True)
    candidates = [p for p in candidates if p.suffix not in (".part", ".ytdl")]
    if not candidates:
        raise DownloadError("Не удалось сохранить видеофайл.")
    path = candidates[0]

    if path.suffix.lower() != ".mp4":
        mp4 = dest_dir / "source.mp4"
        cmd = [ffmpeg(), "-y", "-v", "error", "-i", str(path), "-c", "copy", str(mp4)]
        subprocess.run(cmd, check=False, **subprocess_kwargs())
        if mp4.exists() and mp4.stat().st_size > 0:
            path.unlink(missing_ok=True)
            path = mp4

    info = info or {}
    height = info.get("height")
    vcodec = info.get("vcodec")
    acodec = info.get("acodec")
    fps = info.get("fps")
    selected = info.get("format_id") or ""
    for rf in info.get("requested_formats") or []:
        if rf.get("height"):
            height = max(height or 0, rf["height"])
        if (rf.get("vcodec") or "none") != "none":
            vcodec = rf.get("vcodec")
            fps = rf.get("fps") or fps
        if (rf.get("acodec") or "none") != "none":
            acodec = rf.get("acodec")

    max_height = 0
    for f in info.get("formats") or []:
        if (f.get("vcodec") or "none") != "none" and f.get("height"):
            max_height = max(max_height, int(f["height"]))

    now = time.time()
    download_seconds = None
    if timings["download_started"] and timings["download_finished"]:
        download_seconds = round(timings["download_finished"] - timings["download_started"], 1)
    merge_seconds = None
    if timings["merge_started"] and timings["merge_finished"]:
        merge_seconds = round(timings["merge_finished"] - timings["merge_started"], 1)
    size = path.stat().st_size if path.exists() else 0
    avg_speed = None
    if download_seconds and download_seconds > 0:
        avg_speed = round((timings["bytes"] or size) / download_seconds / 1024 / 1024, 2)

    return {
        "path": path,
        "title": info.get("title") or url,
        "duration": info.get("duration"),
        "uploader": info.get("uploader"),
        "webpage_url": info.get("webpage_url") or url,
        "extractor": info.get("extractor_key"),
        "height": height,
        "max_height": max_height or height,
        "fps": fps,
        "vcodec": vcodec,
        "acodec": acodec,
        "selected_format": selected,
        "filesize": size,
        "download_seconds": download_seconds,
        "merge_seconds": merge_seconds,
        "avg_speed_mbps": avg_speed,
    }



# --- YouTube: подбор рабочего клиента ---------------------------------------

def _youtube_candidates(pot: bool) -> List[tuple[str, Dict[str, Any]]]:
    """Наборы клиентов YouTube в порядке проверки.

    Клиенты YouTube ломаются и чинятся каждые пару недель: «web» требует
    PO-token, «android_vr» отдаёт урезанный список форматов, «tv» иногда просит
    перезагрузить страницу. Поэтому формат спрашиваем у нескольких наборов и
    качаем тем, который реально ответил, — а не угадываем один на всех.
    """
    sets: List[tuple[str, Dict[str, Any]]] = [
        ("по умолчанию", {}),
        ("android", {"youtube": {"player_client": ["android_vr", "android"]}}),
    ]
    if pot:
        sets.append(("PO-token", {"youtube": {"player_client": ["mweb", "web"],
                                              "fetch_pot": ["always"]}}))
    sets.append(("tv/ios", {"youtube": {"player_client": ["tv", "ios"]}}))
    return sets


def _youtube_info(url: str, browser: Optional[str], pot: bool,
                  progress: ProgressCb = None) -> tuple[Dict[str, Any], Dict[str, Any], str]:
    """Метаданные от первого набора клиентов, который отдал форматы."""
    import yt_dlp

    ensure_path()
    errors: List[str] = []
    for label, args in _youtube_candidates(pot):
        opts: Dict[str, Any] = {
            "quiet": True, "no_warnings": True, "skip_download": True,
            "noplaylist": True, "socket_timeout": 30,
        }
        if args:
            opts["extractor_args"] = {k: dict(v) for k, v in args.items()}
        if pot and os.environ.get("VERTCUT_POT_URL"):
            opts.setdefault("extractor_args", {})["youtubepot-bgutilhttp"] = {
                "base_url": [os.environ["VERTCUT_POT_URL"]]}
            if os.environ.get("VERTCUT_NODE"):
                opts["js_runtimes"] = {"node": {"path": os.environ["VERTCUT_NODE"]}}
        opts.update(_cookie_opts(browser))
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{label}: {str(exc)[-160:]}")
            print(f"[youtube] клиент «{label}» не сработал: {exc}", file=sys.stderr)
            continue
        if not info:
            errors.append(f"{label}: пустой ответ")
            continue
        if "entries" in info:
            entries = [e for e in info["entries"] if e]
            info = entries[0] if entries else info
        formats = info.get("formats") or []
        if not formats:
            errors.append(f"{label}: нет форматов")
            continue
        if progress:
            progress(0.02, f"Источник ответил ({label})")
        print(f"[youtube] клиент «{label}»: {len(formats)} форматов", file=sys.stderr)
        return info, args, label
    detail = " | ".join(errors[-2:])
    raise DownloadError("YouTube не отдал видео ни одному клиенту. " + detail[-350:])


def _pick_format(info: Dict[str, Any], max_height: int) -> tuple[str, int]:
    """Формат из фактически доступных — вместо «слепой» строки селектора.

    Возвращает (селектор, реальная высота): подпись в интерфейсе должна
    показывать то качество, которое источник действительно отдал.
    """
    formats = [f for f in (info.get("formats") or []) if f.get("format_id")]
    videos = [f for f in formats if (f.get("vcodec") or "none") != "none" and f.get("height")]
    if not videos:
        return (FORMAT_HD if max_height > 360 else FORMAT_SD), 0
    fitting = [f for f in videos if int(f.get("height") or 0) <= max_height] or videos

    def rank(f: Dict[str, Any]) -> tuple:
        codec = f.get("vcodec") or ""
        return (
            1 if codec.startswith("avc1") else 0,
            1 if f.get("ext") == "mp4" else 0,
            1 if (f.get("acodec") or "none") != "none" else 0,
            int(f.get("height") or 0),
        )

    video = max(fitting, key=rank)
    height = int(video.get("height") or 0)
    if (video.get("acodec") or "none") != "none":
        return str(video["format_id"]), height
    audios = [f for f in formats
              if (f.get("vcodec") or "none") == "none" and (f.get("acodec") or "none") != "none"]
    if audios:
        audio = max(audios, key=lambda f: (1 if f.get("ext") == "m4a" else 0,
                                           float(f.get("abr") or f.get("tbr") or 0)))
        return f"{video['format_id']}+{audio['format_id']}", height
    return str(video["format_id"]), height


def download(url: str, dest_dir: Path, progress: ProgressCb = None,
             browser: Optional[str] = None, max_height: int = 1080,
             force_hd: bool = False) -> Dict[str, Any]:
    """Скачивает видео. По умолчанию цель — 1080p, при блокировке видимый откат к SD."""
    dest_dir.mkdir(parents=True, exist_ok=True)

    if max_height <= 360:
        hd_format = FORMAT_SD
    else:
        # width-варианты нужны для вертикальных видео (Shorts, Twitter): у них
        # «height» — длинная сторона, и фильтр height<=1080 отбрасывает 1080p.
        hd_format = (
            f"bv*[ext=mp4][vcodec^=avc1][height<={max_height}]+ba[ext=m4a]/"
            f"bv*[ext=mp4][vcodec^=avc1][width<={max_height}]+ba[ext=m4a]/"
            f"bv*[ext=mp4][height<={max_height}]+ba[ext=m4a]/"
            f"bv*[ext=mp4][width<={max_height}]+ba[ext=m4a]/"
            f"bv*[height<={max_height}]+ba/bv*[width<={max_height}]+ba/"
            f"b[height<={max_height}]/b[width<={max_height}]/b"
        )

    attempts: List[tuple] = []
    if not is_youtube(url):
        # Twitter/VK/TikTok: сначала пробуем прямой HTTPS-файл — он качается одним
        # потоком и не требует склейки HLS-фрагментов (в разы быстрее).
        direct = f"b[width<={max_height}]/b[height<={max_height}]/b"
        attempts.append((f"{max_height}p", None, direct + "/" + hd_format, False, None))
        if not force_hd:
            attempts.append(("SD", None, FORMAT_SD, False, None))
    else:
        pot = _pot_enabled()
        # Сначала спрашиваем форматы у нескольких клиентов и качаем выбранным.
        picked = None
        try:
            info, args, client_label = _youtube_info(url, browser, pot, progress)
            picked = (_pick_format(info, max_height), args, client_label)
        except DownloadError as exc:
            print(f"[youtube] метаданные не получены: {exc}", file=sys.stderr)
        if picked is not None:
            (fmt, real_height), args, client_label = picked
            pot_args = bool(args and "fetch_pot" in str(args))
            label_height = real_height or max_height
            attempts.append((f"{label_height}p · {client_label}", None, fmt,
                             pot_args and pot, args))
        if force_hd:
            if not attempts:
                raise DownloadError(
                    "YouTube не отдал HD-форматы. Перезапустите загрузку; "
                    "если повторяется — включите «Cookies из браузера».")
            attempts = attempts[:1]
        else:
            attempts += [
                ("SD", None, FORMAT_SD, False, None),
                ("резервный клиент", None, hd_format, False, None),
            ]

    last_error: Optional[Exception] = None
    failed_reasons: List[str] = []
    for idx, (label, clients, fmt, pot, extra_args) in enumerate(attempts):
        if idx > 0:
            _clean_partials(dest_dir)
        try:
            if progress:
                progress(0.01, f"Скачивание ({label})")
            meta = None
            for reconnect in range(2):
                try:
                    meta = _attempt(url, dest_dir, fmt, clients, browser, progress,
                                    pot=pot, extractor_args=extra_args)
                    break
                except StalledDownload as exc:
                    print(f"download stalled ({exc}); reconnecting", file=sys.stderr)
                    if progress:
                        progress(0.01, "Скорость упала · переподключаюсь к источнику…")
                    if reconnect == 1:
                        raise
            assert meta is not None
            meta["quality"] = label
            meta["fallback"] = bool(failed_reasons)
            meta["fallback_reason"] = failed_reasons[0] if failed_reasons else None
            print(f"download ok: {label} height={meta.get('height')} format={meta.get('selected_format')}",
                  file=sys.stderr)
            return meta
        except Cancelled:
            raise
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            failed_reasons.append(_fmt_err(exc))
            print(f"download attempt {label} failed: {exc}", file=sys.stderr)
            if idx == len(attempts) - 1:
                break
            if progress and not force_hd:
                progress(0.01, f"{label} не удалось · пробую ниже качеством")

    reason = _fmt_err(last_error or DownloadError("Не удалось скачать видео"))
    if force_hd:
        raise DownloadError(reason)
    raise DownloadError(reason)


def download_file(url: str, dest_dir: Path, progress: ProgressCb = None) -> Dict[str, Any]:
    """Прямая ссылка на mp4/webm/mov без yt-dlp."""
    import urllib.request

    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / "source.mp4"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, open(path, "wb") as fh:
            total = int(resp.headers.get("Content-Length") or 0)
            got = 0
            while True:
                chunk = resp.read(1024 * 512)
                if not chunk:
                    break
                fh.write(chunk)
                got += len(chunk)
                if progress and total:
                    progress(min(got / total, 0.99), f"Скачивание {got/total*100:.0f}%")
    except Exception as exc:  # noqa: BLE001
        raise DownloadError(f"Не удалось скачать файл по ссылке: {exc}") from exc
    return {"path": path, "title": Path(url.split("?")[0]).name or "video", "duration": None,
            "uploader": None, "webpage_url": url, "extractor": "direct", "quality": "file",
            "height": None}


def fetch_subtitles(url: str, dest_dir: Path, browser: Optional[str] = None) -> Optional[str]:
    """Пробует скачать готовые субтитры (ru/en) — резервный путь без Whisper."""
    import yt_dlp

    ensure_path()
    opts: Dict[str, Any] = {
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["ru", "en"],
        "subtitlesformat": "vtt",
        "outtmpl": str(dest_dir / "subs.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
    }
    opts.update(_cookie_opts(browser))
    for client in (None, ["android_vr", "android"]):
        attempt = dict(opts)
        if client:
            attempt["extractor_args"] = {"youtube": {"player_client": client}}
        try:
            with yt_dlp.YoutubeDL(attempt) as ydl:
                ydl.download([url])
        except Exception:  # noqa: BLE001
            continue
        files = sorted(dest_dir.glob("subs*.vtt"))
        if files:
            return str(files[0])
    return None


def is_direct_media(url: str) -> bool:
    return bool(re.search(r"\.(mp4|mov|webm|mkv|m4v)(\?|$)", url, re.I))


def _pot_token(content_binding: str = "") -> Optional[str]:
    """Запрашивает GVS PO-token у локального провайдера."""
    base = os.environ.get("VERTCUT_POT_URL")
    if not base:
        return None
    try:
        import json
        import urllib.request

        body = json.dumps({"content_binding": content_binding}).encode()
        req = urllib.request.Request(base.rstrip("/") + "/get_pot", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=45) as resp:
            return json.loads(resp.read().decode()).get("poToken")
    except Exception:
        return None


def probe(url: str, browser: Optional[str] = None) -> Dict[str, Any]:
    """Метаданные и оценки размера по качествам — без скачивания видео."""
    import yt_dlp

    ensure_path()
    opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "socket_timeout": 30,
        "extractor_args": {},
    }
    if is_youtube(url):
        # Раньше здесь жёстко включался PO-token-клиент; когда он перестаёт
        # отвечать, «недоступно» показывалось на любую ссылку. Теперь идём тем же
        # перебором клиентов, что и загрузка.
        info, _args, _label = _youtube_info(url, browser, _pot_enabled())
    else:
        node = os.environ.get("VERTCUT_NODE")
        if node:
            opts["js_runtimes"] = {"node": {"path": node}}
        opts.update(_cookie_opts(browser))
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

    if info and "entries" in info:
        entries = [e for e in info["entries"] if e]
        info = entries[0] if entries else info
    duration = float(info.get("duration") or 0)
    formats = info.get("formats") or []

    def estimate(video: Dict[str, Any], audio: Optional[Dict[str, Any]]) -> int:
        def part(fmt: Optional[Dict[str, Any]]) -> int:
            if not fmt:
                return 0
            size = int(fmt.get("filesize") or fmt.get("filesize_approx") or 0)
            if size <= 0:
                tbr = float(fmt.get("tbr") or 0)
                if tbr and duration:
                    size = int(tbr * 1000 / 8 * duration)
            if size <= 0 and duration:
                guess = {1080: 5.5, 720: 3.0, 480: 1.6, 360: 0.9}.get(
                    min((1080, 720, 480, 360),
                        key=lambda h: abs(h - (fmt.get("height") or 720))), 3.0)
                size = int(guess * 1000 * 1000 / 8 * duration)
            return max(0, size)

        return part(video) + part(audio)

    # Предлагаем только те ступени, которые источник реально отдаёт: иначе для
    # ролика 240p интерфейс обещал 1080p и подставлял размер 240p.
    video_heights = [int(f["height"]) for f in formats
                     if f.get("height") and (f.get("vcodec") or "none") != "none"]
    max_available = max(video_heights) if video_heights else 0
    steps = [h for h in (1080, 720, 360) if h <= max_available] or ([max_available] if max_available else [])

    options = []
    for height in steps:
        vids = [f for f in formats if f.get("height") and int(f["height"]) <= height]
        if not vids:
            continue
        def vscore(f: Dict[str, Any]) -> tuple:
            codec = (f.get("vcodec") or "")
            return (f.get("height") or 0,
                    1 if (f.get("ext") == "mp4" and codec.startswith("avc1")) else 0,
                    1 if (f.get("filesize") or f.get("filesize_approx")) else 0,
                    0 if codec.startswith("av01") else 1,
                    f.get("tbr") or 0)

        video = max(vids, key=vscore)
        audios = [f for f in formats
                  if (f.get("acodec") or "none") not in ("none",)
                  and (f.get("vcodec") or "none") in ("none",)
                  and (f.get("filesize") or f.get("filesize_approx") or f.get("tbr"))]
        audio = max(audios, key=lambda f: f.get("abr") or f.get("tbr") or 0) if audios else None
        size = estimate(video, audio)
        options.append({"height": height, "size": size,
                        "size_mb": round(size / 1024 / 1024) if size else 0,
                        "format_id": video.get("format_id")})

    if not options:
        raise DownloadError("Не удалось получить форматы видео.")

    recommended = 1080
    if duration > 5400:
        recommended = 360
    elif duration > 3600:
        recommended = 720
    elif options and options[0]["size_mb"] > 900:
        recommended = 720 if len(options) > 1 else options[0]["height"]
    available = {o["height"] for o in options}
    if recommended not in available:
        recommended = min(available, key=lambda h: abs(h - recommended))

    for o in options:
        o["recommended"] = o["height"] == recommended

    audio_only = [f for f in formats
                  if (f.get("acodec") or "none") not in ("none",)
                  and (f.get("vcodec") or "none") in ("none",)]
    audio_size = 0
    for a in audio_only:
        size = int(a.get("filesize") or a.get("filesize_approx") or 0)
        if not size and a.get("tbr") and duration:
            size = int(float(a["tbr"]) * 1000 / 8 * duration)
        audio_size = max(audio_size, size)

    return {
        "title": info.get("title") or url,
        "duration": duration,
        "thumbnail": info.get("thumbnail"),
        "uploader": info.get("uploader"),
        "options": options,
        "recommended": recommended,
        "audio_size_mb": round(audio_size / 1024 / 1024) if audio_size else 0,
    }


AUDIO_FORMAT = "ba[abr<=64]/ba[abr<=96]/ba/b[height<=360]/b"


def download_audio(url: str, dest_dir: Path, progress: ProgressCb = None,
                   browser: Optional[str] = None) -> Dict[str, Any]:
    """Скачивает только звук — в разы меньше полного видео."""
    import yt_dlp

    ensure_path()
    dest_dir.mkdir(parents=True, exist_ok=True)
    outtmpl = str(dest_dir / "audio.%(ext)s")
    timings = {"started": None, "finished": None, "bytes": 0, "slow_since": None}

    def hook(d: Dict[str, Any]) -> None:
        if d.get("status") == "downloading":
            if timings["started"] is None:
                timings["started"] = time.time()
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            got = d.get("downloaded_bytes") or 0
            timings["bytes"] = max(timings["bytes"], got)
            speed = float(d.get("speed") or 0)
            pct_raw = (got / total * 100) if total else 0
            now = time.time()
            if speed and speed < 45 * 1024 and pct_raw < 95:
                if timings["slow_since"] is None:
                    timings["slow_since"] = now
                elif now - timings["slow_since"] > 45:
                    raise StalledDownload("аудио: скорость ниже 45 КБ/с")
            else:
                timings["slow_since"] = None
            pct = (got / total * 100) if total else 0
            if progress:
                mb = speed / 1024 / 1024
                sp = f"{mb:.2f} МБ/с" if speed else "…"
                progress(min(pct, 99) / 100.0, f"Скачивание аудио {pct:.0f}% · {sp}")
        elif d.get("status") == "finished":
            timings["finished"] = time.time()
            if progress:
                progress(0.99, "Аудио скачано · распознавание речи")

    opts: Dict[str, Any] = {
        "outtmpl": outtmpl,
        "format": AUDIO_FORMAT,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "progress_hooks": [hook],
        "retries": 3,
        "fragment_retries": 5,
        "concurrent_fragment_downloads": 4,
        "ffmpeg_location": str(ffmpeg_bin_dir()),
        "socket_timeout": 30,
    }
    if is_youtube(url) and _pot_enabled() and os.environ.get("VERTCUT_POT_URL"):
        opts["extractor_args"] = {
            "youtube": {"player_client": ["mweb", "web"], "fetch_pot": ["always"]},
            "youtubepot-bgutilhttp": {"base_url": [os.environ["VERTCUT_POT_URL"]]},
        }
        if os.environ.get("VERTCUT_NODE"):
            opts["js_runtimes"] = {"node": {"path": os.environ["VERTCUT_NODE"]}}
    opts.update(_cookie_opts(browser))
    info = None
    for reconnect in range(2):
        try:
            if progress:
                progress(0.01, "Скачивание аудио")
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
            break
        except StalledDownload:
            if reconnect == 1:
                raise
            if progress:
                progress(0.01, "Скорость упала · переподключаюсь к источнику…")
    if info and "entries" in info:
        entries = [e for e in info["entries"] if e]
        info = entries[0] if entries else info
    candidates = [p for p in dest_dir.glob("audio.*") if p.suffix not in (".part", ".ytdl")]
    if not candidates:
        raise DownloadError("Не удалось скачать аудио.")
    path = max(candidates, key=lambda p: p.stat().st_size)
    duration = float((info or {}).get("duration") or 0)
    return {
        "path": path, "title": (info or {}).get("title"), "duration": duration,
        "uploader": (info or {}).get("uploader"), "size": path.stat().st_size,
        "download_seconds": round((timings["finished"] or 0) - (timings["started"] or 0), 1)
        if timings["started"] else None,
    }


def download_section(url: str, dest_dir: Path, start: float, end: float,
                     progress: ProgressCb = None, browser: Optional[str] = None,
                     max_height: int = 1080) -> Path:
    """Скачивает только фрагмент видео (для экономного режима)."""
    import yt_dlp
    from yt_dlp.utils import download_range_func

    ensure_path()
    dest_dir.mkdir(parents=True, exist_ok=True)
    outtmpl = str(dest_dir / "section.%(ext)s")
    if max_height <= 360:
        fmt = FORMAT_SD
    else:
        fmt = (
            f"bv*[ext=mp4][vcodec^=avc1][height<={max_height}]+ba[ext=m4a]/"
            f"bv*[ext=mp4][vcodec^=avc1][width<={max_height}]+ba[ext=m4a]/"
            f"bv*[ext=mp4][height<={max_height}]+ba[ext=m4a]/"
            f"bv*[ext=mp4][width<={max_height}]+ba[ext=m4a]/"
            f"bv*[height<={max_height}]+ba/bv*[width<={max_height}]+ba/"
            f"b[height<={max_height}]/b[width<={max_height}]/b"
        )
    if not is_youtube(url):
        fmt = f"b[width<={max_height}]/b[height<={max_height}]/b/" + fmt

    def hook(d: Dict[str, Any]) -> None:
        if d.get("status") == "downloading" and progress:
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            got = d.get("downloaded_bytes") or 0
            pct = (got / total * 100) if total else 0
            progress(min(pct, 99) / 100.0, "Скачивание момента")
        elif d.get("status") == "finished" and progress:
            progress(0.99, "Момент скачан · рендер")

    formats = [fmt]
    if is_youtube(url):
        formats.append(FORMAT_SD)

    last_error: Optional[Exception] = None
    for fi, fmt_try in enumerate(formats):
        _clean_partials(dest_dir)
        opts: Dict[str, Any] = {
            "outtmpl": outtmpl,
            "format": fmt_try,
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "progress_hooks": [hook],
            "retries": 3,
            "fragment_retries": 5,
            "concurrent_fragment_downloads": 2,
            "download_ranges": download_range_func(None, [(start, end)]),
            "force_keyframes_at_cuts": True,
            "ffmpeg_location": str(ffmpeg_bin_dir()),
            "socket_timeout": 30,
        }
        if is_youtube(url):
            if _pot_enabled():
                opts["extractor_args"] = {
                    "youtube": {"player_client": ["mweb", "web"], "fetch_pot": ["always"]},
                    "youtubepot-bgutilhttp": {"base_url": [os.environ["VERTCUT_POT_URL"]]},
                }
                opts["js_runtimes"] = {"node": {"path": os.environ["VERTCUT_NODE"]}}
            else:
                opts["extractor_args"] = {"youtube": {"player_client": ["android", "tv"]}}
        opts.update(_cookie_opts(browser))
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(url, download=True)
            if any(p.suffix not in (".part", ".ytdl") for p in dest_dir.glob("section.*")):
                break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if fi + 1 >= len(formats):
                raise

    candidates = [p for p in dest_dir.glob("section.*") if p.suffix not in (".part", ".ytdl")]
    if not candidates:
        raise DownloadError("Не удалось скачать фрагмент видео.")
    path = max(candidates, key=lambda p: p.stat().st_size)
    if path.suffix.lower() != ".mp4":
        mp4 = dest_dir / "section.mp4"
        subprocess.run([ffmpeg(), "-y", "-v", "error", "-i", str(path), "-c", "copy", str(mp4)],
                       check=False, **subprocess_kwargs())
        if mp4.exists() and mp4.stat().st_size > 0:
            path.unlink(missing_ok=True)
            path = mp4
    return path
