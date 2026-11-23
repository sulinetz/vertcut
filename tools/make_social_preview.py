"""Обложка репозитория и соцсетей (1280x640) из реальных ассетов VertCut.

Запуск: python tools/make_social_preview.py
Результат: docs/github/social-preview.png
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "github" / "social-preview.png"
ICON = ROOT / "assets" / "icon_1024.png"
PHONE = ROOT / "docs" / "screenshots" / "subtitles-karaoke.png"
FONT_BOLD = ROOT / "assets" / "fonts" / "Montserrat-ExtraBold.ttf"
FONT_TEXT = ROOT / "assets" / "fonts" / "GolosText-Bold.ttf"

W, H = 1280, 640


def radial(size, center, radius, color):
    """Мягкое радиальное свечение на прозрачном слое."""
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    px = layer.load()
    cx, cy = center
    for y in range(size[1]):
        dy = y - cy
        for x in range(size[0]):
            dx = x - cx
            d = math.hypot(dx, dy)
            if d >= radius:
                continue
            k = (1.0 - d / radius) ** 2
            px[x, y] = (color[0], color[1], color[2], int(color[3] * k))
    return layer


def gradient_text(base, text, font, xy, c1, c2):
    mask = Image.new("L", base.size, 0)
    ImageDraw.Draw(mask).text(xy, text, font=font, fill=255)
    bbox = mask.getbbox()
    if not bbox:
        return
    mask = mask.crop(bbox)
    grad = Image.new("RGB", mask.size)
    gd = ImageDraw.Draw(grad)
    for x in range(mask.size[0]):
        k = x / max(1, mask.size[0] - 1)
        gd.line([(x, 0), (x, mask.size[1])],
                fill=(int(c1[0] + (c2[0] - c1[0]) * k),
                      int(c1[1] + (c2[1] - c1[1]) * k),
                      int(c1[2] + (c2[2] - c1[2]) * k)))
    base.paste(grad, (bbox[0], bbox[1]), mask)


def chip(draw, x, y, text, font, accent=False):
    pad_x, pad_y = 18, 11
    box = draw.textbbox((0, 0), text, font=font)
    w = box[2] - box[0] + pad_x * 2
    h = box[3] - box[1] + pad_y * 2
    draw.rounded_rectangle([x, y, x + w, y + h], radius=h // 2,
                           fill=(139, 92, 246) if accent else (27, 24, 38),
                           outline=None if accent else (62, 56, 80), width=1)
    draw.text((x + pad_x, y + pad_y - 2), text, font=font,
              fill=(255, 255, 255))
    return x + w


def main() -> None:
    canvas = Image.new("RGBA", (W, H), (7, 6, 12, 255))
    canvas.alpha_composite(radial((W, H), (110, -40), 620, (139, 92, 246, 120)))
    canvas.alpha_composite(radial((W, H), (1180, 280), 520, (255, 77, 157, 80)))
    canvas.alpha_composite(radial((W, H), (520, 720), 460, (59, 130, 246, 60)))

    grid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    for x in range(0, W, 64):
        gd.line([(x, 0), (x, H)], fill=(255, 255, 255, 12))
    for y in range(0, H, 64):
        gd.line([(0, y), (W, y)], fill=(255, 255, 255, 12))
    canvas.alpha_composite(grid)

    logo = Image.open(ICON).convert("RGBA")
    # В исходном PNG вокруг значка есть белое поле: обрезаем его по цвету,
    # иначе на тёмной обложке появляется белый квадрат.
    colored = logo.convert("RGB")
    pix = colored.load()
    xs, ys = [], []
    for y in range(logo.height):
        for x in range(logo.width):
            r, g, b = pix[x, y]
            if b > r + 25 and b > g - 10:
                xs.append(x)
                ys.append(y)
    if xs:
        box = (max(0, min(xs) + 2), max(0, min(ys) + 2),
               min(logo.width, max(xs) - 1), min(logo.height, max(ys) - 1))
        logo = logo.crop(box)
    logo = logo.resize((66, 66), Image.LANCZOS)
    lm = Image.new("L", logo.size, 0)
    ImageDraw.Draw(lm).rounded_rectangle([0, 0, 65, 65], radius=18, fill=255)
    canvas.paste(logo, (64, 50), lm)
    draw = ImageDraw.Draw(canvas)
    draw.text((144, 60), "VertCut", font=ImageFont.truetype(str(FONT_BOLD), 42),
              fill=(255, 255, 255, 255))

    title = ImageFont.truetype(str(FONT_BOLD), 56)
    draw.text((64, 168), "Длинное видео —", font=title, fill=(245, 243, 255, 255))
    gradient_text(canvas, "в вирусные клипы", title, (64, 240),
                  (139, 92, 246), (255, 77, 157))

    sub = ImageFont.truetype(str(FONT_TEXT), 23)
    draw.text((64, 330), "Shorts · Reels · TikTok · внешний дубляж",
              font=sub, fill=(197, 190, 214, 255))

    chip_font = ImageFont.truetype(str(FONT_TEXT), 17)
    x = chip(draw, 64, 390, "всё локально", chip_font, accent=True)
    x = chip(draw, x + 12, 390, "Windows + macOS", chip_font)
    chip(draw, x + 12, 390, "без подписок", chip_font)

    foot = ImageFont.truetype(str(FONT_TEXT), 20)
    draw.text((64, 552), "github.com/sulinetz/vertcut", font=foot,
              fill=(207, 201, 226, 255))

    # Телефон с вертикальным кадром.
    phone_w, phone_h = 286, 508
    px, py = 930, 66
    frame = Image.new("RGBA", (phone_w + 20, phone_h + 20), (0, 0, 0, 0))
    fd = ImageDraw.Draw(frame)
    fd.rounded_rectangle([0, 0, phone_w + 19, phone_h + 19], radius=44,
                         fill=(16, 14, 23, 255), outline=(255, 255, 255, 46), width=2)
    screen = Image.open(PHONE).convert("RGB").resize((phone_w, phone_h), Image.LANCZOS)
    mask = Image.new("L", (phone_w, phone_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, phone_w - 1, phone_h - 1],
                                           radius=34, fill=255)
    frame.paste(screen, (10, 10), mask)
    canvas.alpha_composite(frame, (px, py))

    fd2 = ImageDraw.Draw(canvas)
    fd2.rounded_rectangle([px + 88, py + 8, px + 198, py + 30], radius=11,
                          fill=(10, 8, 16, 255))

    badge_font = ImageFont.truetype(str(FONT_TEXT), 16)
    badge_w = 178
    badge_x, badge_y = px - 92, py + phone_h - 64
    fd2.rounded_rectangle([badge_x, badge_y, badge_x + badge_w, badge_y + 44],
                          radius=14, fill=(18, 15, 27),
                          outline=(70, 64, 88), width=1)
    fd2.ellipse([badge_x + 16, badge_y + 18, badge_x + 26, badge_y + 28],
                fill=(94, 242, 160, 255))
    fd2.text((badge_x + 36, badge_y + 12), "дубляж · .ac3", font=badge_font,
             fill=(245, 243, 255, 255))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(OUT, optimize=True)
    print(OUT, OUT.stat().st_size)


if __name__ == "__main__":
    main()
