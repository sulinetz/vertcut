# VertCut — технический аудит и план рефакторинга

Дата: 2026-11-22 · База: `777a633` (ребрендинг) · Python 3.13 / Windows

---

## 1. Карта архитектуры

```
desktop/main.py            pywebview-окно, выбор порта, instance-lock, запуск uvicorn
        │
        ▼
vertcut/main.py            FastAPI: 25 роутов в одном файле, монтирование /media /static
        │
        ├── jobs.py          ThreadPoolExecutor(1) для проектов + 2 для клипов, _guarded
        ├── pipeline.py      оркестрация: download → transcribe → analyze → render
        │      ├── downloader.py   yt-dlp: форматы, cookies, HLS-секции, субтитры
        │      ├── transcribe.py   faster-whisper small, чанки, повторная проверка
        │      ├── analyze.py      эвристики «вирусности» (лексиконы RU/EN, паузы, громкость)
        │      ├── reframe.py      YuNet/Haar лица → keyframes кропа
        │      ├── subtitles.py    ASS/SRT, шрифты, переносы, караоке
        │      └── render.py       ffmpeg: кроп/блюр, субтитры, thumb, preview
        ├── live.py          запись HLS-эфиров, нарезка окон, реклама
        ├── db.py            SQLite, WAL, SCHEMA_VERSION=2, connect() на каждый вызов
        ├── config.py        пути, env (VERTCUT_*), ffmpeg()
        └── updater.py       отключён для локальной сборки (DEFAULT_API = "")
web/  app.js (1880) + styles.css (1267) + index.html — без сборки, глобальный state
tests/  test_analyze.py (13) + test_reframe.py — только 2 модуля из 17
```

Поток данных: `POST /api/projects` → `_guarded(pid)` → `prepare_project` (скачивание, статус `review`) → `POST /start` → `process_project` (транскрипт → кандидаты → клипы → рендер) → `done`. Перерендер клипа идёт отдельным пулом.

**Сильные стороны:** продуманная деградация (субтитры из источника при сбое Whisper, `blur` при отсутствии лиц), честная валидация правок клипа до очереди (`_clean_clip_edit`), экранирование ASS (`subtitles._clean`), instance-lock и редирект логов в desktop, аккуратные миграции БД, отключённый апдейтер.

---

## 2. Находки по severity

### Критично

**C1. Retry во время работы теряет отмену и может испортить клипы.**
`main.py:408-416`: при `is_running` вызывается `request_cancel(pid)` (410), а сразу затем — `clear_cancel(pid)` (413). Флаг снимается до того, как рабочий поток его увидит, поэтому старый job продолжает работу. При этом `db.clear_clips(pid)` (414) уже удалил клипов, а старый job продолжает их добавлять → уникальный индекс `(project_id, idx)` (`db.py:85`) даёт `IntegrityError` → проект уходит в `error`. В довершение старый job пишет `status="done"` поверх `queued`.
*Фикс:* не снимать флаг при активном job; вводить generation/run-token на проект и проверять его в каждом `_update`.

**C2. `/cancel` на завершённом проекте переводит его в `cancelled`.**
`main.py:393-400` не проверяет ни `status`, ни `is_running`. Готовый проект становится отменённым, клипы остаются, а запись в глобальном `CANCELLED` (`pipeline.py:93`) живёт до следующего `start`.
*Фикс:* 409, если проект не активен; удалять pid из `CANCELLED` при терминальном статусе.

**C3. Отмена не прерывает текущий ffmpeg.**
`pipeline.py:478` передаёт `lambda p: None` в `_render_one`, а `render.py:200` только читает `out_time_us`. `_check_cancel` вызывается лишь между клипами (`pipeline.py:469-476`). При 3 воркерах и длинных клипах отмена ждёт минуты, продолжая жечь CPU и диск. То же для `download_section` — хук прогресса (`downloader.py:133`) не проверяет отмену.
*Фикс:* прокинуть `should_cancel` в `render_clip`/`download_section`, по исключению убивать `Popen` в `finally`.

### Высоко

**H1. Два перерендера одного клипа пишут в один файл.** `jobs.py:109-118` + `_clip_pool` на 2 потока. `submit_rerender` не проверяет `clip.status == "rendering"` — два POST дают два ffmpeg на `clips/clip_NN.mp4`.

**H2. `upload` блокирует event loop.** `main.py:295-347`: синхронные `open/write` и `utils.probe()` (subprocess ffmpeg) внутри `async def`. `await file.read()` уступает управление раз в 1 МБ, но probe на большом файле подвешивает все HTTP, включая опрос UI. Ruff: `ASYNC230` на `main.py:309`.

