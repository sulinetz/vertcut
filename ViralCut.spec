# -*- mode: python ; coding: utf-8 -*-
"""Сборка ViralCut для macOS (Apple Silicon) и Windows 10/11 (x64)."""

import glob
import shutil
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform.startswith("win")

datas = [("web", "web"), ("assets", "assets")]

# Node + PO-провайдер для HD с YouTube. На Windows архив собирается отдельно,
# без него приложение работает, но YouTube может ограничиться 360p.
vendor = Path("desktop/vendor.tar.gz")
if vendor.is_file():
    datas.append((str(vendor), "bundle"))

# Модель Whisper Small: из кэша проекта или из подготовленной папки build/whisper-small.
snapshots = glob.glob("data/models/models--Systran--faster-whisper-small/snapshots/*")
built_model = Path("build/whisper-small")
if snapshots and not (built_model / "model.bin").is_file():
    src = Path(snapshots[0])
    shutil.rmtree(built_model, ignore_errors=True)
    built_model.mkdir(parents=True, exist_ok=True)
    for name in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt"):
        file = src / name
        if file.exists():
            shutil.copy2(file.resolve(), built_model / name)
if (built_model / "model.bin").is_file():
    datas.append((str(built_model), "models/whisper-small"))

binaries = []
hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "anyio._backends._asyncio",
] + collect_submodules("yt_dlp_plugins") + collect_submodules("fontTools")

if IS_MAC:
    hiddenimports += ["objc", "Foundation", "AppKit", "WebKit", "Quartz",
                      "UniformTypeIdentifiers", "Security"]
if IS_WIN:
    # pywebview на Windows использует WebView2/EdgeChromium через pythonnet;
    # collect_all кладёт WebView2Loader.dll, Microsoft.Web.WebView2.* и Python.Runtime.dll.
    for pkg in ("webview", "pythonnet", "clr_loader"):
        pkg_datas, pkg_binaries, _pkg_hidden = collect_all(pkg)
        datas += pkg_datas
        binaries += pkg_binaries
    hiddenimports += [
        "webview.platforms.edgechromium",
        "webview.platforms.winforms",
        "clr",
        "clr_loader",
        "pythonnet",
    ]

for package in ("ctranslate2", "faster_whisper", "tokenizers", "onnxruntime", "av",
                "huggingface_hub", "imageio_ffmpeg", "cv2"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

a = Analysis(
    ["desktop/main.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PyQt5", "PyQt6", "PySide6", "IPython", "pytest",
              "notebook", "jupyter"],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ViralCut",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
    disable_windowed_traceback=False,
    icon="assets/ViralCut.ico" if IS_WIN else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ViralCut",
)

if IS_MAC:
    app = BUNDLE(
        coll,
        name="ViralCut.app",
        icon="assets/ViralCut.icns",
        bundle_identifier="com.viralcut.app",
        version="1.2.0",
        info_plist={
            "CFBundleDisplayName": "ViralCut",
            "CFBundleShortVersionString": "1.2.0",
            "CFBundleVersion": "6",
            "LSMinimumSystemVersion": "11.0",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
            "LSApplicationCategoryType": "public.app-category.video",
            "NSHumanReadableCopyright": "ViralCut",
        },
    )
