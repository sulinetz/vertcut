"""Слои клипа и единые допустимые значения настроек.

Модуль ничего не рисует и не запускает ffmpeg. Он отвечает на два вопроса:

1. Из каких слоёв состоит клип и в каком порядке они лежат.
2. Какие значения допустимы для каждой настройки.

Диапазоны отсюда используют ``pipeline.normalize_options`` (проект),
``main._clean_clip_edit`` (редактор клипа), ``/api/composition/schema`` и
интерфейс. Так одна и та же настройка не может иметь разные границы в разных
местах — раньше скорость в проекте ограничивалась 1.1, а в рендере 1.25.

Всё, что касается времени (склейки, паузы, вставки рекламы), считается через
``timeline.py``: там чистые функции, и именно они — источник истины.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import platforms, render, subtitles
from . import timeline

# Порядок слоёв снизу вверх. У звуковых слоёв z нет: они смешиваются, а не
# рисуются друг поверх друга.
LAYER_ORDER: Tuple[str, ...] = (
    "main", "adhd_bottom", "ads", "music", "subtitles", "graphics", "dub",
)

LAYER_TITLES: Dict[str, str] = {
    "main": "Основное видео",
    "adhd_bottom": "Нижний ролик (СДВГ)",
    "ads": "Реклама",
    "music": "Музыка",
    "subtitles": "Субтитры",
    "graphics": "Хук и плашки",
    "dub": "Дубляж",
}

LAYER_KINDS: Dict[str, str] = {
    "main": "video",
    "adhd_bottom": "video",
    "ads": "video",
    "music": "audio",
    "subtitles": "text",
    "graphics": "text",
    "dub": "audio",
}

# z только у видеослоёв; субтитры и хук вжигаются одним ASS-проходом после
# накладок рекламы, поэтому хук всегда выше субтитров.
LAYER_Z: Dict[str, Optional[int]] = {
    "main": 0,
    "adhd_bottom": 1,
    "ads": 10,
    "music": None,
    "subtitles": 20,
    "graphics": 30,
    "dub": None,
}

KINDS = ("int", "float", "bool", "choice", "events", "text")

_TRUE = {"1", "true", "yes", "on", "да", "y", "t"}
_FALSE = {"0", "false", "no", "off", "нет", "n", "f", ""}


def as_bool(value: Any, default: bool = False) -> bool:
    """bool("false") — это True; для JSON/форм нужен явный разбор."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value if value is not None else "").strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    return bool(default)


@dataclass(frozen=True)
class Setting:
    key: str
    kind: str
    layer: str
    default: Any
    label: str
    hint: str = ""
    minimum: Optional[float] = None
    maximum: Optional[float] = None
    step: float = 1.0
    decimals: int = 3
    choices: Tuple[str, ...] = ()
    unit: str = ""
    clip: bool = True  # входит в pipeline.CLIP_SETTING_KEYS

    def schema(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "type": self.kind,
            "layer": self.layer,
            "label": self.label,
            "hint": self.hint,
            "default": self.default,
            "min": self.minimum,
            "max": self.maximum,
            "step": self.step,
            "unit": self.unit,
            "choices": list(self.choices),
        }


def _s(*args: Any, **kwargs: Any) -> Setting:
    return Setting(*args, **kwargs)


