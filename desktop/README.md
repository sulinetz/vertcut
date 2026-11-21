# Настольная версия (macOS)

`desktop/main.py` — точка входа .app: поднимает локальный сервер на 127.0.0.1 и открывает
окно WKWebView через pywebview. Данные хранятся в `~/Library/Application Support/VertCut`.

Сборка:

```bash
./build_app.sh     # dist/VertCut.app
./build_dmg.sh     # dist/VertCut-1.0.0.dmg
```

Запуск без окна (для проверки):

```bash
VERTCUT_HEADLESS=1 VERTCUT_DATA=/tmp/vertcut dist/VertCut.app/Contents/MacOS/VertCut
```

Лог: `~/Library/Application Support/VertCut/app.log`.
