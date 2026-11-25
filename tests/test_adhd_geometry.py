"""Геометрия split-screen: Python и JS должны совпадать до пикселя."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from vertcut import render

ROOT = Path(__file__).resolve().parent.parent
GEOMETRY_JS = ROOT / "web" / "geometry.js"

CASES = [
    (1080, 1920, 0.5),
    (1080, 1920, 0.25),
    (1080, 1920, 0.3),
    (1080, 1920, 0.4),
    (1080, 1920, 0.85),
    (1080, 1920, 0.1),
    (1080, 1920, 0.99),
    (1080, 1350, 0.5),
    (720, 1280, 0.63),
    (1081, 1921, 0.777),
]


def test_split_geometry_known_values():
    geometry = render.split_geometry(1080, 1920, 0.5)
    assert geometry["top_h"] == 960
    assert geometry["bottom_h"] == 960
    assert geometry["top"]["h"] == geometry["top_h"]
    assert geometry["bottom"]["y"] == geometry["top_h"]
    assert render.split_geometry(1080, 1920, 0.3)["top_h"] == 576
    assert render.split_geometry(1080, 1920, 0.85)["top_h"] == 1632
    # вне диапазона обрезается, но старые 0.3 остаются рабочими
    assert render.split_geometry(1080, 1920, 0.1)["top_h"] == 480
    assert render.split_geometry(1080, 1920, 0.99)["top_h"] == 1632


def test_split_geometry_even_height_and_bounds():
    for height in (1918, 1920, 1922):
        geometry = render.split_geometry(1080, height, 0.5)
        assert geometry["top_h"] % 2 == 0
        assert geometry["bottom_h"] % 2 == 0
        assert geometry["top_h"] + geometry["bottom_h"] == height
        assert geometry["top_h"] >= 2


@pytest.mark.skipif(not shutil.which("node"), reason="нужен node")
def test_js_geometry_matches_python():
    script = (
        "const {splitGeometry} = require(process.argv[1]);"
        "const [w,h,r] = JSON.parse(process.argv[2]);"
        "console.log(JSON.stringify(splitGeometry(w,h,r)));"
    )
    for width, height, ratio in CASES:
        proc = subprocess.run(
            [shutil.which("node"), "-e", script, str(GEOMETRY_JS),
             json.dumps([width, height, ratio])],
            capture_output=True, text=True, encoding="utf-8", check=True)
        js = json.loads(proc.stdout)
        py = render.split_geometry(width, height, ratio)
        assert js["top_h"] == py["top_h"], (width, height, ratio, js, py)
        assert js["bottom_h"] == py["bottom_h"]
        assert js["top"]["y"] == py["top"]["y"]
        assert js["bottom"]["y"] == py["bottom"]["y"]
        assert js["bottom"]["h"] == py["bottom"]["h"]
