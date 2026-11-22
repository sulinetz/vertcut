"""Нагрузка CPU/GPU, температура GPU и свободное место.

Модуль намеренно не бросает исключения наружу: панель датчиков не должна
ломать приложение, даже если psutil не установлен или nvidia-smi недоступен.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .config import PROJECTS_DIR
from .utils import subprocess_kwargs

try:  # psutil — мягкая зависимость: без неё CPU просто не показывается
    import psutil  # type: ignore[import-not-found]
except Exception:  # noqa: BLE001
    psutil = None  # type: ignore[assignment]

if psutil is not None:
    # Первый cpu_percent() всегда 0: снимаем базовую точку заранее.
    psutil.cpu_percent(interval=None)

_LOCK = threading.Lock()
_CACHE: Dict[str, Any] = {"at": 0.0, "data": {}}
_CACHE_SECONDS = 1.0
_GPU_EXE: Optional[str] = None
_GPU_LOOKED = False

_NVIDIA_QUERY = "name,utilization.gpu,temperature.gpu,memory.used,memory.total"


def _num(value: str) -> Optional[float]:
    text = (value or "").strip()
    if not text or text.upper() in ("N/A", "[N/A]", "NOT SUPPORTED"):
        return None
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def parse_nvidia_smi(text: str) -> Optional[Dict[str, Any]]:
    """Разбирает строку `nvidia-smi --query-gpu=... --format=csv,noheader,nounits`."""
    for line in (text or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            continue
        used = _num(parts[3])
        total = _num(parts[4])
        return {
            "name": parts[0] or "NVIDIA GPU",
            "util": _num(parts[1]),
            "temp": _num(parts[2]),
            "mem_used_mb": used,
            "mem_total_mb": total,
            "mem_percent": round(used / total * 100, 1) if used and total else None,
        }
    return None


def _nvidia_smi_exe() -> Optional[str]:
    global _GPU_EXE, _GPU_LOOKED
    if _GPU_LOOKED:
        return _GPU_EXE
    _GPU_LOOKED = True
    found = shutil.which("nvidia-smi")
    if not found and sys.platform.startswith("win"):
        candidate = Path(r"C:\Windows\System32\nvidia-smi.exe")
        if candidate.is_file():
            found = str(candidate)
    _GPU_EXE = found
    return found


def _gpu_snapshot() -> Optional[Dict[str, Any]]:
    exe = _nvidia_smi_exe()
    if not exe:
        return None
    try:
        proc = subprocess.run(
            [exe, f"--query-gpu={_NVIDIA_QUERY}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=2, errors="replace",
            **subprocess_kwargs(),
        )
        if proc.returncode != 0:
            return None
        return parse_nvidia_smi(proc.stdout or "")
    except Exception:  # noqa: BLE001 — драйвер может отвечать медленно/быть занят
        return None


def _cpu_snapshot() -> Optional[Dict[str, Any]]:
    if psutil is None:
        return None
    try:
        return {
            "percent": round(float(psutil.cpu_percent(interval=None)), 1),
            "cores": psutil.cpu_count(logical=True),
            "physical": psutil.cpu_count(logical=False),
        }
    except Exception:  # noqa: BLE001
        return None


def _memory_snapshot() -> Optional[Dict[str, Any]]:
    if psutil is None:
        return None
    try:
        mem = psutil.virtual_memory()
        return {
            "percent": round(float(mem.percent), 1),
            "used_gb": round(mem.used / 1024 ** 3, 1),
            "total_gb": round(mem.total / 1024 ** 3, 1),
        }
    except Exception:  # noqa: BLE001
        return None


def _disk_snapshot() -> Optional[Dict[str, Any]]:
    try:
        usage = shutil.disk_usage(PROJECTS_DIR)
        return {
            "path": str(PROJECTS_DIR),
            "free_gb": round(usage.free / 1024 ** 3, 1),
            "total_gb": round(usage.total / 1024 ** 3, 1),
        }
    except Exception:  # noqa: BLE001
        return None


def snapshot(force: bool = False) -> Dict[str, Any]:
    """Свежий снимок метрик; кэш на секунду, чтобы опрос UI не спамил nvidia-smi."""
    global _CACHE
    with _LOCK:
        now = time.monotonic()
        if not force and _CACHE.get("data") and now - float(_CACHE.get("at") or 0) < _CACHE_SECONDS:
            return _CACHE["data"]
        data = {
            "cpu": _cpu_snapshot(),
            "memory": _memory_snapshot(),
            "gpu": _gpu_snapshot(),
            "disk": _disk_snapshot(),
            "at": round(time.time(), 3),
        }
        _CACHE = {"at": now, "data": data}
        return data
