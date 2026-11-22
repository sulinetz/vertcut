"""Умное кадрирование: поиск лиц и плавное слежение для вертикального кадра.

Возвращает путь окна кадрирования (keyframes), который render.py превращает
в выражение для ffmpeg crop. Без лиц — центральный кроп.
"""
from __future__ import annotations

import math
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import utils
from .config import ASSETS_DIR

_MODEL = ASSETS_DIR / "models" / "yunet.onnx"


def _model_candidates() -> List[Path]:
    """Пути к модели YuNet.

    OpenCV на Windows не открывает ONNX, если в пути есть не-ASCII символы
    (например, папка «Проект по умолчанию»). Поэтому при необходимости
    кладём копию во временную папку и пробуем её тоже.
    """
    paths = [_MODEL]
    try:
        str(_MODEL).encode("ascii")
    except UnicodeEncodeError:
        try:
            cache = Path(tempfile.gettempdir()) / "vertcut_models"
            cache.mkdir(parents=True, exist_ok=True)
            target = cache / "yunet.onnx"
            if not target.exists() or target.stat().st_size != _MODEL.stat().st_size:
                shutil.copy2(_MODEL, target)
            paths.append(target)
        except OSError:
            pass
    return paths


def _make_detector():
    import cv2

    if _MODEL.exists():
        for path in _model_candidates():
            try:
                return "yunet", cv2.FaceDetectorYN.create(str(path), "", (320, 320), 0.6, 0.3, 5000)
            except Exception:  # noqa: BLE001 — модель может не подойти этой сборке OpenCV
                continue
    if hasattr(cv2, "CascadeClassifier"):
        return "haar", None
    return "none", None


def _detect(detector: Tuple[str, Any], frame) -> List[Dict[str, float]]:
    import cv2

    kind, det = detector
    h, w = frame.shape[:2]
    out: List[Dict[str, float]] = []
    if kind == "none":
        return out
    if kind == "yunet" and det is not None:
        try:
            det.setInputSize((w, h))
            _, faces = det.detect(frame)
        except Exception:
            faces = None
        if faces is not None:
            for f in faces:
                x, y, fw, fh = float(f[0]), float(f[1]), float(f[2]), float(f[3])
                score = float(f[-1])
                if score < 0.5 or fw < 16:
                    continue
                out.append({"cx": x + fw / 2, "cy": y + fh / 2, "w": fw, "h": fh, "score": score})
        return out

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if not hasattr(cv2, "CascadeClassifier"):
        return out
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(24, 24))
    for (x, y, fw, fh) in faces:
        out.append({"cx": x + fw / 2, "cy": y + fh / 2, "w": float(fw), "h": float(fh), "score": 1.0})
    return out


def _mouth_patch(frame, face: Dict[str, float], size: int = 8):
    """Мини-патч области рта: по нему ловим артикуляцию между кадрами."""
    import cv2

    h, w = frame.shape[:2]
    cx, cy = face["cx"], face["cy"]
    fw, fh = max(8.0, face["w"]), max(8.0, face["h"])
    # рот — в нижней трети лица
    mx0 = int(max(0, cx - fw * 0.22))
    mx1 = int(min(w, cx + fw * 0.22))
    my0 = int(max(0, cy + fh * 0.18))
    my1 = int(min(h, cy + fh * 0.42))
    if mx1 - mx0 < 4 or my1 - my0 < 3:
        return None
    patch = frame[my0:my1, mx0:mx1]
    if patch.ndim == 3:
        patch = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    return cv2.resize(patch, (size, size)).astype("float32")


def _mouth_motion(prev_faces, prev_patches, faces, patches) -> List[float]:
    """Насколько сильно изменился рот каждого лица относительно прошлого кадра."""
    scores: List[float] = []
    for face, patch in zip(faces, patches):
        if patch is None or not prev_faces:
            scores.append(0.0)
            continue
        best, best_dist = 0.0, 1e9
        for pface, ppatch in zip(prev_faces, prev_patches):
            if ppatch is None:
                continue
            dist = abs(pface["cx"] - face["cx"]) + abs(pface["cy"] - face["cy"])
            if dist > face["w"] * 1.2:
                continue
            if dist < best_dist:
                best_dist = dist
                best = float(abs(patch - ppatch).mean())
        scores.append(best)
    return scores


def _inside(face: Dict[str, float], rect: Tuple[float, float, float, float]) -> bool:
    x0, y0, x1, y1 = rect
    return x0 <= face["cx"] <= x1 and y0 <= face["cy"] <= y1