SPEC: Dict[str, Setting] = {s.key: s for s in (
    # --- основное видео -------------------------------------------------
    _s("aspect", "choice", "main", "9:16", "Формат кадра",
       "9:16 — вертикаль для Shorts/Reels/TikTok. 1:1 и 16:9 — для других площадок.",
       choices=tuple(render.ASPECTS)),
    _s("mode", "choice", "main", "auto", "Кадрирование",
       "Умный кроп следит за лицом, «размытый фон» оставляет весь кадр, «обрезка» режет по центру.",
       choices=("auto", "blur", "crop")),
    _s("platform", "choice", "main", platforms.DEFAULT_PLATFORM, "Площадка",
       "От площадки зависит безопасная зона: куда можно ставить субтитры и хук.",
       choices=tuple(platforms.PLATFORMS)),
    _s("layout", "choice", "main", "", "Раскладка",
       "СДВГ-композиция делит кадр на верхнее видео и нижний ролик.",
       choices=("", *render.STREAM_LAYOUTS, "adhd")),
    _s("look", "choice", "main", "none", "Цветовой пресет",
       "Мягкая цветокоррекция кадра без изменения геометрии.",
       choices=("none", "warm", "cool", "contrast", "cinematic", "soft")),
    _s("vignette", "bool", "main", False, "Виньетка",
       "Затемняет края кадра. Сильнее всего заметно на светлом фоне."),
    _s("grain", "bool", "main", False, "Зерно",
       "Добавляет плёночный шум. Немного увеличивает размер файла."),
    _s("zoom", "int", "main", 100, "Зум",
       "Масштаб 100–120 %. Больше 110 % заметно режет качество исходника.", 100, 120, 1, unit="%"),
    _s("bitrate", "int", "main", 0, "Битрейт",
       "0 — авто. Ограничение в Мбит/с пригодится для медленного интернета.", 0, 40, 1, unit="Мбит/с"),
    _s("hflip", "bool", "main", False, "Зеркало",
       "Отражает кадр по горизонтали. Текст субтитров не зеркалится."),
    _s("tilt", "float", "main", 0.0, "Наклон",
       "Поворот кадра до 3°. Углы обрезаются, поэтому кадр приближается сам.", 0.0, 3.0, 0.5, 2, unit="°"),
    _s("speed", "float", "main", 1.0, "Скорость видео",
       "До 1.1×. Быстрее делать нельзя без пересчёта таймингов субтитров.", 1.0, 1.1, 0.01, 3, unit="×"),
    _s("pitch", "float", "main", 1.0, "Тон звука",
       "Сдвигает тон при ускорении: ниже — глубже, выше — звонче.", 0.95, 1.05, 0.01, 3, unit="×"),
    _s("jump_cuts", "bool", "main", False, "Резать паузы",
       "Убирает длинные паузы и пересчитывает слова, поэтому караоке не разъезжается."),
    _s("cut_zoom", "bool", "main", False, "Зум на склейках",
       "Чередует лёгкое приближение на каждом втором куске после резки пауз."),
    _s("bg_video", "text", "main", "random", "Фоновое видео",
       "«random» — фон из библиотеки. Имя файла задаёт конкретный фон."),
    _s("split_ratio", "float", "main", 0.5, "Доля верхнего кадра",
       "Сколько высоты занимает основное видео в СДВГ-композиции.", 0.25, 0.85, 0.01, 2, unit="доля"),
    _s("segments", "bool", "main", False, "Экономный режим",
       "Сначала анализ полного видео, потом скачивание только выбранных моментов."),
    _s("export_subs", "bool", "main", False, "Файлы субтитров",
       "Кладёт рядом с клипом .srt и .ass — для загрузки на площадку вручную."),

    # --- нижний ролик (СДВГ) --------------------------------------------
    _s("adhd_bg", "text", "adhd_bottom", "", "Фон нижнего ролика",
       "Пусто — случайный фон проекта. «local:имя» — своё видео проекта."),
    _s("adhd_top_fill", "choice", "adhd_bottom", "cover", "Заполнение верхнего кадра",
       "«cover» заполняет весь прямоугольник с обрезкой, «contain» вписывает целиком. "
       "При «contain» умный кроп отключается.",
       choices=tuple(render.ADHD_FILLS)),
    _s("adhd_bottom_fill", "choice", "adhd_bottom", "cover", "Заполнение нижнего кадра",
       "«cover» заполняет весь прямоугольник с обрезкой, «contain» вписывает целиком.",
       choices=tuple(render.ADHD_FILLS)),
    _s("adhd_top_scale", "float", "adhd_bottom", 1.0, "Масштаб верхнего кадра",
       "Увеличение верхнего видео. Края обрезаются по границам области.",
       0.5, 2.0, 0.05, 3, unit="×"),
    _s("adhd_top_offset_x", "float", "adhd_bottom", 0.0, "Сдвиг верхнего по X",
       "Сдвиг в долях ширины: 0.1 = 10 % вправо.", -0.5, 0.5, 0.01, 3),
    _s("adhd_top_offset_y", "float", "adhd_bottom", 0.0, "Сдвиг верхнего по Y",
       "Сдвиг в долях высоты области: 0.1 = 10 % вниз.", -0.5, 0.5, 0.01, 3),
    _s("adhd_bottom_scale", "float", "adhd_bottom", 1.0, "Масштаб нижнего кадра",
       "Увеличение нижнего видео. Края обрезаются по границам области.",
       0.5, 2.0, 0.05, 3, unit="×"),
    _s("adhd_bottom_offset_x", "float", "adhd_bottom", 0.0, "Сдвиг нижнего по X",
       "Сдвиг в долях ширины: 0.1 = 10 % вправо.", -0.5, 0.5, 0.01, 3),
    _s("adhd_bottom_offset_y", "float", "adhd_bottom", 0.0, "Сдвиг нижнего по Y",
       "Сдвиг в долях высоты области: 0.1 = 10 % вниз.", -0.5, 0.5, 0.01, 3),
    _s("adhd_bottom_speed", "float", "adhd_bottom", 1.0, "Скорость нижнего ролика",
       "Ускорение нижнего видео не меняет длительность клипа и его звук.",
       0.25, 4.0, 0.05, 3, unit="×"),
    _s("adhd_bottom_start", "float", "adhd_bottom", -1.0, "Старт нижнего ролика",
       "С какой секунды брать нижнее видео. -1 — случайный момент.",
       -1.0, 7200.0, 0.1, 3, unit="с"),
    _s("adhd_bottom_volume", "int", "adhd_bottom", 0, "Звук нижнего ролика",
       "Громкость нижнего видео в процентах. 0 — только картинка.",
       0, 50, 1, unit="%"),

    # --- реклама ---------------------------------------------------------
    _s("ads_enabled", "bool", "ads", True, "Показывать рекламу",
       "Быстрый выключатель всех событий рекламы, сами события сохраняются."),
    _s("ad_events", "events", "ads", [], "События рекламы",
       "Наложения и вставки. Время хранится в абсолютном времени источника."),

    # --- музыка ----------------------------------------------------------
    _s("music_volume", "int", "music", 8, "Громкость музыки",
       "Проценты от громкости исходника. 0 — музыки нет.",
       0, 50, 1, unit="%"),

    # --- субтитры --------------------------------------------------------
    _s("subtitles", "bool", "subtitles", True, "Вжигать субтитры",
       "Выключение убирает и караоке, и хук из кадра."),
    _s("accent", "choice", "subtitles", "yellow", "Цвет субтитров",
       "Цвет выделенного слова и хука.",
       choices=tuple(subtitles.ACCENTS)),
    _s("uppercase", "bool", "subtitles", True, "КАПСОМ",
       "Печатает субтитры и хук заглавными."),
    _s("show_hook", "bool", "graphics", True, "Показывать хук",
       "Заголовок сверху кадра первые секунды клипа."),
    _s("sub_size", "int", "subtitles", 118, "Размер субтитров",
       "Размер шрифта для кадра 1080×1920. Меньше 90 плохо читается на телефоне.",
       70, 180, 2, unit="px"),
    _s("sub_font", "text", "subtitles", "montserrat", "Шрифт субтитров",
       "Шрифт из встроенной коллекции или загруженный пользователем."),
    _s("sub_position", "choice", "subtitles", "bottom", "Положение субтитров",
       "Снизу — привычно и не мешает лицу. Сверху — если снизу интерфейс площадки.",
       choices=tuple(subtitles.POSITIONS)),
    _s("sub_offset", "int", "subtitles", 0, "Сдвиг субтитров",
       "Плюс — выше, минус — ниже. Держите внутри безопасной зоны площадки.",
       -1600, 1600, 10, unit="px"),
    _s("sub_speed", "choice", "subtitles", "calm", "Темп караоке",
       "Спокойный — по 1–3 слова, быстрый — короткими вспышками.",
       choices=tuple(subtitles.SPEEDS)),
    _s("line_gap", "int", "subtitles", 0, "Межстрочный интервал",
       "Дополнительный воздух между строками субтитров.",
       0, 120, 2, unit="px"),

    # --- звук -------------------------------------------------------------
    _s("audio_track", "int", "dub", -1, "Дорожка источника",
       "-1 — выбрать автоматически по языку. 0, 1, … — номер дорожки.",
       -1, 64, 1),
    _s("external_audio", "bool", "dub", False, "Дубляж",
       "Заменяет звук исходника загруженным файлом."),
    _s("external_audio_track", "int", "dub", -1, "Дорожка дубляжа",
       "-1 — первая дорожка файла дубляжа.", -1, 64, 1),
    _s("audio_offset", "float", "dub", 0.0, "Сдвиг дубляжа",
       "Сдвигает дубляж относительно картинки. Плюс — позже.",
       -300.0, 300.0, 0.1, 2, unit="с"),

    # --- только опции проекта (в клип не попадают) ------------------------
    _s("count", "int", "main", 0, "Сколько нарезок",
       "0 — авто по выбранной длине клипа.", 0, 200, 1, clip=False),
    _s("min_dur", "int", "main", 15, "Минимальная длина",
       "Нижняя граница длины клипа при поиске моментов.", 8, 120, 1,
       clip=False, unit="с"),
    _s("max_dur", "int", "main", 60, "Максимальная длина",
       "Верхняя граница длины клипа. Должна быть больше минимальной.",
       8, 180, 1, clip=False, unit="с"),
    _s("target_dur", "int", "main", 32, "Целевая длина",
       "К этой длине стремится поиск моментов.", 8, 180, 1,
       clip=False, unit="с"),
)}

