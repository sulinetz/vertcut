"""Транскрипция: локальный faster-whisper, резерв — субтитры источника."""
from __future__ import annotations

import os
import shutil
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import utils
from .config import (DATA_DIR, MODELS_DIR, WHISPER_COMPUTE, WHISPER_DEVICE,
                     WHISPER_LOCAL_DIR, WHISPER_MODEL, ffmpeg)

# Всё, что качает HuggingFace, держим внутри папки проекта.
os.environ.setdefault("HF_HOME", str(DATA_DIR / "hf"))
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

_MODEL = None
_MODEL_LONG = None
_MODEL_LOCK = threading.Lock()
ProgressCb = Optional[Callable[[float, str], None]]


class TranscriptionError(Exception):
    pass


def model_cached() -> bool:
    """Модель уже есть локально (внутри .app или в кэше — сеть не нужна)."""
    if WHISPER_LOCAL_DIR and (Path(WHISPER_LOCAL_DIR) / "model.bin").is_file():
        return True
    try:
        pattern = f"models--Systran--faster-whisper-{WHISPER_MODEL}"
        for path in MODELS_DIR.glob(pattern + "/snapshots/*/model.bin"):
            if path.stat().st_size > 1024 * 1024:
                return True
    except Exception:
        pass
    return False


def model_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def _reset_model(long_audio: bool = False) -> None:
    global _MODEL, _MODEL_LONG
    with _MODEL_LOCK:
        if long_audio:
            _MODEL_LONG = None
        else:
            _MODEL = None


def _get_model(long_audio: bool = False):
    global _MODEL, _MODEL_LONG
    with _MODEL_LOCK:
        if long_audio and _MODEL_LONG is not None:
            return _MODEL_LONG
        if not long_audio and _MODEL is not None:
            return _MODEL
        from faster_whisper import WhisperModel

        local_dir = Path(WHISPER_LOCAL_DIR) if WHISPER_LOCAL_DIR else None
        model_ref = str(local_dir) if local_dir and (local_dir / "model.bin").is_file() else WHISPER_MODEL
        # Для длинных аудио не используем экспериментальный MPS — на нём
        # ctranslate2 может «зависнуть» на середине многочасового файла.
        if WHISPER_DEVICE == "auto":
            # Apple Metal доступен только на macOS; на Windows/Linux сразу CPU.
            if long_audio or sys.platform != "darwin":
                candidates = [("cpu", WHISPER_COMPUTE)]
            else:
                candidates = [("mps", "float16"), ("cpu", WHISPER_COMPUTE)]
        else:
            candidates = [(WHISPER_DEVICE, WHISPER_COMPUTE)]
        last_exc = None
        model = None
        for device, compute in candidates:
            try:
                model = WhisperModel(
                    model_ref,
                    device=device,
                    compute_type=compute,
                    download_root=str(MODELS_DIR),
                )
                model._vc_device = device  # type: ignore[attr-defined]
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                model = None
                print(f"[whisper] {device}/{compute} недоступен: {str(exc)[:200]}",
                      file=sys.stderr, flush=True)
        if model is None:
            raise TranscriptionError(
                "Локальная модель распознавания речи недоступна. "
                f"Причина: {str(last_exc)[:200]}"
            )
        if long_audio:
            _MODEL_LONG = model
        else:
            _MODEL = model
        return model


def _consume(model, path: Path, language: Optional[str], use_vad: bool,
             offset: float, total_duration: float,
             on_progress: ProgressCb) -> tuple[List[Dict[str, Any]], Any]:
    segments, tinfo = model.transcribe(
        str(path),
        language=language or None,
        task="transcribe",
        beam_size=1,
        vad_filter=use_vad,
        vad_parameters={"min_silence_duration_ms": 400},
        word_timestamps=True,
        condition_on_previous_text=False,
    )
    out: List[Dict[str, Any]] = []
    for seg in segments:
        text = (seg.text or "").strip()
        if not text:
            continue
        words = []
        for word in (seg.words or []):
            token = (word.word or "").strip()
            if not token:
                continue
            words.append({
                "word": token,
                "start": round(float(word.start) + offset, 3),
                "end": round(float(word.end) + offset, 3),
            })
        if not words:
            tokens = text.split()
            step = max(0.05, (seg.end - seg.start) / max(1, len(tokens)))
            words = [{
                "word": token,
                "start": round(seg.start + i * step + offset, 3),
                "end": round(seg.start + (i + 1) * step + offset, 3),
            } for i, token in enumerate(tokens)]
        out.append({
            "start": round(float(seg.start) + offset, 3),
            "end": round(float(seg.end) + offset, 3),
            "text": text, "words": words,
        })
        if on_progress and total_duration:
            on_progress(min(0.99, (offset + float(seg.end)) / total_duration),
                        "Распознавание речи")
    return out, tinfo


