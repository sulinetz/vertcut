"""Транскрипция: локальный faster-whisper с проверкой сомнительных мест.

Качество важнее скорости, но без больших моделей:

* аудио для распознавания чистится (high-pass, low-pass, шумоподавление,
  выравнивание громкости) — движку достаётся речь, а не гул и перепады уровня;
* декодирование идёт beam-search с подсказкой-промптом и запасными
  температурами, чтобы не «залипать» на одной гипотезе;
* сегменты с низкой уверенностью перепроверяются повторно: вырезаем окно,
  декодируем ещё раз с контекстом соседей и оставляем вариант, у которого
  выше вероятность модели.

Всё это не требует скачивать другую модель и работает на том же `small`.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import app_settings, utils
from .config import (DATA_DIR, MODELS_DIR, WHISPER_COMPUTE, WHISPER_CUDA_COMPUTE,
                     WHISPER_DEVICE, WHISPER_LOCAL_DIR, WHISPER_MODEL, ffmpeg)
from .errors import Cancelled

# Всё, что качает HuggingFace, держим внутри папки проекта.
os.environ.setdefault("HF_HOME", str(DATA_DIR / "hf"))
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

_MODEL = None
_MODEL_KEY: Optional[Tuple[str, str, str]] = None
_MODEL_LOCK = threading.Lock()
# Один тяжёлый проход за раз: две модели в VRAM не помещаются, а ctranslate2
# не рассчитан на параллельные вызовы одного экземпляра.
_RUN_LOCK = threading.Lock()
ProgressCb = Optional[Callable[[float, str], None]]

# --- профили распознавания ---------------------------------------------------

# Профиль — это набор параметров, а не только модель. Значения подобраны
# консервативно; после бенчмарка их можно уточнить в одном месте.
ASR_PROFILES: Dict[str, Dict[str, Any]] = {
    "fast": {
        "model": "small", "beam": 1, "best_of": 1,
        "temperatures": [0.0], "recheck": 0, "batch": 16, "batch_min": 60,
    },
    "balance": {
        "model": "large-v3-turbo", "beam": 5, "best_of": 5,
        "temperatures": [0.0, 0.2], "recheck": 8, "batch": 8, "batch_min": 60,
    },
    "max": {
        "model": "large-v3", "beam": 5, "best_of": 5,
        "temperatures": [0.0, 0.2, 0.4, 0.6], "recheck": 16, "batch": 8, "batch_min": 60,
    },
}

PROFILE_LABELS = {
    "": "Как настроено",
    "fast": "Быстро",
    "balance": "Баланс",
    "max": "Максимальное качество",
}

BASE_PROMPT = (
    "VertCut, вертикальные клипы, субтитры, подкаст, интервью. "
    "Русская речь с пунктуацией; имена и термины пишутся так же, как в оригинале."
)
# Оставлено для совместимости: старый код мог читать ASR_PROMPT напрямую.
ASR_PROMPT = os.environ.get("VERTCUT_WHISPER_PROMPT", BASE_PROMPT)


class TranscriptionError(Exception):
    pass


def _env_int(name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


def _env_float(name: str, default: float, low: float, high: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


def _terms_prompt(terms: List[str]) -> str:
    """Словарь имён и терминов в подсказке декодера, с жёстким лимитом."""
    if not terms:
        return ""
    text = ", ".join(terms)
    return (" Имена и термины: " + text[:400] + ".") if text else ""


def asr_config(profile: str = "", model: str = "") -> Dict[str, Any]:
    """Параметры распознавания на текущий запуск.

    Читается каждый раз: смена модели или словаря в настройках должна
    действовать без перезапуска. Приоритет: env → профиль → явная модель
    проекта → настройка приложения → умолчание.
    """
    key = str(profile or "").strip().lower()
    key = key if key in ASR_PROFILES else ""
    preset = ASR_PROFILES.get(key) or {}

    env_model = str(os.environ.get("VERTCUT_WHISPER") or "").strip()
    candidate = (env_model or model or preset.get("model")
                 or app_settings.whisper_model() or WHISPER_MODEL or "small")
    chosen = app_settings.normalize_whisper_model(candidate) or "small"

    terms = app_settings.asr_terms_list()
    prompt = (os.environ.get("VERTCUT_WHISPER_PROMPT")
              or (BASE_PROMPT + _terms_prompt(terms)))

    temps = preset.get("temperatures") or [0.0, 0.2, 0.4, 0.6]
    raw_temps = str(os.environ.get("VERTCUT_WHISPER_TEMPS") or "").strip()
    if raw_temps:
        parsed = []
        for piece in raw_temps.split(","):
            try:
                parsed.append(max(0.0, min(1.0, float(piece))))
            except ValueError:
                continue
        if parsed:
            temps = parsed

    return {
        "profile": key,
        "model": chosen,
        "beam": _env_int("VERTCUT_WHISPER_BEAM", int(preset.get("beam") or 5), 1, 10),
        "best_of": _env_int("VERTCUT_WHISPER_BEST_OF",
                            int(preset.get("best_of") or preset.get("beam") or 5), 1, 10),
        "temperatures": temps,
        "recheck": _env_int("VERTCUT_WHISPER_RECHECK", int(preset.get("recheck", 8)), 0, 50),
        "batch": _env_int("VERTCUT_WHISPER_BATCH_SIZE", int(preset.get("batch") or 8), 1, 64),
        "batch_min": _env_float("VERTCUT_WHISPER_BATCH_MIN",
                                float(preset.get("batch_min") or 60), 0.0, 3600.0),
        "weak_logprob": _env_float("VERTCUT_WHISPER_WEAK_LOGP", -0.62, -5.0, 0.0),
        "prompt": prompt[:600],
        "terms": terms,
    }


def _prompt_words(prompt: str) -> set:
    return set(re.findall(r"[a-zа-яё0-9]+", str(prompt).lower()))


def _prompt_echo(text: str, prompt: Optional[str] = None) -> bool:
    """Модель на музыке иногда выдаёт подсказку-промпт вместо текста."""
    words = re.findall(r"[a-zа-яё0-9]+", str(text).lower())
    if len(words) < 3:
        return False
    allowed = _prompt_words(ASR_PROMPT if prompt is None else prompt)
    hits = sum(1 for w in words if w in allowed)
    return hits / len(words) >= 0.7


def model_cached(profile: str = "", model: str = "") -> bool:
    """Модель уже есть локально (внутри .app или в кэше — сеть не нужна)."""
    if WHISPER_LOCAL_DIR and (Path(WHISPER_LOCAL_DIR) / "model.bin").is_file():
        return True
    try:
        pattern = f"models--Systran--faster-whisper-{asr_config(profile, model)['model']}"
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


_DEVICE_LOCK = threading.Lock()
_ACTIVE = {"device": None, "compute": None, "reason": ""}
_CUDA_STATE: Dict[str, Any] = {}


def _setup_cuda_dlls() -> None:
    """Windows: библиотеки cuBLAS/cuDNN ставятся pip-пакетами и лежат вне PATH.

    Без этого ctranslate2 падает на «cublas64_12.dll not found» и молча уходит
    на CPU. Ищем их в установленных пакетах и добавляем каталоги в поиск DLL.
    Пользователю не нужно ставить CUDA Toolkit.
    """
    if not sys.platform.startswith("win") or _CUDA_STATE.get("dlls"):
        return
    _CUDA_STATE["dlls"] = True
    added = []
    roots = []
    try:
        import site

        roots.extend(site.getsitepackages())
    except Exception:
        pass
    try:
        import sysconfig

        purelib = sysconfig.get_paths().get("purelib")
        if purelib:
            roots.append(purelib)
    except Exception:
        pass
    for root in roots:
        base = Path(root) / "nvidia"
        if not base.is_dir():
            continue
        for pkg in base.iterdir():
            for sub in ("bin", "lib"):
                candidate = pkg / sub
                if candidate.is_dir():
                    try:
                        os.add_dll_directory(str(candidate))
                        added.append(str(candidate))
                    except (OSError, AttributeError):
                        pass
    if added:
        os.environ["PATH"] = os.pathsep.join(added + [os.environ.get("PATH", "")])


def _nvidia_gpu_present() -> bool:
    """Есть ли в системе карта NVIDIA (даже если CUDA-библиотеки не стоят)."""
    if "present" in _CUDA_STATE:
        return bool(_CUDA_STATE["present"])
    present = False
    try:
        import shutil as _shutil
        import subprocess as _sub

        exe = _shutil.which("nvidia-smi")
        if exe:
            proc = _sub.run([exe, "-L"], capture_output=True, text=True, timeout=10,
                            **utils.subprocess_kwargs())
            present = proc.returncode == 0 and "GPU" in (proc.stdout or "")
    except Exception:  # noqa: BLE001
        present = False
    _CUDA_STATE["present"] = present
    return present


def _cuda_available() -> bool:
    """Есть ли рабочая CUDA. Проверяем один раз, ошибки не всплывают наружу."""
    if "cuda" in _CUDA_STATE:
        return bool(_CUDA_STATE["cuda"])
    ok = False
    reason = ""
    try:
        _setup_cuda_dlls()
        import ctranslate2

        count = int(ctranslate2.get_cuda_device_count())
        if count <= 0:
            if _nvidia_gpu_present():
                reason = ("видеокарта NVIDIA найдена, но CUDA-библиотеки не установлены. "
                          "Запустите: python tools/enable_cuda.py")
            else:
                reason = "видеокарта NVIDIA не найдена"
        else:
            types = ctranslate2.get_supported_compute_types("cuda")
            if "float16" in types:
                ok = True
            else:
                ok = bool(types)
                reason = f"нет float16, доступно: {sorted(types)}"
    except Exception as exc:  # noqa: BLE001 — отсутствие CUDA это норма
        reason = str(exc)[:200]
    _CUDA_STATE["cuda"] = ok
    _CUDA_STATE["reason"] = reason
    return ok


def device_info() -> Dict[str, Any]:
    """Что реально используется — для /api/health и настроек."""
    with _DEVICE_LOCK:
        cuda = _cuda_available()
        return {
            "device": _ACTIVE["device"] or ("cuda" if cuda else "cpu"),
            "compute": _ACTIVE["compute"] or (WHISPER_CUDA_COMPUTE if cuda else WHISPER_COMPUTE),
            "gpu": cuda,
            "gpu_present": _nvidia_gpu_present(),
            "note": _ACTIVE["reason"] or _CUDA_STATE.get("reason") or "",
        }


def _device_candidates(long_audio: bool) -> List[Tuple[str, str]]:
    """Порядок попыток: GPU → CPU. Одна сборка работает везде."""
    if WHISPER_DEVICE != "auto":
        device = WHISPER_DEVICE
        compute = WHISPER_CUDA_COMPUTE if "cuda" in device else WHISPER_COMPUTE
        return [(device, compute)]

    if sys.platform == "darwin":
        # Metal на длинных файлах ctranslate2 иногда зависает — только короткие.
        if long_audio:
            return [("cpu", WHISPER_COMPUTE)]
        return [("mps", "float16"), ("cpu", WHISPER_COMPUTE)]

    if _cuda_available():
        # float16 — основной режим; int8_float16 — если видеокарта старая.
        primary = WHISPER_CUDA_COMPUTE
        rest = [c for c in ("float16", "int8_float16", "int8") if c != primary]
        return [("cuda", primary)] + [("cuda", c) for c in rest] + [("cpu", WHISPER_COMPUTE)]

    return [("cpu", WHISPER_COMPUTE)]


def _reset_model(long_audio: bool = False) -> None:
    """Сбрасывает единственный слот модели — вторую большую модель не держим."""
    global _MODEL, _MODEL_KEY
    with _MODEL_LOCK:
        _MODEL = None
        _MODEL_KEY = None


def _model_name(profile: str = "", model: str = "") -> str:
    return str(asr_config(profile, model)["model"])


def _get_model(long_audio: bool = False, config: Optional[Dict[str, Any]] = None):
    global _MODEL, _MODEL_KEY
    with _MODEL_LOCK:
        cfg = config or asr_config()
        name = str(cfg["model"])
        candidates = _device_candidates(long_audio)
        if (_MODEL is not None and _MODEL_KEY is not None
                and _MODEL_KEY[0] == name
                and tuple(_MODEL_KEY[1:]) in {tuple(item) for item in candidates}):
            return _MODEL
        # Другая модель или другое устройство: прежнюю выгружаем до загрузки.
        _MODEL = None
        _MODEL_KEY = None

        from faster_whisper import WhisperModel

        local_dir = Path(WHISPER_LOCAL_DIR) if WHISPER_LOCAL_DIR else None
        model_ref = str(local_dir) if local_dir and (local_dir / "model.bin").is_file() else name
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
                with _DEVICE_LOCK:
                    _ACTIVE.update({"device": device, "compute": compute, "reason": ""})
                _MODEL_KEY = (name, device, compute)
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                model = None
                print(f"[whisper] {device}/{compute} недоступен: {str(exc)[:200]}",
                      file=sys.stderr, flush=True)
                with _DEVICE_LOCK:
                    _ACTIVE["reason"] = f"{device}/{compute}: {str(exc)[:120]}"
        if model is None:
            raise TranscriptionError(
                "Локальная модель распознавания речи недоступна. "
                f"Причина: {str(last_exc)[:200]}"
            )
        _MODEL = model
        return model


def _decode(model, audio: Path, language: Optional[str], vad: bool,
            config: Dict[str, Any], prompt: Optional[str] = None,
            beam: Optional[int] = None, temperature=None, condition: bool = True):
    """Один проход декодирования с настройками профиля."""
    return model.transcribe(
        str(audio),
        language=language or None,
        task="transcribe",
        beam_size=beam or int(config["beam"]),
        best_of=int(config["best_of"]) if beam is None else beam,
        temperature=(config["temperatures"] if temperature is None else temperature),
        length_penalty=1.0,
        repetition_penalty=1.05,
        no_repeat_ngram_size=3,
        condition_on_previous_text=condition,
        prompt_reset_on_temperature=0.5,
        initial_prompt=config["prompt"] if prompt is None else prompt,
        vad_filter=vad,
        vad_parameters={"min_silence_duration_ms": 300, "speech_pad_ms": 200} if vad else None,
        word_timestamps=True,
        no_speech_threshold=0.6,
        log_prob_threshold=-1.0,
        compression_ratio_threshold=2.4,
        language_detection_threshold=0.5,
        language_detection_segments=1,
    )


def _decode_batched(model, audio: Path, language: Optional[str], vad: bool,
                    config: Dict[str, Any], prompt: Optional[str] = None):
    """Пачечное декодирование (faster-whisper BatchedInferencePipeline)."""
    from faster_whisper import BatchedInferencePipeline

    pipe = BatchedInferencePipeline(model=model)
    kwargs = dict(
        language=language or None,
        task="transcribe",
        beam_size=int(config["beam"]),
        condition_on_previous_text=True,
        initial_prompt=config["prompt"] if prompt is None else prompt,
        vad_filter=vad,
        word_timestamps=True,
        batch_size=int(config["batch"]),
    )
    try:
        return pipe.transcribe(str(audio), **kwargs)
    except TypeError:
        # в других версиях части аргументов нет — повторяем с минимумом
        for key in ("condition_on_previous_text", "initial_prompt"):
            kwargs.pop(key, None)
        return pipe.transcribe(str(audio), **kwargs)


def _segment_payload(seg, offset: float) -> Dict[str, Any]:
    text = (seg.text or "").strip()
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
    if not words and text:
        tokens = text.split()
        step = max(0.05, (seg.end - seg.start) / max(1, len(tokens)))
        words = [{
            "word": token,
            "start": round(seg.start + i * step + offset, 3),
            "end": round(seg.start + (i + 1) * step + offset, 3),
        } for i, token in enumerate(tokens)]
    return {
        "start": round(float(seg.start) + offset, 3),
        "end": round(float(seg.end) + offset, 3),
        "text": text,
        "words": words,
        "quality": {
            "avg_logprob": round(float(getattr(seg, "avg_logprob", 0.0) or 0.0), 3),
            "no_speech_prob": round(float(getattr(seg, "no_speech_prob", 0.0) or 0.0), 3),
        },
    }


def _consume(model, path: Path, language: Optional[str], use_vad: bool,
             offset: float, total_duration: float,
             on_progress: ProgressCb, config: Dict[str, Any],
             batched: bool = False, prompt: Optional[str] = None,
             ) -> Tuple[List[Dict[str, Any]], Any]:
    if batched:
        try:
            segments, tinfo = _decode_batched(model, path, language, use_vad, config, prompt)
        except Exception as exc:  # noqa: BLE001 — пачечный режим не должен ломать распознавание
            print(f"[whisper] пачечный режим не сработал: {str(exc)[:160]}", file=sys.stderr, flush=True)
            segments, tinfo = _decode(model, path, language, use_vad, config, prompt=prompt)
    else:
        segments, tinfo = _decode(model, path, language, use_vad, config, prompt=prompt)
    out: List[Dict[str, Any]] = []
    for seg in segments:
        payload = _segment_payload(seg, offset)
        if not payload["text"]:
            continue
        out.append(payload)
        if on_progress and total_duration:
            on_progress(min(0.99, (offset + float(seg.end)) / total_duration),
                        "Распознавание речи")
    return out, tinfo


def _transcribe_span(model, path: Path, language: Optional[str], offset: float,
                     total_duration: float, on_progress: ProgressCb,
                     config: Optional[Dict[str, Any]] = None,
                     batched: bool = False):
    """Пробует с VAD; если он ничего не нашёл или сломан — без VAD.

    VAD обучен на речи и часто отбрасывает пение: песня с вокалом выглядит
    как «тишина». Поэтому пустой результат — повод повторить без фильтра.
    """
    config = config or asr_config()
    try:
        parts, info = _consume(model, path, language, True, offset, total_duration,
                               on_progress, config, batched)
    except Exception as exc:  # noqa: BLE001
        low = str(exc).lower()
        if "onnxruntime" not in low and "vad" not in low and "fusedconv" not in low:
            raise
        traceback.print_exc()
        if on_progress:
            on_progress(min(0.99, offset / max(1.0, total_duration)),
                        "VAD недоступен · распознавание без фильтра тишины")
        return _consume(model, path, language, False, offset, total_duration,
                        on_progress, config, batched, prompt="")

    if not parts:
        print("[whisper] VAD не нашёл речи — повторяю без VAD", file=sys.stderr, flush=True)
        if on_progress:
            on_progress(min(0.99, offset / max(1.0, total_duration)),
                        "Похоже на пение · распознаю без фильтра тишины")
        parts, info = _consume(model, path, language, False, offset, total_duration,
                               on_progress, config, batched, prompt="")
    return parts, info


def _cut_window(src: Path, dst: Path, start: float, end: float) -> bool:
    """Вырезает фрагмент аудио для повторной проверки."""
    cmd = [ffmpeg(), "-y", "-v", "error", "-ss", f"{max(0.0, start):.3f}",
           "-to", f"{max(start + 0.2, end):.3f}", "-i", str(src),
           "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dst)]
    result = utils.run(cmd)
    return result.returncode == 0 and dst.exists() and dst.stat().st_size > 512


_ONE_LETTER = set("авикосуяэ") | {"a", "i"}
_PUNCT = ".,!?…:;«»\"'()[]{}—–-"


def _token_key(token: str) -> str:
    return token.strip(_PUNCT).lower()


def _suspect_reasons(seg: Dict[str, Any], prev: Optional[Dict[str, Any]] = None,
                     nxt: Optional[Dict[str, Any]] = None,
                     weak: float = -0.62) -> List[str]:
    """Почему сегмент стоит перепроверить. Пустой список — всё в порядке."""
    text = str(seg.get("text") or "").strip()
    if not text:
        return ["empty"]
    tokens = text.split()
    quality = seg.get("quality") or {}
    logprob = float(quality.get("avg_logprob") or 0.0)
    no_speech = float(quality.get("no_speech_prob") or 0.0)
    reasons: List[str] = []

    if logprob < weak:
        reasons.append("logprob")
    if len(text) < 3:
        reasons.append("short")
    if any(len(_token_key(token)) >= 28 for token in tokens):
        reasons.append("long_word")
    if any(len(_token_key(token)) == 1 and _token_key(token) not in _ONE_LETTER
           for token in tokens):
        reasons.append("short_word")
    if no_speech >= 0.45 and logprob < -0.30:
        reasons.append("noise")

    run = 1
    previous = ""
    for token in tokens:
        key = _token_key(token)
        if key and key == previous:
            run += 1
        else:
            run = 1
        previous = key
        if run >= 3:
            reasons.append("repeat")
            break
    if len(tokens) >= 6:
        unique = {_token_key(token) for token in tokens if _token_key(token)}
        if len(unique) <= max(1, len(tokens) // 4):
            reasons.append("repeat")

    duration = float(seg.get("end") or 0.0) - float(seg.get("start") or 0.0)
    if 0.0 < duration < 0.30 and len(tokens) > 3:
        reasons.append("too_fast")

    for neighbor in (prev, nxt):
        if not neighbor:
            continue
        other = float((neighbor.get("quality") or {}).get("avg_logprob") or 0.0)
        if abs(logprob - other) >= 0.45 and logprob < -0.25:
            reasons.append("logprob_jump")
            break
    return reasons


def _recheck(model, wav: Path, workdir: Path, segments: List[Dict[str, Any]],
             language: Optional[str], on_progress: ProgressCb, limit: int,
             config: Dict[str, Any]) -> int:
    """Перепроверяет сомнительные сегменты; возвращает число правок.

    Сомнительность — не только низкая вероятность: повторы, обрывки, слишком
    короткие или длинные слова, речь на шуме и скачки уверенности. Окно
    вокруг сегмента декодируется заново с контекстом соседей. Замена
    принимается, только если модель стала не хуже и текст не «разъехался»
    по длине — так мы чиним слова, но не портим удачные сегменты.
    """
    if limit <= 0 or not segments:
        return 0
    weak = float(config.get("weak_logprob") or -0.62)
    scored: List[tuple] = []
    for index, seg in enumerate(segments):
        reasons = _suspect_reasons(
            seg,
            segments[index - 1] if index else None,
            segments[index + 1] if index + 1 < len(segments) else None,
            weak,
        )
        if not reasons:
            continue
        logprob = float((seg.get("quality") or {}).get("avg_logprob") or 0.0)
        structural = any(reason not in ("logprob", "logprob_jump") for reason in reasons)
        severity = logprob - (0.6 if structural else 0.0) - 0.1 * len(reasons)
        scored.append((severity, seg, reasons))
    if not scored:
        return 0
    scored.sort(key=lambda item: item[0])

    fixed = 0
    for index, (_, seg, reasons) in enumerate(scored[:limit]):
        clip = workdir / f"recheck_{os.urandom(3).hex()}.wav"
        try:
            if not _cut_window(wav, clip, seg["start"] - 0.30, seg["end"] + 0.40):
                continue
            before = [s["text"] for s in segments if s["end"] <= seg["start"]][-2:]
            context = " ".join(before)[-220:]
            prompt = (context + " " + str(config.get("prompt") or ""))[-400:]
            try:
                parts, _ = _decode(model, clip, language, False, config, prompt=prompt,
                                   beam=int(config["beam"]), temperature=[0.0],
                                   condition=False)
                new_text = " ".join(p.text.strip() for p in parts).strip()
                payloads = [_segment_payload(p, max(0.0, seg["start"] - 0.30)) for p in parts]
            except Exception:  # noqa: BLE001
                traceback.print_exc()
                continue
            if not new_text or not payloads:
                continue
            new_logprob = sum(p["quality"]["avg_logprob"] for p in payloads) / len(payloads)
            old_logprob = float((seg.get("quality") or {}).get("avg_logprob") or 0.0)
            ratio = len(new_text) / max(1, len(seg["text"]))
            structural = any(reason in ("repeat", "long_word", "short_word",
                                        "short", "noise", "too_fast")
                             for reason in reasons)
            low_ratio, high_ratio = (0.30, 2.60) if structural else (0.45, 2.20)
            improved = new_logprob > old_logprob + 0.04
            # Структурную ошибку (повтор, обрывок) можно чинить и без прироста
            # вероятности, но не ценой явного ухудшения текста.
            if not improved and (not structural or new_logprob < old_logprob - 0.30):
                continue
            if not (low_ratio <= ratio <= high_ratio):
                continue
            seg["text"] = new_text
            seg["words"] = [w for p in payloads for w in p["words"]]
            seg["start"] = payloads[0]["start"]
            seg["end"] = payloads[-1]["end"]
            seg["quality"]["avg_logprob"] = round(new_logprob, 3)
            seg["quality"]["rechecked"] = True
            seg["quality"]["recheck_reason"] = reasons[0]
            fixed += 1
            if on_progress:
                # Прогресс-колбэки снаружи ждут float, поэтому не None.
                on_progress(0.996, f"Проверка спорных фрагментов · {index + 1}")
        finally:
            try:
                clip.unlink(missing_ok=True)
            except OSError:
                pass
    return fixed


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


def transcript_key(media: Path, language: Optional[str] = None,
                   audio_track: Optional[int] = None, profile: str = "",
                   model: str = "",
                   config: Optional[Dict[str, Any]] = None) -> str:
    """Ключ кэша распознавания: всё, что влияет на текст и тайминги.

    Модель, профиль, словарь, язык, дорожка и сам файл. Если пользователь
    сменил профиль или словарь, старый транскрипт не переиспользуется.
    """
    cfg = config or asr_config(profile, model)
    digest = hashlib.sha256()
    digest.update(b"asr-v2")
    for part in (str(cfg.get("model") or ""), str(cfg.get("profile") or ""),
                 str(cfg.get("prompt") or ""), str(language or ""),
                 str(-1 if audio_track is None else int(audio_track)),
                 str(cfg.get("beam") or ""), str(cfg.get("temperatures") or "")):
        digest.update(("|" + part).encode("utf-8"))
    try:
        stat = Path(media).stat()
        digest.update(f"|size:{stat.st_size}|mtime:{int(stat.st_mtime)}".encode())
    except OSError:
        digest.update(b"|nostat")
    return digest.hexdigest()


def transcribe(media: Path, workdir: Path, language: Optional[str] = None,
               on_progress: ProgressCb = None,
               audio_track: Optional[int] = None,
               profile: str = "", model: str = "") -> Dict[str, Any]:
    with _RUN_LOCK:
        return _transcribe_impl(media, workdir, language, on_progress,
                                audio_track, profile, model)


def _transcribe_impl(media: Path, workdir: Path, language: Optional[str],
                     on_progress: ProgressCb, audio_track: Optional[int],
                     profile: str, model: str) -> Dict[str, Any]:
    started = time.time()
    if on_progress:
        on_progress(0.005, "Подготовка звука для распознавания…")
    try:
        info = utils.probe(media)
    except utils.MediaError:
        info = {"duration": utils.media_duration(media), "has_audio": True,
                "width": 0, "height": 0}
    duration = info["duration"]

    if not info["has_audio"]:
        raise TranscriptionError("В видео нет аудиодорожки — нарезки с субтитрами невозможны.")

    config = asr_config(profile, model)
    cache_key = transcript_key(media, language, audio_track, config=config)

    # Чистим звук: убираем низкочастотный гул и шипение, выравниваем громкость.
    wav = utils.extract_asr_audio(media, workdir / "audio16k.wav", audio_track=audio_track)
    chunk_seconds = _env_int("VERTCUT_WHISPER_CHUNK", 600, 120, 3600)
    trigger = max(chunk_seconds, _env_int("VERTCUT_WHISPER_CHUNK_MIN", 1800, 120, 7200))
    long_audio = duration > trigger
    batched = (duration >= float(config["batch_min"])
               and os.environ.get("VERTCUT_WHISPER_BATCH", "1").strip()
               not in ("0", "false", "no", "off"))
    model_obj = _get_model(long_audio=long_audio, config=config)
    spans: List[tuple[Path, float, float]] = [(wav, 0.0, duration)]
    chunks_folder: Optional[Path] = None
    if duration > trigger:
        split, chunks_folder = _split_audio(wav, workdir, chunk_seconds)
        if split:
            spans = split

    out: List[Dict[str, Any]] = []
    detected_language = language
    language_probability = None
    reported_language = ""
    for index, (path, offset, length) in enumerate(spans):
        if not path.exists():
            traceback.print_exc()
            continue
        timeout = max(240.0, length * 40)
        try:
            result = _run_with_timeout(
                lambda: _transcribe_span(model_obj, path, detected_language, offset,
                                         duration, on_progress, config, batched),
                timeout,
            )
            if result is None:
                # часть зависла (например, в драйвере Metal) — перезапускаем модель и идём дальше
                print(f"whisper chunk {index} timed out; skipping", file=sys.stderr)
                _reset_model(long_audio)
                model_obj = _get_model(long_audio=long_audio, config=config)
                if on_progress:
                    on_progress(min(0.99, (offset + length) / max(1.0, duration)),
                                f"Часть {index + 1} зависла · пропускаю")
                continue
            part, tinfo = result
            out.extend(part)
            reported = str(getattr(tinfo, "language", "") or "")
            if reported:
                reported_language = reported
            if not detected_language and reported:
                detected_language = reported
                language_probability = round(float(getattr(tinfo, "language_probability", 0.0) or 0.0), 3)
        except Cancelled:
            # Отмена пользователя не должна превращаться в «пропускаю часть».
            raise
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            continue
        if len(spans) > 1 and on_progress:
            on_progress(min(0.99, (offset + length) / max(1.0, duration)),
                        f"Распознавание речи · часть {index + 1} из {len(spans)}")

    if chunks_folder is not None:
        shutil.rmtree(chunks_folder, ignore_errors=True)
    if not out:
        raise TranscriptionError(
            "Речь не распознана: возможно, в видео только музыка без вокала. "
            "Для такого ролика выберите режим «Просто порезать».")

    # Второй проход по спорным местам — только когда аудио не разрезано на части.
    fixed = 0
    if len(spans) == 1 and int(config["recheck"]) > 0:
        if on_progress:
            on_progress(0.995, "Проверка спорных фрагментов…")
        try:
            fixed = _recheck(model_obj, wav, workdir, out, detected_language,
                             on_progress, int(config["recheck"]), config)
        except Exception:  # noqa: BLE001
            traceback.print_exc()

    out = [s for s in out if not _prompt_echo(s.get("text"), str(config["prompt"]))]
    out.sort(key=lambda s: s["start"])
    logprobs = [s.get("quality", {}).get("avg_logprob", 0.0) for s in out]
    weak = sum(1 for value in logprobs if value < float(config["weak_logprob"]))
    confidence = round(sum(logprobs) / len(logprobs), 3) if logprobs else 0.0

    warning = ""
    if language and reported_language:
        if utils.normalize_language(reported_language) != utils.normalize_language(language):
            warning = (f"Просили язык {language}, модель определила {reported_language}. "
                       "Проверьте текст перед нарезкой.")
    if not warning and language and language_probability is not None and language_probability < 0.5:
        warning = (f"Низкая уверенность в языке: {language_probability:.0%}. "
                   "Проверьте текст перед нарезкой.")

    return {
        "language": (detected_language or language or "ru"),
        "duration": duration,
        "segments": out,
        "engine": f"whisper-{config['model']}",
        "model": config["model"],
        "asr_profile": config["profile"],
        "cache_key": cache_key,
        "warning": warning,
        "took": round(time.time() - started, 1),
        "quality": {
            "confidence": confidence,
            "weak_segments": weak,
            "rechecked": fixed,
            "language_probability": language_probability,
        },
    }
