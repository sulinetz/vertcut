"""Включает GPU-распознавание на машине с видеокартой NVIDIA.

Запуск:  python tools/enable_cuda.py

Ставит только библиотеки CUDA, которые нужны ctranslate2 для faster-whisper.
CUDA Toolkit целиком не требуется. Если карты NVIDIA нет — скрипт ничего
не меняет и объясняет, что приложение продолжит работать на процессоре.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGES = ["nvidia-cublas-cu12>=12.4"]


def _run(cmd: list[str]) -> int:
    print("+", " ".join(cmd), flush=True)
    return subprocess.call(cmd)


def _has_nvidia_gpu() -> bool:
    import shutil

    exe = shutil.which("nvidia-smi")
    if not exe:
        return False
    try:
        proc = subprocess.run([exe, "-L"], capture_output=True, text=True, timeout=15)
    except Exception:  # noqa: BLE001
        return False
    return proc.returncode == 0 and "GPU" in (proc.stdout or "")


def main() -> int:
    if not _has_nvidia_gpu():
        print("Видеокарта NVIDIA не найдена — ничего не меняю.")
        print("Приложение будет распознавать речь на процессоре (в 5–10 раз медленнее).")
        return 0

    print("Видеокарта NVIDIA найдена. Ставлю CUDA-библиотеки для ctranslate2…")
    code = _run([sys.executable, "-m", "pip", "install", "--upgrade", *PACKAGES])
    if code != 0:
        print("Не удалось установить пакеты. Проверьте интернет и повторите.")
        return code

    sys.path.insert(0, str(ROOT))
    print("\nПроверка…")
    try:
        import ctranslate2

        count = ctranslate2.get_cuda_device_count()
        types = sorted(ctranslate2.get_supported_compute_types("cuda")) if count else []
    except Exception as exc:  # noqa: BLE001
        print(f"Ошибка проверки: {exc}")
        return 1

    if count and "float16" in types:
        print(f"Готово: CUDA видна ({count} устройство), float16 поддерживается.")
        print("Приложение само выберет GPU при следующем распознавании.")
        return 0

    print(f"CUDA устройств: {count}; доступные типы: {types}")
    print("Если устройств 0 — обновите драйвер NVIDIA и повторите.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
