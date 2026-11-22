"""Рисует иконку VertCut во всех нужных форматах (PNG, ICO, ICNS)."""
from __future__ import annotations

import pathlib

import numpy as np
from PIL import Image, ImageDraw

ROOT = pathlib.Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
S = 1024
SS = 4  # суперсэмплинг
W = S * SS

BLUE = (29, 78, 216)
CYAN = (34, 211, 238)
PLAY = (29, 78, 216)


def gradient(size: int) -> Image.Image:
    y, x = np.mgrid[0:size, 0:size].astype(np.float32)
    t = (x + y) / (2.0 * (size - 1))
    t = t[..., None]
    start = np.array(BLUE, dtype=np.float32)
    end = np.array(CYAN, dtype=np.float32)
    arr = (start + (end - start) * t).astype(np.uint8)
    return Image.fromarray(arr, "RGB").convert("RGBA")


def build() -> Image.Image:
    # Готовый знак: если лежит исходник, все форматы собираются из него.
    source = ASSETS / "icon_source.png"
    if source.exists():
        return Image.open(source).convert("RGBA").resize((S, S), Image.LANCZOS)

    bg = gradient(W)

    mask = Image.new("L", (W, W), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, W - 1, W - 1], radius=int(0.225 * W), fill=255)
    icon = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    icon.paste(bg, (0, 0), mask)

    d = ImageDraw.Draw(icon)
    # белый вертикальный «клип»
    x0, x1 = int(0.330 * W), int(0.670 * W)
    y0, y1 = int(0.210 * W), int(0.790 * W)
    d.rounded_rectangle([x0, y0, x1, y1], radius=int(0.075 * W), fill=(255, 255, 255, 255))
    # play внутри
    d.polygon([
        (int(0.452 * W), int(0.408 * W)),
        (int(0.452 * W), int(0.592 * W)),
        (int(0.596 * W), int(0.500 * W)),
    ], fill=PLAY + (255,))

    return icon.resize((S, S), Image.LANCZOS)


def main() -> None:
    icon = build()
    icon.save(ASSETS / "icon_1024.png")
    icon.save(ASSETS / "icon_new.png")

    # .ico с набором размеров
    ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    icon.save(ASSETS / "VertCut.ico", sizes=ico_sizes)

    # .iconset для macOS
    iconset = ASSETS / "VertCut.iconset"
    iconset.mkdir(exist_ok=True)
    for base in (16, 32, 128, 256, 512):
        icon.resize((base, base), Image.LANCZOS).save(iconset / f"icon_{base}x{base}.png")
        icon.resize((base * 2, base * 2), Image.LANCZOS).save(iconset / f"icon_{base}x{base}@2x.png")
    icon.resize((64, 64), Image.LANCZOS).save(iconset / "icon_64x64.png")

    # .icns
    icns = ASSETS / "VertCut.icns"
    try:
        icon.save(icns, format="ICNS")
        print("icns: Pillow")
    except Exception as exc:  # noqa: BLE001
        print("icns: Pillow не умеет, ставлю icnsutil:", exc)
        import subprocess
        import sys

        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "icnsutil"], check=True)
        import icnsutil

        icns_file = icnsutil.IcnsFile()
        for name, size in (("icp4", 16), ("icp5", 32), ("icp6", 64), ("ic07", 128),
                           ("ic08", 256), ("ic09", 512), ("ic10", 1024)):
            tmp = ASSETS / f"_tmp_{size}.png"
            icon.resize((size, size), Image.LANCZOS).save(tmp)
            icns_file.add_media(name, str(tmp))
            tmp.unlink()
        icns_file.write(str(icns))
        print("icns: icnsutil")

    print("готово:", (ASSETS / "VertCut.ico").stat().st_size, "байт ico")


if __name__ == "__main__":
    main()