#: Ключи, которые интерфейс может менять явно.
EDITABLE = tuple(key for key, item in SPEC.items() if item.clip)


class CompositionError(ValueError):
    """Недопустимое значение настройки: API отвечает 400, проект — default."""


def setting(key: str) -> Optional[Setting]:
    return SPEC.get(key)


def schema() -> Dict[str, Any]:
    """Схема для интерфейса: порядок слоёв и границы всех настроек."""
    layers: List[Dict[str, Any]] = []
    for name in LAYER_ORDER:
        keys = [item.key for item in SPEC.values()
                if item.layer == name and item.clip]
        layers.append({
            "name": name,
            "title": LAYER_TITLES[name],
            "kind": LAYER_KINDS[name],
            "z": LAYER_Z[name],
            "settings": keys,
        })
    return {
        "version": 1,
        "layers": layers,
        "settings": [item.schema() for item in SPEC.values()],
    }


def clamp_value(key: str, value: Any) -> Any:
    """Приводит значение к диапазону; при мусоре возвращает default."""
    item = SPEC.get(key)
    if item is None:
        return value
    return _coerce(item, value, strict=False)


def clamp_strict(key: str, value: Any) -> Any:
    """Как clamp_value, но мусор — исключение (для HTTP 400)."""
    item = SPEC.get(key)
    if item is None:
        raise CompositionError(f"Неизвестная настройка: {key}")
    return _coerce(item, value, strict=True)


