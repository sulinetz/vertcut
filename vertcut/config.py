"""Конфигурация и общие пути приложения."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
ASSETS_DIR = ROOT / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"

DATA_DIR = Path(os.environ.get("VERTCUT_DATA", ROOT / "data")).resolve()


def resolve_projects_dir(data_dir: Path) -> Path:
    """Папка с тяжёлыми проектами: можно вынести на другой диск.

    Приоритет: `VERTCUT_PROJECTS` / `VERTCUT_PROJECTS_DIR` → файл
    `projects_dir.txt` в папке данных → `<данные>/projects`. Файл нужен для
    собранного приложения: его не запускают из консоли с переменными.
    """
    raw = (os.environ.get("VERTCUT_PROJECTS")
           or os.environ.get("VERTCUT_PROJECTS_DIR") or "").strip()
    if not raw:
        marker = data_dir / "projects_dir.txt"
        try:
            raw = marker.read_text(encoding="utf-8").strip()
        except OSError:
            raw = ""
    if not raw:
        return (data_dir / "projects").resolve()
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = data_dir / path
    return path.resolve()


PROJECTS_DIR = resolve_projects_dir(DATA_DIR)
MODELS_DIR = DATA_DIR / "models"
DB_PATH = DATA_DIR / "vertcut.db"

# Временные файлы больших загрузок и ffmpeg держим рядом с проектами, а не
# на системном диске. Иначе 20-гигабайтный файл сначала целиком ложится в TMP.
TEMP_DIR = Path(os.environ.get("VERTCUT_TEMP", PROJECTS_DIR.parent / "temp")).resolve()

PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
MODELS_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)
for _var in ("TMP", "TEMP", "TMPDIR"):
    os.environ[_var] = str(TEMP_DIR)
try:
    import tempfile as _tempfile

    _tempfile.tempdir = str(TEMP_DIR)
except Exception:  # noqa: BLE001
    pass

# Размер модели Whisper: tiny / base / small / medium / large-v3
WHISPER_MODEL = os.environ.get("VERTCUT_WHISPER", "small")
WHISPER_LOCAL_DIR = os.environ.get("VERTCUT_WHISPER_DIR", "")
WHISPER_DEVICE = os.environ.get("VERTCUT_DEVICE", "auto")
# CPU: int8 — самый быстрый вариант без видеокарты.
WHISPER_COMPUTE = os.environ.get("VERTCUT_COMPUTE", "int8")
# GPU: float16 по умолчанию. Явный VERTCUT_COMPUTE имеет приоритет.
WHISPER_CUDA_COMPUTE = os.environ.get(
    "VERTCUT_CUDA_COMPUTE", os.environ.get("VERTCUT_COMPUTE") or "float16")

MAX_WORKERS = int(os.environ.get("VERTCUT_WORKERS", "1"))

_ffmpeg_cache: Optional[str] = None
_ffmpeg_dir_cache: Optional[Path] = None


def ffmpeg() -> str:
    """Путь к ffmpeg: env override -> imageio-ffmpeg (статическая сборка) -> PATH."""
    global _ffmpeg_cache
    if _ffmpeg_cache:
        return _ffmpeg_cache
    env = os.environ.get("VERTCUT_FFMPEG")
    if env and Path(env).exists():
        _ffmpeg_cache = env
        return env
    try:
        import imageio_ffmpeg

        _ffmpeg_cache = imageio_ffmpeg.get_ffmpeg_exe()
        return _ffmpeg_cache
    except Exception:
        pass
    found = shutil.which("ffmpeg")
    if not found:
        raise RuntimeError("ffmpeg не найден. Установите ffmpeg или пакет imageio-ffmpeg.")
    _ffmpeg_cache = found
    return found


def ffmpeg_bin_dir() -> Path:
    """Папка с бинарником ffmpeg под именем ffmpeg (нужно yt-dlp для склейки)."""
    global _ffmpeg_dir_cache
    if _ffmpeg_dir_cache is not None:
        return _ffmpeg_dir_cache
    bin_dir = DATA_DIR / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    # yt-dlp на Windows ищет именно ffmpeg.exe.
    link = bin_dir / ("ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg")
    target = Path(ffmpeg())
    valid = False
    if link.exists():
        try:
            valid = Path(os.readlink(link)) == target if link.is_symlink() else link.stat().st_size > 0
        except OSError:
            valid = False
    if not valid:
        try:
            link.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            link.symlink_to(target)
        except OSError:
            shutil.copy2(target, link)
            link.chmod(0o755)
    _ffmpeg_dir_cache = bin_dir
    return bin_dir


def ensure_path() -> None:
    """Добавляет папку с ffmpeg в PATH — yt-dlp ищет его там."""
    bin_dir = str(ffmpeg_bin_dir())
    if bin_dir not in os.environ.get("PATH", "").split(os.pathsep):
        os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
