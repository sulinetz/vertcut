"""Безопасные зоны интерфейсов площадок.

Справа и снизу в Shorts/TikTok/Reels лежит интерфейс: название, канал,
кнопки. Текст и лицо не должны туда попадать, иначе их закроет плеер.

Значения — в пикселях кадра 1080x1920. Интерфейсы меняются, поэтому это
константы-ориентиры, а не «официальные» числа площадок: при необходимости
их можно подкрутить в одном месте.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

PLAY_W, PLAY_H = 1080, 1920

PLATFORMS: Dict[str, Dict[str, Any]] = {
    "universal": {
        "label": "Универсально (Shorts + TikTok)",
        "top": 200, "bottom": 484, "right": 180, "left": 64,
    },
    "shorts": {
        "label": "YouTube Shorts",
        "top": 140, "bottom": 360, "right": 180, "left": 64,
    },
    "tiktok": {
        "label": "TikTok",
        "top": 130, "bottom": 484, "right": 150, "left": 64,
    },
    "reels": {
        "label": "Instagram Reels",
        "top": 200, "bottom": 420, "right": 140, "left": 64,
    },
    "none": {
        "label": "Без учёта интерфейса",
        "top": 0, "bottom": 0, "right": 0, "left": 0,
    },
}

DEFAULT_PLATFORM = "universal"


def zones(key: Optional[str]) -> Dict[str, Any]:
    """Границы безопасной области для площадки."""
    item = PLATFORMS.get(str(key or ""), PLATFORMS[DEFAULT_PLATFORM])
    return item


def is_known(key: Optional[str]) -> bool:
    return str(key or "") in PLATFORMS


def safe_rect(key: Optional[str]) -> Tuple[int, int, int, int]:
    """(x0, y0, x1, y1) — область, которую интерфейс не закрывает."""
    z = zones(key)
    return (
        int(z["left"]),
        int(z["top"]),
        PLAY_W - int(z["right"]),
        PLAY_H - int(z["bottom"]),
    )


def clamp_y(y: float, key: Optional[str], anchor: str = "bottom",
            pad: int = 40) -> float:
    """Прижимает координату текста к безопасной области.

    anchor = "bottom": y — нижняя граница текста (\\an2).
    anchor = "top": y — верхняя граница текста (\\an8).
    """
    z = zones(key)
    top_limit = float(z["top"]) + pad
    bottom_limit = PLAY_H - float(z["bottom"]) - pad
    if anchor == "top":
        return max(top_limit, min(y, bottom_limit))
    return max(top_limit, min(y, bottom_limit))


def bottom_text_y(key: Optional[str], gap: int = 60) -> int:
    """Базовая линия субтитров снизу: над интерфейсом площадки."""
    z = zones(key)
    # Даже без интерфейса не прижимаем текст к самому краю.
    reserved = max(320, int(z["bottom"]) + gap)
    return max(int(z["top"]) + 200, PLAY_H - reserved)


def top_text_y(key: Optional[str], gap: int = 120) -> int:
    """Верхняя граница текста сверху: под интерфейсом площадки."""
    z = zones(key)
    return max(120, int(z["top"]) + gap)


def face_box(key: Optional[str], size: int, margin: int = 40) -> Tuple[int, int, int]:
    """Куда ставить плашку с лицом: (x, y, size).

    По умолчанию — слева снизу, но выше интерфейса и левее кнопок справа.
    """
    z = zones(key)
    x = max(int(z["left"]), margin)
    y = PLAY_H - int(z["bottom"]) - size - margin
    max_x = PLAY_W - int(z["right"]) - size - margin
    if x > max_x:
        x = max(int(z["left"]), max_x)
    max_y = PLAY_H - int(z["bottom"]) - size - margin
    if y > max_y:
        y = max_y
    y = max(int(z["top"]) + margin, y)
    return int(x), int(y), int(size)
