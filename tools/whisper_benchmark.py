"""Бенчмарк Whisper: WER, термины, тайминги, скорость и память.

Материал — ролики YouTube с **авторскими** русскими субтитрами. Автосубтитры
не годятся: они сами результат ASR. Скачивание идёт во временную папку,
в репозиторий попадают только итоговая таблица и этот скрипт.

Пример:
    .\\.venv-win\\Scripts\\python.exe tools\\whisper_benchmark.py ^
        --items %TEMP%\\vc-bench\\items.json ^
        --profiles fast,balance,max ^
        --models small,large-v3-turbo ^
        --out docs\\WHISPER_BENCHMARK.md

items.json:
    {"items": [
      {"url": "https://youtu.be/...", "start": 120, "duration": 75,
       "kind": "чистая речь", "terms": ["OpenAI", "GPT-5"]}
    ]}

Требуется сеть и yt-dlp/ffmpeg из окружения проекта. Скачанные файлы не
коммитятся.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vertcut import transcribe, utils  # noqa: E402
from vertcut.config import ffmpeg  # noqa: E402


def normalize_text(text: str) -> List[str]:
    text = str(text or "").lower().replace("ё", "е")
    text = re.sub(r"[^\w\s]|_", " ", text)
    return [word for word in text.split() if word]


def edit_distance(ref: List[str], hyp: List[str]) -> int:
    previous = list(range(len(hyp) + 1))
    for i in range(1, len(ref) + 1):
        current = [i] + [0] * len(hyp)
        for j in range(1, len(hyp) + 1):
            cost = 0 if ref[i - 1] == hyp[j - 1] else 1
            current[j] = min(previous[j] + 1, current[j - 1] + 1,
                             previous[j - 1] + cost)
        previous = current
    return previous[len(hyp)]


def wer_percent(reference: str, hypothesis: str) -> float:
    ref = normalize_text(reference)
    hyp = normalize_text(hypothesis)
    if not ref:
        return 0.0
    return round(edit_distance(ref, hyp) / len(ref) * 100, 1)


def term_errors(reference: str, hypothesis: str,
                terms: Optional[List[str]] = None) -> Tuple[int, int]:
    """(ошибок, проверено терминов): термин есть в эталоне, но не в тексте."""
    checked = 0
    wrong = 0
    low_ref = str(reference).lower()
    low_hyp = str(hypothesis).lower()
    for term in terms or []:
        term = str(term or "").strip()
        if not term or term.lower() not in low_ref:
            continue
        checked += 1
        if term.lower() not in low_hyp:
            wrong += 1
    return wrong, checked


def punctuation_count(text: str) -> int:
    return len(re.findall(r"[,.!?;:…]", str(text or "")))


def slice_reference(cues: List[Dict[str, Any]], start: float,
                    end: float) -> str:
    """Текст авторских субтитров внутри окна; слова снаружи отбрасываются."""
    words: List[str] = []
    for cue in cues:
        for word in cue.get("words") or []:
            middle = (float(word["start"]) + float(word["end"])) / 2
            if start - 0.2 <= middle <= end + 0.2:
                token = str(word.get("word") or "").strip()
                if token:
                    words.append(token)
    return " ".join(words)


def timing_stats(segments: List[Dict[str, Any]]) -> Dict[str, Any]:
    durations = []
    for seg in segments:
        for word in seg.get("words") or []:
            span = float(word["end"]) - float(word["start"])
            if span > 0:
                durations.append(span)
    durations.sort()
    median = statistics.median(durations) if durations else 0.0
    share = (sum(1 for value in durations if 0.03 <= value <= 2.0) / len(durations)
             if durations else 0.0)
    return {"words": len(durations),
            "median_word": round(median, 3),
            "sane_share": round(share, 3)}


def _run(cmd: List[str], timeout: float = 900) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace",
                          **utils.subprocess_kwargs())


def download_item(url: str, workdir: Path, language: str) -> Tuple[Path, Path]:
    """Скачивает полное аудио и авторские субтитры. Возвращает (wav, vtt)."""
    import yt_dlp

    workdir.mkdir(parents=True, exist_ok=True)
    outtmpl = str(workdir / "audio.%(ext)s")
    audio_opts: Dict[str, Any] = {
        "format": "ba[ext=m4a]/ba/b",
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "wav",
                            "preferredquality": "0"}],
        "postprocessor_args": {"ffmpeg": ["-ar", "16000", "-ac", "1"]},
    }
    with yt_dlp.YoutubeDL(audio_opts) as ydl:
        ydl.extract_info(url, download=True)

    sub_opts: Dict[str, Any] = {
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": False,
        "subtitleslangs": [language],
        "subtitlesformat": "vtt",
        "outtmpl": str(workdir / "sub.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    try:
        with yt_dlp.YoutubeDL(sub_opts) as ydl:
            ydl.extract_info(url, download=True)
    except Exception:
        pass

    wavs = sorted(workdir.glob("audio*.wav"))
    if not wavs:
        raise RuntimeError("не удалось скачать аудио")
    subs = sorted(workdir.glob("sub*.vtt"))
    if not subs:
        raise RuntimeError("нет авторских субтитров на выбранном языке")
    return wavs[0], subs[0]


def cut_audio(source: Path, target: Path, start: float, duration: float) -> Path:
    total = utils.media_duration(source)
    length = max(5.0, min(float(duration), max(0.0, total - float(start))))
    target.parent.mkdir(parents=True, exist_ok=True)
    proc = _run([ffmpeg(), "-y", "-v", "error", "-ss", f"{max(0.0, start):.3f}",
                 "-t", f"{length:.3f}", "-i", str(source), "-ac", "1", "-ar", "16000",
                 str(target)])
    if proc.returncode != 0 or not target.exists():
        raise RuntimeError(f"не удалось вырезать фрагмент: {proc.stderr[-300:]}")
    return target


def memory_mb() -> Tuple[float, float]:
    ram = 0.0
    try:
        import psutil
        ram = psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
    except Exception:
        pass
    vram = 0.0
    try:
        proc = _run(["nvidia-smi", "--query-gpu=memory.used",
                     "--format=csv,noheader,nounits"], timeout=10)
        if proc.returncode == 0:
            values = [int(line.strip()) for line in proc.stdout.splitlines()
                      if line.strip().isdigit()]
            vram = max(values) if values else 0.0
    except Exception:
        pass
    return round(vram, 1), round(ram, 1)


def evaluate(fragment: Path, reference: str, terms: List[str],
             profile: str, model: str, language: str) -> Dict[str, Any]:
    workdir = Path(tempfile.mkdtemp(prefix="vc-bench-run-"))
    try:
        vram_before, ram_before = memory_mb()
        started = time.time()
        result = transcribe.transcribe(fragment, workdir,
                                       language=language or None,
                                       profile=profile, model=model)
        took = time.time() - started
        vram_after, ram_after = memory_mb()
        hypothesis = " ".join(seg.get("text") or ""
                              for seg in result.get("segments") or [])
        wrong, checked = term_errors(reference, hypothesis, terms)
        duration = float(result.get("duration") or 0) or utils.media_duration(fragment)
        stats = timing_stats(result.get("segments") or [])
        return {
            "config": f"profile={profile or '-'} model={result.get('model') or model}",
            "wer": wer_percent(reference, hypothesis),
            "terms_wrong": wrong,
            "terms_checked": checked,
            "punct_ref": punctuation_count(reference),
            "punct_hyp": punctuation_count(hypothesis),
            "words": stats["words"],
            "median_word": stats["median_word"],
            "sane_share": stats["sane_share"],
            "speed": round(duration / max(0.1, took), 2),
            "took": round(took, 1),
            "vram_mb": max(vram_before, vram_after),
            "ram_mb": max(ram_before, ram_after),
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def markdown(rows: List[Dict[str, Any]], items: List[Dict[str, Any]]) -> str:
    lines = [
        "# Бенчмарк Whisper",
        "",
        "Дата запуска: " + time.strftime("%Y-%m-%d %H:%M"),
        "Материал: авторские русские субтитры YouTube, фрагменты 60–90 с. "
        "Автосубтитры не используются.",
        "",
        "| Фрагмент | Конфигурация | WER, % | Термины | Пунктуация | Слов | Медиана слова, с | "
        "Тайминги в норме | Скорость | VRAM, МБ | RAM, МБ |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['kind']} | {row['config']} | {row['wer']:.1f} | "
            f"{row['terms_wrong']}/{row['terms_checked']} | "
            f"{row['punct_ref']} → {row['punct_hyp']} | {row['words']} | "
            f"{row['median_word']:.2f} | {row['sane_share'] * 100:.0f}% | "
            f"{row['speed']:.2f}× | {row['vram_mb']:.0f} | {row['ram_mb']:.0f} |")
    lines += ["", "Эталон ограничен: авторские субтитры бывают сокращёнными, "
              "поэтому WER приближённый.", ""]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Бенчмарк моделей и профилей Whisper")
    parser.add_argument("--items", required=True, help="JSON со списком фрагментов")
    parser.add_argument("--profiles", default="", help="fast,balance,max")
    parser.add_argument("--models", default="", help="small,large-v3-turbo,...")
    parser.add_argument("--language", default="ru")
    parser.add_argument("--out", default="", help="куда сохранить markdown")
    parser.add_argument("--workdir", default="", help="папка для скачивания (по умолчанию %%TEMP%%)")
    args = parser.parse_args(argv)

    data = json.loads(Path(args.items).read_text(encoding="utf-8"))
    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        print("В items.json нет фрагментов.", file=sys.stderr)
        return 2
    profiles = [p.strip() for p in args.profiles.split(",") if p.strip()]
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if not profiles and not models:
        profiles = ["fast", "balance", "max"]

    base = Path(args.workdir) if args.workdir else Path(tempfile.gettempdir()) / "vc-whisper-bench"
    base.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, Any]] = []
    for index, item in enumerate(items, 1):
        url = str(item.get("url") or "")
        if not url:
            continue
        kind = str(item.get("kind") or f"фрагмент {index}")
        start = float(item.get("start") or 0.0)
        duration = float(item.get("duration") or 75.0)
        terms = list(item.get("terms") or [])
        print(f"[{index}/{len(items)}] {kind}: скачивание", file=sys.stderr, flush=True)
        item_dir = base / f"item_{index}"
        shutil.rmtree(item_dir, ignore_errors=True)
        try:
            audio, subtitle = download_item(url, item_dir, args.language)
            fragment = cut_audio(audio, base / f"fragment_{index}.wav", start, duration)
            cues = utils.parse_vtt(subtitle)
            reference = slice_reference(cues, start, start + duration)
            if len(normalize_text(reference)) < 5:
                print(f"[{index}] в субтитрах нет текста в этом окне — пропуск",
                      file=sys.stderr)
                continue
        except Exception as exc:  # noqa: BLE001
            print(f"[{index}] пропуск: {exc}", file=sys.stderr)
            continue

        for profile in profiles:
            print(f"[{index}] профиль {profile or '-'}", file=sys.stderr, flush=True)
            try:
                row = evaluate(fragment, reference, terms, profile, "", args.language)
                row["kind"] = kind
                rows.append(row)
            except Exception as exc:  # noqa: BLE001
                print(f"[{index}] профиль {profile}: {exc}", file=sys.stderr)
        for model in models:
            print(f"[{index}] модель {model}", file=sys.stderr, flush=True)
            try:
                row = evaluate(fragment, reference, terms, "", model, args.language)
                row["kind"] = kind
                rows.append(row)
            except Exception as exc:  # noqa: BLE001
                print(f"[{index}] модель {model}: {exc}", file=sys.stderr)

    if not rows:
        print("Не удалось получить ни одного результата.", file=sys.stderr)
        return 1
    table = markdown(rows, items)
    print(table)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(table, encoding="utf-8")
        print(f"Сохранено: {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