def _coerce(item: Setting, value: Any, *, strict: bool) -> Any:
    if item.kind == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        text = str(value if value is not None else "").strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
        if strict:
            raise CompositionError(f"{item.label}: нужно да/нет")
        return item.default

    if item.kind == "choice":
        text = str(value if value is not None else item.default)
        if text in item.choices:
            return text
        if strict:
            raise CompositionError(f"{item.label}: недопустимое значение")
        return item.default

    if item.kind in ("int", "float"):
        if isinstance(value, bool):
            if strict:
                raise CompositionError(f"{item.label}: нужно число")
            return item.default
        try:
            number = float(value)
        except (TypeError, ValueError):
            if strict:
                raise CompositionError(f"{item.label}: нужно число") from None
            return item.default
        low = item.minimum if item.minimum is not None else number
        high = item.maximum if item.maximum is not None else number
        number = max(float(low), min(float(high), number))
        if item.kind == "int":
            return int(number)
        return round(number, item.decimals)

    # events / text: бизнес-логика у вызывающего (ads.normalize_events, фон).
    return value


def apply(values: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Нормализует только переданные известные ключи (без defaults)."""
    out: Dict[str, Any] = {}
    for key, value in (values or {}).items():
        if key in SPEC:
            out[key] = clamp_value(key, value)
    return out


def normalize(values: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Полный набор настроек: defaults + нормализованные переданные значения."""
    out = {key: item.default for key, item in SPEC.items()}
    out.update(apply(values))
    return out


def layer_of(key: str) -> str:
    item = SPEC.get(key)
    return item.layer if item else "main"


def layers(values: Optional[Dict[str, Any]] = None,
           *, ad_events: Optional[Sequence[Any]] = None) -> List[Dict[str, Any]]:
    """Активные слои клипа в порядке отрисовки.

    ``values`` — настройки клипа. ``ad_events`` можно передать отдельно, если
    события ещё не нормализованы (интерфейс редактирует их на лету).
    """
    opts = normalize({k: v for k, v in (values or {}).items()
                      if isinstance(v, (int, float, bool, str))})
    events = ad_events
    if events is None:
        events = [event for event in (values or {}).get("ad_events") or []
                  if isinstance(event, dict)]
    out: List[Dict[str, Any]] = []
    for name in LAYER_ORDER:
        keys = [item.key for item in SPEC.values()
                if item.layer == name and item.clip]
        active = False
        detail: Dict[str, Any] = {}
        if name == "main":
            active = True
        elif name == "adhd_bottom":
            active = opts.get("layout") == "adhd"
        elif name == "ads":
            overlays = [e for e in events if e.get("kind") != "replace"]
            inserts = [e for e in events if e.get("kind") == "replace"]
            detail = {"overlays": len(overlays), "inserts": len(inserts)}
            active = bool(opts.get("ads_enabled", True)) and bool(events)
        elif name == "music":
            active = int(opts.get("music_volume") or 0) > 0
        elif name == "subtitles":
            active = bool(opts.get("subtitles", True))
        elif name == "graphics":
            active = bool(opts.get("subtitles", True)) and bool(opts.get("show_hook", True))
        elif name == "dub":
            active = bool(opts.get("external_audio", False))
        out.append({
            "name": name,
            "title": LAYER_TITLES[name],
            "kind": LAYER_KINDS[name],
            "z": LAYER_Z[name],
            "active": active,
            "settings": keys,
            **detail,
        })
    return out


# ---------------------------------------------------------------------------
# Время: вставки рекламы и окна событий
# ---------------------------------------------------------------------------

def ad_inserts(clip: Dict[str, Any], settings: Dict[str, Any],
               tl: Dict[str, Any],
               events: Optional[Sequence[Any]] = None) -> Dict[str, Any]:
    """План вставок рекламы для уже посчитанного ``pipeline.clip_timeline``.

    Время событий хранится в абсолютном времени источника, а ``insert_spans``
    ждёт время относительно начала клипа.
    """
    span = [(0.0, max(0.1, float(clip["end"]) - float(clip["start"])))]
    source = list(events) if events is not None else list(settings.get("ad_events") or [])
    local = []
    for event in source:
        if not isinstance(event, dict) or event.get("kind") != "replace":
            continue
        try:
            start = max(0.0, float(event.get("start") or 0.0) - float(clip["start"]))
        except (TypeError, ValueError):
            continue
        local.append({**event, "start": start})
    return timeline.insert_spans(tl.get("segments") or span, local,
                                 speed=float(tl.get("speed") or 1.0),
                                 duration=float(tl.get("length") or 0.1))
