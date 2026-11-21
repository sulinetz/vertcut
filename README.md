# VertCut

Локальная сборка для превращения длинных видео в вертикальные клипы: скачивание,
распознавание речи, умное кадрирование по лицу, караоке-субтитры и рендер
9:16 / 1:1 / 16:9. Всё считается на этом компьютере, видео никуда не отправляется.

> Это форк исходного кода [ViralCut](https://github.com/vanwild11/viralcut) для
> личного использования. Права и ограничения — в [`LICENSE`](LICENSE) и
> [`NOTICE.md`](NOTICE.md).

## Запуск на Windows

Нужен Python 3.11–3.13 x64 (проверено на 3.13) и ~2 ГБ на диске под зависимости
и модель Whisper.

```bat
run_windows.bat
```

Скрипт создаст `.venv-win`, поставит зависимости и откроет окно приложения.
Повторный запуск — тот же файл, установка пропускается.

Вручную:

```powershell
py -3.13 -m venv .venv-win
.\.venv-win\Scripts\python.exe -m pip install -r requirements-desktop.txt
.\.venv-win\Scripts\python.exe desktop\main.py
```

Только сервер, без окна (UI в браузере):

```powershell
.\.venv-win\Scripts\python.exe -m vertcut --port 8765
```

## Где лежат данные

`%APPDATA%\VertCut` — база, проекты, скачанные модели, логи (`app.log`).

Модель Whisper (`small`, ~500 МБ) скачивается при первой транскрипции.
`ffmpeg` подтягивается из пакета `imageio-ffmpeg`.

## Настройки через переменные окружения

| Переменная | По умолчанию | Что делает |
|---|---|---|
| `VERTCUT_DATA` | `%APPDATA%\VertCut` | папка данных |
| `VERTCUT_WHISPER` | `small` | размер модели: `tiny`/`base`/`small`/`medium`/`large-v3` |
| `VERTCUT_WHISPER_DIR` | — | путь к локальной папке с моделью |
| `VERTCUT_DEVICE` | `auto` | `auto`/`cpu`/`cuda` |
| `VERTCUT_COMPUTE` | `int8` | тип вычислений CTranslate2 |
| `VERTCUT_WORKERS` | `1` | параллельные обработки |
| `VERTCUT_PORT` | `8765` | порт локального API |
| `VERTCUT_FFMPEG` | — | путь к своему `ffmpeg` |

Старые имена `VIRALCUT_*` продолжают работать как запасной вариант.

## Структура

```
vertcut/    бэкенд: FastAPI, скачивание, Whisper, кадрирование, субтитры, рендер
web/        интерфейс (index.html, app.js, styles.css)
desktop/    окно pywebview + запуск сервера
assets/     шрифты, иконки, модель YuNet, плагины yt-dlp
tests/      pytest
tools/      служебные скрипты (проверка UI, рендера, шрифтов)
```

## Тесты

```powershell
.\.venv-win\Scripts\python.exe -m pytest -q
```
