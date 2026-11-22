"""Бенчмарк рендера: CPU (libx264) против NVENC.

Запуск:
    .\\.venv-win\\Scripts\\python.exe tools\\bench_render.py --seconds 10
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from vertcut import render
from vertcut.config import ffmpeg


def make_source(path: Path, seconds: int) -> None:
    subprocess.run(
        [
            ffmpeg(), "-y", "-v", "error",
            "-f", "lavfi", "-i", f"testsrc2=size=1920x1080:rate=30:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
            "-c:a", "aac", "-b:a", "128k", "-shortest", str(path),
        ],
        check=True,
    )


def run_one(src: Path, out: Path, seconds: int, mode: str) -> dict:
    os.environ["VERTCUT_HW_ENCODE"] = "0" if mode == "cpu" else "auto"
    render._HW_CACHE.clear()
    started = time.perf_counter()
    result = render.render_clip(
        src, 0.0, float(seconds), out,
        aspect="9:16", mode="crop", crf=20, bitrate=8,
    )
    elapsed = time.perf_counter() - started
    return {
        "mode": mode,
        "seconds": round(elapsed, 2),
        "speed": round(seconds / max(0.01, elapsed), 2),
        "encoder": result.get("encoder"),
        "fallback": result.get("fallback", False),
        "size_mb": round(out.stat().st_size / 1024 / 1024, 1) if out.exists() else 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=10)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="vertcut-bench-") as tmp:
        root = Path(tmp)
        src = root / "source.mp4"
        make_source(src, args.seconds)
        rows = []
        for mode in ("cpu", "gpu"):
            rows.append(run_one(src, root / f"out_{mode}.mp4", args.seconds, mode))
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