def _facecam_box(face_w: float, face_h: float, cx: float, cy: float,
                 src_w: int, src_h: int) -> Dict[str, float]:
    """Прямоугольник врезки вокруг стабильного маленького лица.

    Берём квадрат с запасом вокруг лица: врезка обычно включает плечи и фон,
    а не только лицо.
    """
    side = max(4.6 * face_w, 2.0 * face_h)
    side = max(0.14 * src_w, min(0.34 * src_w, side))
    w = side
    h = side * 0.78
    x = cx - w / 2
    y = cy - h * 0.42
    x = max(0.0, min(src_w - w, x))
    y = max(0.0, min(src_h - h, y))
    return {"x": round(x, 1), "y": round(y, 1), "w": round(w, 1), "h": round(h, 1)}


def detect_facecam(source: Path, start: float, end: float,
                   sample_fps: float = 2.0, max_width: int = 960,
                   min_share: float = 0.45) -> Optional[Dict[str, Any]]:
    """Ищет врезку с лицом: маленькое лицо, которое стоит на одном месте.

    Возвращает {"x","y","w","h","share","source"} в пикселях исходника
    или None, если стабильной врезки нет.
    """
    try:
        import cv2
    except Exception:
        return None
    info = utils.probe(source)
    src_w, src_h = info["width"], info["height"]
    if not src_w or not src_h:
        return None

    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        return None
    detector = _make_detector()
    buckets: Dict[Tuple[int, int], List[Dict[str, float]]] = {}
    total = 0
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        step = max(1, int(round(fps / max(0.5, sample_fps))))
        cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000.0)
        index = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            ts = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            if ts < start - 0.05:
                index += 1
                continue
            if ts > end:
                break
            if index % step == 0:
                total += 1
                fh, fw = frame.shape[:2]
                scale = min(1.0, max_width / max(1, fw))
                small = cv2.resize(frame, (int(fw * scale), int(fh * scale))) if scale < 1 else frame
                faces = _detect(detector, small)
                for face in faces:
                    if scale < 1:
                        for key in ("cx", "cy", "w", "h"):
                            face[key] /= scale
                    if face["w"] > 0.32 * src_w:
                        continue
                    key = (round(face["cx"] / (0.04 * src_w)), round(face["cy"] / (0.04 * src_h)))
                    buckets.setdefault(key, []).append(face)
            index += 1
    finally:
        cap.release()

    if not buckets or total == 0:
        return None
    best = max(buckets.values(), key=len)
    share = len(best) / total
    if share < min_share:
        return None
    cx = sorted(f["cx"] for f in best)[len(best) // 2]
    cy = sorted(f["cy"] for f in best)[len(best) // 2]
    fw = sorted(f["w"] for f in best)[len(best) // 2]
    fh = sorted(f["h"] for f in best)[len(best) // 2]
    box = _facecam_box(fw, fh, cx, cy, src_w, src_h)
    box.update({"share": round(share, 3), "source": [src_w, src_h]})
    return box


def _median(values: Sequence[float], window: int = 5) -> List[float]:
    out: List[float] = []
    half = window // 2
    for i in range(len(values)):
        chunk = sorted(values[max(0, i - half): min(len(values), i + half + 1)])
        out.append(chunk[len(chunk) // 2])
    return out


def _smooth(values: List[Optional[float]], alpha: float = 0.25,
            max_speed: float = 160.0, dt: float = 0.5) -> List[float]:
    """Заполняет пропуски, сглаживает EMA и ограничивает скорость движения окна."""
    filled: List[float] = []
    last: Optional[float] = None
    for v in values:
        if v is None:
            if last is None:
                filled.append(float("nan"))
            else:
                filled.append(last)
        else:
            last = v
            filled.append(v)

    known = [v for v in filled if not math.isnan(v)]
    if not known:
        return []
    default = known[len(known) // 2]
    filled = [default if math.isnan(v) else v for v in filled]
    med = _median(filled, 3)

    out: List[float] = []
    current = med[0]
    for target in med:
        current += (target - current) * alpha
        delta = current - (out[-1] if out else current)
        limit = max_speed * dt
        if abs(delta) > limit:
            current = (out[-1] if out else current) + math.copysign(limit, delta)
        out.append(current)
    return out


def build_crop_path(source: Path, start: float, end: float, aspect: str = "9:16",
                    sample_fps: float = 2.0, max_width: int = 960,
                    exclude: Optional[Tuple[float, float, float, float]] = None,
                    avoid: Optional[Tuple[float, float, float, float]] = None) -> Optional[Dict[str, Any]]:
    """Анализирует фрагмент и возвращает keyframes окна кадрирования.

    exclude — прямоугольник, лица внутри которого игнорируются (врезка).
    avoid — прямоугольник, который окно по возможности не должно накрывать.

    Результат: {"x": [...], "y": [...], "times": [...], "crop_w": int, "crop_h": int}
    Координаты — в пикселях исходного видео, times — секунды от начала клипа.
    """
    try:
        import cv2
    except Exception:
        return None

    info = utils.probe(source)
    src_w, src_h = info["width"], info["height"]
    aw, ah = (9, 16)
    try:
        aw, ah = [int(v) for v in aspect.split(":")]
    except Exception:
        pass

    # окно кадрирования под целевой аспект, максимально возможное (без апскейла по ширине)
    if src_w / src_h > aw / ah:
        crop_h = src_h
        crop_w = max(2, int(round(src_h * aw / ah)))
    else:
        crop_w = src_w
        crop_h = max(2, int(round(src_w * ah / aw)))

    cap = cv2.VideoCapture(str(source))
    if not cap.isOpened():
        return None
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        duration = max(0.1, end - start)
        step = max(1, int(round(fps / max(0.5, sample_fps))))
        cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000.0)

        detector = _make_detector()
        samples: List[Tuple[float, List[Dict[str, float]], List[Any]]] = []
        frame_idx = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            ts = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0
            if ts < start - 0.05:
                frame_idx += 1
                continue
            if ts > end:
                break
            if frame_idx % step == 0:
                h, w = frame.shape[:2]
                scale = min(1.0, max_width / max(1, w))
                small = cv2.resize(frame, (int(w * scale), int(h * scale))) if scale < 1 else frame
                faces = _detect(detector, small)
                if scale < 1:
                    for face in faces:
                        for key in ("cx", "cy", "w", "h"):
                            face[key] /= scale
                if exclude is not None:
                    keep = [i for i, f in enumerate(faces) if not _inside(f, exclude)]
                    faces = [faces[i] for i in keep]
                mouth = [_mouth_patch(frame, face) for face in faces]
                samples.append((max(0.0, ts - start), faces, mouth))
            frame_idx += 1

        if not samples:
            return None

        dt = max(0.05, duration / max(1, len(samples) - 1))
        xs: List[Optional[float]] = []
        ys: List[Optional[float]] = []
        prev_cx: Optional[float] = None

        prev_faces: List[Dict[str, float]] = []
        prev_mouth: List[Any] = []
        speaker_idx: Optional[int] = None
        last_switch = -99.0
        for ts, faces, mouth in samples:
            if not faces:
                xs.append(None)
                ys.append(None)
                prev_faces, prev_mouth = [], []
                continue
            order = sorted(range(len(faces)), key=lambda k: faces[k]["w"] * faces[k]["h"], reverse=True)
            faces = [faces[k] for k in order]
            mouth = [mouth[k] for k in order]
            motion = _mouth_motion(prev_faces, prev_mouth, faces, mouth)
            if speaker_idx is None or speaker_idx >= len(faces):
                speaker_idx = 0
            elif len(faces) > 1 and len(motion) == len(faces):
                best = max(range(len(motion)), key=lambda k: motion[k])
                # смена говорящего только при явном перевесе и не чаще раза в 1.2 с:
                # иначе окно дёргается между людьми на каждом кадре
                current = motion[speaker_idx] if speaker_idx < len(motion) else 0.0
                if (best != speaker_idx and motion[best] > max(1.2, current * 1.6)
                        and ts - last_switch > 1.2):
                    speaker_idx = best
                    last_switch = ts
            speaker = speaker_idx
            primary = faces[speaker] if 0 <= speaker < len(faces) else faces[0]
            if prev_cx is not None and len(faces) > 1 and speaker == 0:
                # без явного говорящего держимся за тем же человеком, а не прыгаем
                def cost(f: Dict[str, float]) -> float:
                    return abs(f["cx"] - prev_cx) / max(1.0, src_w) + 0.35 * (1 - f["w"] / max(1.0, faces[0]["w"]))
                primary = min(faces, key=cost)
            prev_faces, prev_mouth = faces, mouth
            prev_cx = primary["cx"]

            # если два лица рядом и оба влезают в окно — центрируем между ними
            cx = primary["cx"]
            near = [f for f in faces if abs(f["cx"] - primary["cx"]) < crop_w * 0.95]
            if len(near) >= 2:
                cx = sum(f["cx"] for f in near) / len(near)

            xs.append(cx)
            ys.append(primary["cy"])

        if not any(v is not None for v in xs):
            center_x = max(0.0, (src_w - crop_w) / 2)
            center_y = max(0.0, (src_h - crop_h) / 2)
            return {"times": [0.0, duration], "x": [center_x, center_x],
                    "y": [center_y, center_y], "crop_w": crop_w, "crop_h": crop_h,
                    "faces": 0, "samples": len(samples), "coverage": 0.0,
                    "source": [src_w, src_h]}

        smooth_x = _smooth(xs, alpha=0.5, max_speed=max(60.0, crop_w * 0.6), dt=dt)
        smooth_y = _smooth(ys, alpha=0.3, max_speed=max(40.0, crop_h * 0.4), dt=dt)

        max_x = max(0.0, src_w - crop_w)
        max_y = max(0.0, src_h - crop_h)
        # Врезку не накрываем окном, если это возможно без выхода за кадр.
        avoid_x0, avoid_y0 = 0.0, 0.0
        if avoid is not None:
            ax0, ay0, ax1, ay1 = avoid
            if ax1 + crop_w <= src_w:
                avoid_x0 = ax1
            elif ax0 - crop_w >= 0:
                avoid_x0 = 0.0
            if ay1 + crop_h <= src_h:
                avoid_y0 = ay1
        times: List[str] = []
        path_x: List[float] = []
        path_y: List[float] = []
        for (ts, _, _), cx, cy in zip(samples, smooth_x, smooth_y):
            x = max(avoid_x0, min(max_x, cx - crop_w / 2))
            # голова должна оставаться в кадре целиком: держим лицо по центру-верху
            y = max(avoid_y0, min(max_y, cy - crop_h * 0.42))
            times.append(round(ts, 3))
            path_x.append(round(x, 1))
            path_y.append(round(y, 1))

        face_frames = sum(1 for _, f, _ in samples if f)
        return {
            "times": times,
            "x": path_x,
            "y": path_y,
            "crop_w": crop_w,
            "crop_h": crop_h,
            "faces": face_frames,
            "samples": len(samples),
            "coverage": round(face_frames / max(1, len(samples)), 3),
            "source": [src_w, src_h],
        }
    finally:
        cap.release()


def _piecewise(times: List[float], values: List[float], clamp_max: float, var: str = "t") -> str:
    """Выражение ffmpeg: кусочно-линейная интерполяция через сумму ramp-функций."""
    if not times or not values:
        return "0"
    if len(times) == 1:
        return f"{values[0]:.1f}"
    slopes: List[float] = []
    for i in range(len(times) - 1):
        dt = max(1e-3, times[i + 1] - times[i])
        slopes.append((values[i + 1] - values[i]) / dt)

    expr = f"{values[0]:.1f}"
    prev_slope = 0.0
    for i, slope in enumerate(slopes):
        delta = slope - prev_slope
        prev_slope = slope
        if abs(delta) < 1e-4:
            continue
        expr += f"+({delta:.3f})*max(0\\,{var}-{times[i]:.3f})"
    # после последнего keyframe движение прекращается
    delta = -prev_slope
    if abs(delta) > 1e-4:
        expr += f"+({delta:.3f})*max(0\\,{var}-{times[-1]:.3f})"
    return f"max(0\\,min({clamp_max:.1f}\\,{expr}))"


def _decimate_path(times: List[float], xs: List[float], ys: List[float],
                   limit: int = 64) -> Tuple[List[float], List[float], List[float]]:
    """Прореживает траекторию: ffmpeg не переваривает выражения на сотни термов.

    При 2 fps путь за 90 секунд — это ~180 keyframes и ~20 КБ выражения.
    Встроенный парсер ffmpeg падает с «Missing ')' or too many args».
    Оставляем не больше `limit` равномерных точек: движение всё равно плавное.
    """
    count = len(times)
    if count <= limit or limit < 2:
        return times, xs, ys
    step = (count - 1) / (limit - 1)
    indices: List[int] = []
    for i in range(limit):
        index = int(round(i * step))
        if not indices or index != indices[-1]:
            indices.append(index)
    if indices[-1] != count - 1:
        indices.append(count - 1)
    return ([times[i] for i in indices],
            [xs[i] for i in indices],
            [ys[i] for i in indices])


def crop_expressions(path: Dict[str, Any]) -> Tuple[str, str]:
    """Возвращает (x_expr, y_expr) для фильтра crop."""
    times = [float(t) for t in path["times"]]
    xs = [float(v) for v in path["x"]]
    ys = [float(v) for v in path["y"]]
    times, xs, ys = _decimate_path(times, xs, ys)
    max_x = max(0.0, path["source"][0] - path["crop_w"])
    max_y = max(0.0, path["source"][1] - path["crop_h"])
    x_expr = _piecewise(times, xs, max_x, "t")
    y_expr = _piecewise(times, ys, max_y, "t")
    return x_expr, y_expr
