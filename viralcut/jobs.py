"""Фоновые задачи: очередь проектов и перерендер клипов."""
from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict

from . import db, live, pipeline
from .config import MAX_WORKERS

_project_pool = ThreadPoolExecutor(max_workers=max(1, MAX_WORKERS), thread_name_prefix="project")
_clip_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="clip")
_lock = threading.Lock()

# Каждый эфир — отдельный поток. Раньше стримы шли через пул на 3 места, и
# несколько «ждущих эфир» записей навсегда занимали очередь: следующая запись
# висела на «Запись · подключение», хотя ничего не начиналось.
MAX_STREAMS = max(1, int(os.environ.get("VIRALCUT_MAX_STREAMS", "6")))
_streams: Dict[str, threading.Thread] = {}
_streams_lock = threading.Lock()


def submit_project(pid: str) -> None:
    def work() -> None:
        try:
            pipeline.run_project(pid)
        except Exception as exc:  # noqa: BLE001
            db.update_project(pid, status="error", error=str(exc)[:600], stage="Ошибка")

    _project_pool.submit(work)


def submit_stream(pid: str, options: dict) -> None:
    with _streams_lock:
        existing = _streams.get(pid)
        if existing is not None and existing.is_alive():
            return
        if sum(1 for t in _streams.values() if t.is_alive()) >= MAX_STREAMS:
            db.update_project(
                pid, status="error", stage="Слишком много одновременных записей",
                error=f"Одновременно можно записывать не больше {MAX_STREAMS} эфиров.")
            return

        def work() -> None:
            try:
                live.run_stream(pid, options)
            except Exception as exc:  # noqa: BLE001
                db.update_project(pid, status="error", error=str(exc)[:600], stage="Ошибка стрима")
            finally:
                with _streams_lock:
                    _streams.pop(pid, None)

        thread = threading.Thread(target=work, name=f"live-{pid}", daemon=True)
        _streams[pid] = thread
        thread.start()


def submit_prepare(pid: str) -> None:
    def work() -> None:
        try:
            pipeline.prepare_project(pid)
        except Exception as exc:  # noqa: BLE001
            db.update_project(pid, status="error", error=str(exc)[:600], stage="Ошибка")

    _project_pool.submit(work)


def submit_process(pid: str) -> None:
    def work() -> None:
        try:
            pipeline.process_project(pid)
        except Exception as exc:  # noqa: BLE001
            db.update_project(pid, status="error", error=str(exc)[:600], stage="Ошибка")

    _project_pool.submit(work)


def submit_rerender(clip_id: str, payload: Dict[str, Any]) -> None:
    db.update_clip(clip_id, status="rendering", error=None)

    def work() -> None:
        try:
            pipeline.rerender_clip(clip_id, payload)
        except Exception as exc:  # noqa: BLE001
            db.update_clip(clip_id, status="error", error=str(exc)[:500])

    _clip_pool.submit(work)