**H3. Гонка статусов worker ↔ API.** `pipeline._update` пишет `status` безусловно; `project_cancel` пишет `cancelled` из потока запроса. `db.set_stage_if_active` (`db.py:102`) существует ровно для этого, но используется только heartbeat-ом (`pipeline.py:113-131`). Все записи воркера должны идти через guarded-update.

**H4. Общая модель Whisper не потокобезопасна.** `transcribe.py:35-140` держит `_MODEL`/`_MODEL_LONG` глобально; `jobs.py:12` размерен `MAX_WORKERS` (`config.py:35`, по умолчанию 1). При `VERTCUT_WORKERS>1` два проекта вызовут `model.transcribe()` на одном инстансе ctranslate2. Нужен `_TRANSCRIBE_LOCK` или модель на поток.

### Средне

| # | Находка | Где |
|---|---|---|
| M1 | Новое SQLite-соединение на каждый вызов + `PRAGMA journal_mode=WAL` каждый раз | `db.py:59-64` |
| M2 | Замыкания захватывают переменные цикла (`label` не связан дефолтом) | `pipeline.py:292-293, 313`; `transcribe.py:415`; `reframe.py:243` |
| M3 | Нет пагинации: после 50 проектов старые исчезают из сайдбара | `db.py:142`, `main.py:217` |
| M4 | `hook/title/caption` без `max_length` в модели | `main.py:50-67` |
| M5 | `export_zip` пишет архив внутрь раздаваемой папки проекта | `pipeline.py:643`, `main.py:483` |
| M6 | 16 × `except: pass`, 7 из них в desktop (глушат ошибки shutdown) | `desktop/main.py:158,402,415,437,446,496,515` и др. |
| M7 | Дублирование настроек клипа: `_clip_settings()` vs inline-копия | `pipeline.py:196` vs `444-450` |
| M8 | Нет `ruff`/`pytest` конфига: 585 замечаний, 433 из них — `UP006/UP045/UP035` из-за target `py39` | корень репо |
| M9 | Тесты покрывают 2 модуля из 17; CI гоняет только `test_analyze` | `tests/`, `.github/workflows/build.yml` |
| M10 | `test_edge_cases.py` — ручной скрипт с macOS-путём ffmpeg, на Windows не работает | `tests/test_edge_cases.py:13` |
| M11 | Фронтенд: монолит 1880 строк, глобальный `state`, полная перерисовка `innerHTML` каждые 1.3 с | `web/app.js:228, 288, 841` |
| M12 | Нет обработки обрыва связи: `poll()` тихо замирает на последнем состоянии | `web/app.js:717-724` |
| M13 | Брендинг upstream: ссылки на Telegram и релизы в документации; `docs/promo/*`, `RELEASE_NOTES.md:9-24`, `CHANGELOG.md:134` | `docs/`, корень | удалено |

### Низко / полировка

- `main.py:496` — `mkdir` на импорте модуля, хотя весь старт вынесен в `lifespan` (80-85).
- Мёртвый код: `analyze.py:262 low`, `downloader.py:250 now`, `downloader.py:844 last_error`, `pipeline.py:287 base`, `pipeline.py:323 elapsed`.
- `utils.probe` парсит stderr ffmpeg регулярками (`utils.py:38-64`) — работает, но `ffprobe -print_format json` надёжнее (потребует поставки ffprobe).
- `_render_workers()` (`pipeline.py:521-534`) не учитывает RAM: 3×1080p60 x264 может уронить 8 ГБ машину.
- `live.py` (633 строки, свой HLS-парсер и детект рекламы) — самый сложный и наименее покрытый тестами модуль.
- `desktop/main.py:421-422` навсегда подменяет `sys.stdout/stderr` — неудобно при отладке из терминала.

---

## 3. План рефакторинга (инкрементально, без «большого взрыва»)

### Фаза 0 — гигиена (≈ полдня, поведение не меняется)
1. `pyproject.toml`: `[tool.ruff] target-version="py311"`, `select = ["E","F","W","I","B","SIM","ASYNC","S","RUF"]`, `ignore = ["UP006","UP045","UP035"]`; `[tool.pytest.ini_options] testpaths=["tests"]`.
2. `ruff check --fix` (443 безопасных фикса), затем вручную F841/B023.
3. `mkdir` из `main.py:496` → в `lifespan`.
4. Удалить `docs/promo`, `docs/screenshots`, `docs/index.html`, `RELEASE_NOTES.md`; `CHANGELOG.md` почистить от Telegram/upstream-ссылок. `NOTICE.md`/`README.md` оставить — они корректно фиксируют происхождение.
5. `.gitignore`: `.venv-win/`, `data/`, `build/`, `dist/`, `__pycache__/`.

