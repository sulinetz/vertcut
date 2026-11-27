"""Библиотека рекламных ассетов и события на таймлайне клипа.

Ассеты глобальные: лежат в `DATA_DIR/ads`, индекс — `index.json` под lock.
Проект хранит только id ассета и позиции событий, сами файлы не копируются.
Изображения проверяются Pillow, видео — ffprobe; имена санитайзятся.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from . import utils
from .config import ASSETS_DIR, DATA_DIR

ADS_DIR = DATA_DIR / "ads"
INDEX_PATH = ADS_DIR / "index.json"
LOCK = threading.RLock()

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
VIDEO_SUFFIXES = {".mp4", ".webm", ".mov", ".mkv", ".m4v"}
ANIMATIONS = ("none", "fade", "slide", "scale")
KEY_COLORS = ("none", "green", "black")
KINDS = ("image", "video", "text")
MAX_EVENTS = 40
MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_VIDEO_BYTES = 300 * 1024 * 1024


def ensure_dirs() -> None:
    ADS_DIR.mkdir(parents=True, exist_ok=True)


def _empty_index() -> Dict[str, Any]:
    return {"version": 1, "assets": {}}


def _read_index() -> Dict[str, Any]:
    try:
        raw = INDEX_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, dict) and isinstance(data.get("assets"), dict):
            return data
    except (OSError, ValueError):
        pass
    return _empty_index()


def _write_index(data: Dict[str, Any]) -> None:
    ensure_dirs()
    temp = INDEX_PATH.with_suffix(".json.tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, INDEX_PATH)


def clean_name(value: str, fallback: str = "ассет") -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "", text)
    return (text[:80] or fallback).strip()


def _public(asset: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(asset)
    item["url"] = f"/api/ads/{asset['id']}/file"
    return item


def list_assets() -> List[Dict[str, Any]]:
    with LOCK:
        assets = list(_read_index()["assets"].values())
    assets.sort(key=lambda a: (-float(a.get("created") or 0), a.get("name") or ""))
    return [_public(a) for a in assets]


def get_asset(asset_id: str) -> Optional[Dict[str, Any]]:
    with LOCK:
        asset = _read_index()["assets"].get(str(asset_id or ""))
    return dict(asset) if isinstance(asset, dict) else None


def asset_path(asset_id: str) -> Optional[Path]:
    asset = get_asset(asset_id)
    if not asset:
        return None
    path = ADS_DIR / str(asset.get("file") or "")
    try:
        path.resolve().relative_to(ADS_DIR.resolve())
    except (OSError, ValueError):
        return None
    return path if path.is_file() else None


def _new_id(existing: Dict[str, Any]) -> str:
    while True:
        value = uuid.uuid4().hex[:12]
        if value not in existing:
            return value


def _kind_for_suffix(suffix: str) -> str:
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix in VIDEO_SUFFIXES:
        return "video"
    return ""


def _gif_duration(image: Any) -> float:
    """Суммарная длительность кадров GIF в секундах."""
    try:
        from PIL import ImageSequence

        total_ms = 0
        for frame in ImageSequence.Iterator(image):
            step = int(frame.info.get("duration") or 0)
            total_ms += step if step > 0 else 100
        return round(total_ms / 1000.0, 2)
    except Exception:  # noqa: BLE001
        return 0.0


def add_file(filename: str, source: Path, name: Optional[str] = None) -> Dict[str, Any]:
    """Добавляет картинку, GIF или короткое видео в библиотеку."""
    suffix = Path(filename or "").suffix.lower()
    kind = _kind_for_suffix(suffix)
    if not kind:
        raise ValueError("Нужен PNG, JPG, WEBP, GIF или видео MP4/WEBM/MOV/MKV")
    size = source.stat().st_size
    limit = MAX_IMAGE_BYTES if kind == "image" else MAX_VIDEO_BYTES
    if size > limit:
        raise ValueError(f"Файл больше {limit // (1024 * 1024)} МБ")
    info: Dict[str, Any] = {"width": 0, "height": 0, "duration": 0.0,
                           "animated": False, "frames": 1}
    if kind == "image":
        try:
            from PIL import Image

            with Image.open(source) as image:
                image.verify()
            with Image.open(source) as image:
                frames = int(getattr(image, "n_frames", 1) or 1)
                animated = suffix == ".gif" and frames > 1
                gif_dur = _gif_duration(image) if animated else 0.0
                info = {"width": int(image.width), "height": int(image.height),
                        "duration": gif_dur, "animated": animated, "frames": frames}
            if suffix == ".gif" and info["duration"] <= 0:
                try:
                    probed = utils.probe(source)
                    info["duration"] = round(float(probed.get("duration") or 0), 2)
                except Exception:  # noqa: BLE001
                    pass
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Не удалось прочитать изображение: {str(exc)[:120]}") from exc
    else:
        try:
            probed = utils.probe(source)
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Не удалось прочитать видео: {str(exc)[:120]}") from exc
        info = {"width": int(probed.get("width") or 0),
                "height": int(probed.get("height") or 0),
                "duration": round(float(probed.get("duration") or 0), 2),
                "animated": False, "frames": 0}
        if info["duration"] <= 0:
            raise ValueError("В видео нет длительности")

    ensure_dirs()
    with LOCK:
        data = _read_index()
        asset_id = _new_id(data["assets"])
        target = ADS_DIR / f"{asset_id}{suffix}"
        shutil.copyfile(source, target)
        asset = {
            "id": asset_id,
            "name": clean_name(name or Path(filename).stem),
            "kind": kind,
            "file": target.name,
            "width": info["width"],
            "height": info["height"],
            "duration": info["duration"],
            "animated": bool(info.get("animated")),
            "frames": int(info.get("frames") or 0),
            "size": target.stat().st_size,
            "created": round(time.time(), 3),
        }
        data["assets"][asset_id] = asset
        _write_index(data)
    return _public(asset)


def is_animated_footage(asset: Dict[str, Any]) -> bool:
    """Подходит ли ассет для «random» футажа (видео или GIF, но не статичная картинка)."""
    if not isinstance(asset, dict):
        return False
    if asset.get("kind") == "video":
        return True
    name = str(asset.get("file") or "").lower()
    return asset.get("kind") == "image" and (bool(asset.get("animated")) or name.endswith(".gif"))


def pick_random_footage(seed_key: str) -> Optional[Dict[str, Any]]:
    """Детерминированный выбор видео/GIF футажа по ключу клипа."""
    candidates = [a for a in list_assets() if is_animated_footage(a)]
    if not candidates:
        return None
    candidates.sort(key=lambda a: str(a.get("id") or ""))
    digest = hashlib.sha256(str(seed_key or "").encode("utf-8")).digest()
    idx = int.from_bytes(digest[:8], "big") % len(candidates)
    return candidates[idx]


def add_text(text: str, color: str = "#FFFFFF", background: str = "#00000000",
             font_size: int = 64, name: str = "") -> Dict[str, Any]:
    """Текст и плашки рендерим в PNG: drawtext на Windows ненадёжен."""
    text = str(text or "").strip()
    if not text:
        raise ValueError("Пустой текст")
    if len(text) > 300:
        raise ValueError("Текст длиннее 300 символов")
    font_size = max(18, min(160, int(font_size or 64)))
    ensure_dirs()

    from PIL import Image, ImageDraw, ImageFont

    font = None
    fonts = ASSETS_DIR / "fonts"
    for candidate in ("Manrope-ExtraBold.ttf", "GolosText-Bold.ttf",
                      "Inter-Black.ttf", "Comfortaa-Bold.ttf"):
        path = fonts / candidate
        if path.is_file():
            try:
                font = ImageFont.truetype(str(path), font_size)
                break
            except OSError:
                continue
    if font is None:
        font = ImageFont.load_default()

    # Перенос по словам: длинную строку проще читать в вертикальном ролике.
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    max_width = 900
    lines: List[str] = []
    current = ""
    for word in text.split():
        trial = (current + " " + word).strip()
        box = probe.textbbox((0, 0), trial, font=font)
        if current and box[2] - box[0] > max_width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    line_height = int(font_size * 1.25)
    widths = [probe.textbbox((0, 0), line, font=font)[2] for line in lines] or [1]
    width = min(max(max(widths) + font_size, font_size * 2), max_width + font_size * 2)
    height = line_height * len(lines) + font_size
    image = Image.new("RGBA", (width, height), background)
    draw = ImageDraw.Draw(image)
    y = font_size // 2
    for line in lines:
        box = draw.textbbox((0, 0), line, font=font)
        draw.text(((width - (box[2] - box[0])) // 2, y), line, font=font, fill=color)
        y += line_height

    with LOCK:
        data = _read_index()
        asset_id = _new_id(data["assets"])
        target = ADS_DIR / f"{asset_id}.png"
        image.save(target, "PNG")
        asset = {
            "id": asset_id,
            "name": clean_name(name or text[:40], "текст"),
            "kind": "text",
            "file": target.name,
            "width": width,
            "height": height,
            "duration": 0.0,
            "size": target.stat().st_size,
            "created": round(time.time(), 3),
            "text": text[:300],
        }
        data["assets"][asset_id] = asset
        _write_index(data)
    return _public(asset)


def rename(asset_id: str, name: str) -> Dict[str, Any]:
    with LOCK:
        data = _read_index()
        asset = data["assets"].get(str(asset_id or ""))
        if not asset:
            raise KeyError(asset_id)
        asset["name"] = clean_name(name, "ассет")
        _write_index(data)
        return _public(asset)


def delete(asset_id: str) -> bool:
    with LOCK:
        data = _read_index()
        asset = data["assets"].pop(str(asset_id or ""), None)
        if not asset:
            return False
        path = ADS_DIR / str(asset.get("file") or "")
        try:
            path.resolve().relative_to(ADS_DIR.resolve())
            path.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass
        _write_index(data)
    return True


def _as_float(value: Any, default: float, low: float, high: float) -> float:
    try:
        return round(max(low, min(high, float(value))), 3)
    except (TypeError, ValueError):
        return default


def normalize_events(events: Any, known: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
    """Проверка событий: числа в диапазонах, типы, id ассетов."""
    if not isinstance(events, (list, tuple)):
        return []
    allowed = set(known) if known is not None else None
    out: List[Dict[str, Any]] = []
    for raw in events:
        if not isinstance(raw, dict):
            continue
        asset = str(raw.get("asset") or "").strip()
        if not asset or (allowed is not None and asset not in allowed):
            continue
        kind = str(raw.get("kind") or "overlay").strip().lower()
        if kind not in ("overlay", "replace"):
            continue
        event = {
            "id": str(raw.get("id") or uuid.uuid4().hex[:10])[:40],
            "asset": asset,
            "kind": kind,
            "start": _as_float(raw.get("start"), 0.0, 0.0, 7200.0),
            "duration": _as_float(raw.get("duration"), 1.0, 0.2, 300.0),
            "x": _as_float(raw.get("x"), 0.66, 0.0, 1.0),
            "y": _as_float(raw.get("y"), 0.05, 0.0, 1.0),
            "w": _as_float(raw.get("w"), 0.28, 0.02, 1.0),
            "h": _as_float(raw.get("h"), 0.28, 0.02, 1.0),
            "opacity": _as_float(raw.get("opacity"), 1.0, 0.0, 1.0),
            "anim_in": str(raw.get("anim_in") or "none").strip().lower(),
            "anim_out": str(raw.get("anim_out") or "none").strip().lower(),
            "anim_dur": _as_float(raw.get("anim_dur"), 0.3, 0.0, 2.0),
            "z": int(_as_float(raw.get("z"), 0.0, -50.0, 100.0)),
            "volume": _as_float(raw.get("volume"), 1.0, 0.0, 1.0),
            "key_color": str(raw.get("key_color") or "none").strip().lower(),
        }
        if event["key_color"] not in KEY_COLORS:
            event["key_color"] = "none"
        for key in ("anim_in", "anim_out"):
            if event[key] not in ANIMATIONS:
                event[key] = "none"
        if event["anim_dur"] <= 0:
            event["anim_in"] = event["anim_out"] = "none"
        out.append(event)
        if len(out) >= MAX_EVENTS:
            break
    return out