def _transcribe_span(model, path: Path, language: Optional[str], offset: float,
                     total_duration: float, on_progress: ProgressCb):
    """Пробует с VAD, при ошибке ONNX повторяет без VAD."""
    try:
        return _consume(model, path, language, True, offset, total_duration, on_progress)
    except Exception as exc:  # noqa: BLE001
        low = str(exc).lower()
        if "onnxruntime" not in low and "vad" not in low and "fusedconv" not in low:
            raise
        traceback.print_exc()
        if on_progress:
            on_progress(min(0.99, offset / max(1.0, total_duration)),
                        "VAD недоступен · распознавание без фильтра тишины")
        return _consume(model, path, language, False, offset, total_duration, on_progress)


def _run_with_timeout(fn, timeout: float):
    """Запускает распознавание части в потоке; при зависании отдаёт None."""
    box = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except Exception as exc:  # noqa: BLE001
            box["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        return None
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _split_audio(wav: Path, workdir: Path, chunk_seconds: int) -> tuple[List[tuple[Path, float, float]], Path]:
    folder = workdir / f"whisper_chunks_{os.urandom(4).hex()}"
    folder.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg(), "-y", "-v", "error", "-i", str(wav),
           "-f", "segment", "-segment_time", str(chunk_seconds), "-c", "copy",
           str(folder / "chunk_%03d.wav")]
    result = utils.run(cmd)
    files = sorted(folder.glob("chunk_*.wav"))
    if result.returncode or not files:
        shutil.rmtree(folder, ignore_errors=True)
        return [], folder
    spans = []
    offset = 0.0
    for path in files:
        length = utils.media_duration(path)
        if length <= 0:
            continue
        spans.append((path, offset, length))
        offset += length
    return spans, folder


def transcribe(media: Path, workdir: Path, language: Optional[str] = None,
               on_progress: ProgressCb = None) -> Dict[str, Any]:
    started = time.time()
    if on_progress:
        on_progress(0.005, "Загрузка модели распознавания речи…")
    try:
        info = utils.probe(media)
    except utils.MediaError:
        info = {"duration": utils.media_duration(media), "has_audio": True,
                "width": 0, "height": 0}
    duration = info["duration"]

    if not info["has_audio"]:
        raise TranscriptionError("В видео нет аудиодорожки — нарезки с субтитрами невозможны.")

    wav = utils.extract_audio(media, workdir / "audio16k.wav")
    chunk_seconds = max(120, int(os.environ.get("VIRALCUT_WHISPER_CHUNK", "600")))
    trigger = max(chunk_seconds, int(os.environ.get("VIRALCUT_WHISPER_CHUNK_MIN", "1800")))
    long_audio = duration > trigger
    model = _get_model(long_audio=long_audio)
    spans: List[tuple[Path, float, float]] = [(wav, 0.0, duration)]
    chunks_folder: Optional[Path] = None
    if duration > trigger:
        split, chunks_folder = _split_audio(wav, workdir, chunk_seconds)
        if split:
            spans = split

    out: List[Dict[str, Any]] = []
    detected_language = language
    for index, (path, offset, length) in enumerate(spans):
        if not path.exists():
            traceback.print_exc()
            continue
        timeout = max(240.0, length * 40)
        try:
            result = _run_with_timeout(
                lambda: _transcribe_span(model, path, detected_language, offset,
                                         duration, on_progress),
                timeout,
            )
            if result is None:
                # часть зависла (например, в драйвере Metal) — перезапускаем модель и идём дальше
                print(f"whisper chunk {index} timed out; skipping", file=sys.stderr)
                _reset_model(long_audio)
                model = _get_model(long_audio=long_audio)
                if on_progress:
                    on_progress(min(0.99, (offset + length) / max(1.0, duration)),
                                f"Часть {index + 1} зависла · пропускаю")
                continue
            part, tinfo = result
            out.extend(part)
            if not detected_language and getattr(tinfo, "language", None):
                detected_language = tinfo.language
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            continue
        if len(spans) > 1 and on_progress:
            on_progress(min(0.99, (offset + length) / max(1.0, duration)),
                        f"Распознавание речи · часть {index + 1} из {len(spans)}")

    if chunks_folder is not None:
        shutil.rmtree(chunks_folder, ignore_errors=True)
    if not out:
        raise TranscriptionError("Речь не распознана: возможно, в видео нет голоса.")

    return {
        "language": (detected_language or language or "ru"),
        "duration": duration,
        "segments": out,
        "engine": f"whisper-{WHISPER_MODEL}",
        "took": round(time.time() - started, 1),
    }