### Фаза 1 — корректность (1–2 дня)
1. **Run-token вместо `CANCELLED`**: `JobRegistry` с `{pid: Job(state, cancel_event, generation)}`. `cancel` ставит событие только для активного job; `_update` пишет статус, лишь если generation совпадает. Закрывает C1, C2, H3.
2. **Отменяемый рендер**: `render_clip(..., should_cancel=...)`, проверка в цикле чтения прогресса, `proc.kill()` в `finally`; то же в `download_section`. Закрывает C3.
3. **Гард перерендера**: 409, если клип уже `rendering` (H1).
4. **Валидация правок**: `start < end`, `end <= duration`, `Field(max_length=...)` (M4).
5. **Регрессионные тесты**: tmp-`DATA_DIR`, фейковый пайплайн, сценарии «cancel → retry», «двойной rerender».

### Фаза 2 — архитектура (3–5 дней)
1. Разбить `pipeline.py`: `stages/download.py`, `stages/transcribe.py`, `stages/analyze.py`, `stages/render.py` + `PipelineContext` (dataclass) вместо пяти аргументов в каждой функции. `process_project` (369-518) распадается на 4 читаемых шага.
2. Один `_clip_settings()` на оба пути (M7).
3. Роутеры: `api/projects.py`, `api/clips.py`, `api/fonts.py`, `api/streams.py`, `api/system.py`; `main.py` — только `create_app()`.
4. БД: соединение на поток (`threading.local`), `busy_timeout=5000`, `synchronous=NORMAL`; миграции — список шагов вместо `if current < N` (M1).
5. Логирование: `logging` + `RotatingFileHandler` вместо `print`/`traceback.print_exc`.

### Фаза 3 — фронтенд (3–5 дней)
1. ES-модули без сборщика: `api.js`, `state.js`, `components/`, `views/`. `<script type="module">`.
2. Store с `subscribe()` и точечным обновлением узлов вместо пересборки строк (M11).
3. `AbortController` + backoff + индикатор соединения в `api()` (M12).
4. Дизайн-токены в `:root`, CSS по экранам.
5. Опционально: Vite + TypeScript, если UI будет расти.

### Фаза 4 — качество (постоянно)
- pytest: db CRUD и миграции, golden-тесты ASS/SRT, pipeline со стаб-рендерером, `TestClient` на health/upload/lifecycle, чистые функции `_pick_format`, `parse_vtt`.
- CI: `ruff` + `pytest` на PR, сборка Windows; macOS-job, если поставляете mac.
- Порог покрытия ≥ 60 % по `vertcut/`.

---

## 4. Варианты улучшений (приоритет)

### P1 — быстрая ценность, низкий риск
- **Пресеты**: именованные шаблоны «аспект + шрифт + цвет + скорость» (UI-заготовка уже есть — `STYLE_PRESETS`, `app.js:205`).
- **Пакетный экспорт**: MP4+SRT одним архивом на клип, кнопка «скопировать описание/хэштеги».
- **Поиск и пагинация проектов** (M3).
- **Экран «Хранилище»**: размеры проектов, автоочистка старых — исходники по 4 ГБ быстро съедают диск.

### P2 — качество результата
- **Скоринг клипов**: вынести веса эвристик в конфиг; опционально LLM-реранк топ-N через локальную модель (Ollama); кнопки 👍/👎 для подстройки весов.
- **Субтитры**: переносы по пунктуации, safe-zone под UI TikTok/Reels/Shorts, караоке-подсветка слова.
- **Локализация**: строки из JS и Python-статусов → `locales/ru.json`, `en.json`.
- **Аппаратное кодирование**: NVENC/QSV/VideoToolbox в `render.py` (проба энкодеров уже есть, `render.py:78`) — ускорение рендера в 2–4 раза.

### P3 — платформа
- **Возобновление по этапам**: сохранять `transcript.json` и результат анализа в `workdir`, переиспользовать при ретрае (сейчас падение на транскрипции теряет всё).
- **CLI**: `python -m vertcut.cli --url … --count 10 --out dir` — автоматизация и тесты без GUI.
- **Тесты live**: локальный HLS-фикстур (playlist + ts-сегменты).
- **Апдейтер**: оставить выключенным локально; при распространении — подписанные сборки и свой фид через `VERTCUT_UPDATE_URL`.

---

## 5. Быстрые победы (можно сделать сегодня)

1. `[tool.ruff] target-version="py311"` — минус 433 замечания одной строкой.
2. `main.py:410/413` — не снимать cancel при активном job (C1).
3. `main.py:393` — 409 для неактивного проекта (C2).
4. `Field(max_length=...)` в `ClipEdit` (M4).
5. `mkdir` → `lifespan` (M13-полировка).
6. Удалить upstream-promo из `docs/` (M13).
