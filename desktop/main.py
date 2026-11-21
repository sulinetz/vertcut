"""Точка входа настольного ViralCut для macOS и Windows.

Поднимает локальный сервер в фоновом потоке и открывает окно WebView
(WKWebView на macOS, EdgeChromium/WebView2 на Windows).
Данные (проекты, модель, БД) хранятся в папке приложения:
macOS — ~/Library/Application Support/ViralCut, Windows — %APPDATA%\\ViralCut.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tarfile
import threading
import time
import traceback
import urllib.request
from pathlib import Path
from typing import Any, Dict

APP_NAME = "ViralCut"

# при запуске из исходников (python desktop/main.py) пакет viralcut лежит рядом
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

IS_WINDOWS = sys.platform.startswith("win")
IS_MACOS = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")

if IS_WINDOWS:
    import msvcrt  # type: ignore[import-not-found]
else:
    import fcntl  # type: ignore[import-not-found]


def _windows_downloads() -> Path | None:
    """Системная папка «Загрузки» на Windows (учитывает OneDrive-редирект)."""
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                        ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

        folder_id = GUID(0x374DE290, 0x123F, 0x4565,
                         (ctypes.c_ubyte * 8)(0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B))
        path_ptr = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(
                ctypes.byref(folder_id), 0, None, ctypes.byref(path_ptr)) == 0 and path_ptr.value:
            value = path_ptr.value
            ctypes.windll.ole32.CoTaskMemFree(path_ptr)
            return Path(value)
    except Exception:
        return None
    return None


def _linux_downloads() -> Path | None:
    config = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")) / "user-dirs.dirs"
    try:
        for line in config.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith("XDG_DOWNLOAD_DIR"):
                raw = line.split("=", 1)[1].strip().strip('"').replace("$HOME", str(Path.home()))
                if raw:
                    return Path(raw)
    except Exception:
        return None
    return None


def downloads_dir() -> Path:
    """Папка «Загрузки» по правилам ОС, а не догадка про ~/Downloads."""
    found = None
    if IS_WINDOWS:
        found = _windows_downloads()
    elif IS_LINUX:
        found = _linux_downloads()
    folder = found or (Path.home() / "Downloads")
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        folder = Path.home()
    return folder


class DesktopApi:
    """Нативные действия для окна: сохранение файлов и Finder."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir

    def _downloads(self) -> Path:
        folder = downloads_dir() / "ViralCut"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    @staticmethod
    def _ask_enabled() -> bool:
        return os.environ.get("VIRALCUT_ASK_SAVE", "1") != "0"

    def _ask_target(self, suggested: str):
        """Диалог «Сохранить как»: сразу в системной папке «Загрузки».

        Возвращает Path, None (пользователь закрыл диалог) или "unavailable",
        когда окно ещё не готово/платформа не умеет диалог — тогда сохраняем
        в Загрузки/ViralCut без вопроса.
        """
        try:
            import webview

            windows = getattr(webview, "windows", None) or []
            if not windows:
                return "unavailable"
            chosen = windows[0].create_file_dialog(
                webview.SAVE_DIALOG,
                directory=str(self._downloads()),
                save_filename=suggested,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"save dialog failed: {exc}", flush=True)
            return "unavailable"
        if not chosen:
            return None
        value = chosen[0] if isinstance(chosen, (list, tuple)) else chosen
        return Path(str(value))

    @staticmethod
    def _safe(name: str) -> str:
        import re

        value = re.sub(r"[^\w\- ]+", "", name or "clip", flags=re.UNICODE).strip()
        return (value[:70] or "clip").strip()

    @staticmethod
    def _unique(path: Path) -> Path:
        if not path.exists():
            return path
        for i in range(2, 1000):
            candidate = path.with_name(f"{path.stem} ({i}){path.suffix}")
            if not candidate.exists():
                return candidate
        return path

    def _reveal(self, path: Path) -> None:
        try:
            if IS_WINDOWS:
                subprocess.Popen(["explorer", f"/select,{path}"])
            elif IS_MACOS:
                subprocess.Popen(["open", "-R", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path.parent)])
        except Exception:
            pass

    def save_clip(self, clip_id: str) -> Dict[str, Any]:
        from viralcut import db

        clip = db.get_clip(clip_id)
        if not clip or not clip.get("path"):
            return {"ok": False, "error": "Клип не найден"}
        src = Path(clip["path"])
        if not src.exists():
            return {"ok": False, "error": "Файл клипа не найден на диске"}
        name = f"{clip.get('idx', 0) + 1:02d}_{self._safe(clip.get('title') or 'clip')}.mp4"
        # VIRALCUT_ASK_SAVE=0 — сохранять молча в Загрузки/ViralCut (пакетный экспорт).
        target = self._ask_target(name) if self._ask_enabled() else "unavailable"
        if target is None:
            return {"ok": False, "cancelled": True}
        if target == "unavailable":
            dest = self._unique(self._downloads() / name)
        else:
            dest = target if target.suffix.lower() == ".mp4" else target.with_suffix(".mp4")
            dest = self._unique(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        self._reveal(dest)
        return {"ok": True, "path": str(dest), "folder": str(dest.parent)}

    def save_zip(self, project_id: str) -> Dict[str, Any]:
        from viralcut import db, pipeline
        from viralcut.config import PROJECTS_DIR

        project = db.get_project(project_id)
        if not project:
            return {"ok": False, "error": "Проект не найден"}
        archive = PROJECTS_DIR / project_id / f"viralcut_{project_id}.zip"
        try:
            pipeline.export_zip(project_id, archive)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)[:300]}
        name = f"viralcut_{self._safe(project.get('title') or 'clips')}.zip"
        target = self._ask_target(name) if self._ask_enabled() else "unavailable"
        if target is None:
            return {"ok": False, "cancelled": True}
        if target == "unavailable":
            dest = self._unique(self._downloads() / name)
        else:
            dest = target if target.suffix.lower() == ".zip" else target.with_suffix(".zip")
            dest = self._unique(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(archive, dest)
        self._reveal(dest)
        return {"ok": True, "path": str(dest), "folder": str(dest.parent)}

    def open_url(self, url: str) -> Dict[str, Any]:
        """Открывает внешнюю ссылку в системном браузере (Telegram-канал и т.п.)."""
        from urllib.parse import urlparse

        parsed = urlparse(url or "")
        if parsed.scheme not in ("https", "http") or not parsed.netloc:
            return {"ok": False, "error": "Некорректная ссылка"}
        try:
            import webbrowser

            webbrowser.open(url, new=2, autoraise=True)
            return {"ok": True}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)[:200]}

    def open_project_folder(self, project_id: str) -> Dict[str, Any]:
        from viralcut.config import PROJECTS_DIR

        folder = PROJECTS_DIR / project_id / "clips"
        if not folder.exists():
            folder = PROJECTS_DIR / project_id
        try:
            if IS_WINDOWS:
                os.startfile(str(folder))  # type: ignore[attr-defined]
            elif IS_MACOS:
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "path": str(folder)}


def default_data_dir() -> Path:
    env = os.environ.get("VIRALCUT_DATA")
    if env:
        return Path(env).expanduser().resolve()
    if IS_WINDOWS:
        root = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
        return root / APP_NAME
    if IS_MACOS:
        return Path.home() / "Library" / "Application Support" / APP_NAME
    root = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
    return root / APP_NAME


def free_port(start: int = 8765, attempts: int = 40) -> int:
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("Не удалось найти свободный порт")


def wait_health(port: int, timeout: float = 40.0) -> bool:
    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/api/health"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as resp:
                if resp.status == 200 and json.loads(resp.read().decode()).get("ok"):
                    return True
        except Exception:
            time.sleep(0.15)
    return False


def _node_name() -> str:
    return "node.exe" if IS_WINDOWS else "node"


def vendor_dir(data_dir: Path) -> Path:
    """Возвращает папку с Node и PO-провайдером, распаковывая архив при первом запуске."""
    if not getattr(sys, "frozen", False):
        return Path(__file__).resolve().parent / "vendor"
    dest = data_dir / "runtime" / "vendor"
    node_name = _node_name()
    if (dest / node_name).exists() and (dest / "pot" / "build" / "main.js").exists():
        return dest

    exe = Path(sys.executable).resolve()
    candidates = [
        Path(getattr(sys, "_MEIPASS", exe.parent)) / "bundle" / "vendor.tar.gz",
        Path(getattr(sys, "_MEIPASS", exe.parent)) / "vendor.tar.gz",
        exe.parent.parent / "Frameworks" / "bundle" / "vendor.tar.gz",
        exe.parent.parent / "Resources" / "bundle" / "vendor.tar.gz",
        exe.parent.parent / "Resources" / "vendor.tar.gz",
    ]
    archive = next((c for c in candidates if c.is_file()), None)
    if archive is None:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / "vendor.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    with tarfile.open(archive, "r:gz") as tar:
        try:
            tar.extractall(tmp, filter="data")  # Python 3.12+
        except TypeError:
            tar.extractall(tmp)
    shutil.rmtree(dest, ignore_errors=True)
    tmp.rename(dest)
    node = dest / node_name
    if node.exists() and not IS_WINDOWS:
        node.chmod(0o755)
    return dest


def seed_ejs_cache(data_dir: Path, vendor: Path) -> None:
    """Кладём solver для YouTube JS-челленджей в кэш, чтобы не качать его при первом видео."""
    src = vendor / "ejs" / "challenge-solver"
    dst = data_dir / "cache" / "yt-dlp" / "challenge-solver"
    if src.exists() and not (dst / "lib.json").exists():
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src, dst, dirs_exist_ok=True)
        except Exception as exc:  # noqa: BLE001
            print(f"ejs cache seed failed: {exc}", flush=True)


def start_pot_provider(data_dir: Path, vendor: Path, log) -> "subprocess.Popen | None":
    """Поднимает локальный PO-token провайдер (нужен для HD с YouTube)."""
    node = vendor / _node_name()
    server = vendor / "pot" / "build" / "main.js"
    if not node.exists() or not server.exists():
        print("POT provider not bundled — HD may be unavailable", flush=True)
        return None
    try:
        port = free_port(4416)
        env = os.environ.copy()
        env["XDG_CACHE_HOME"] = str(data_dir / "cache")
        extra: dict = {}
        if IS_WINDOWS:
            extra["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        proc = subprocess.Popen(
            [str(node), str(server), "--port", str(port)],
            cwd=str(vendor / "pot"), env=env, stdout=log, stderr=log, **extra,
        )
        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=1) as resp:
                    if resp.status == 200:
                        os.environ["VIRALCUT_POT_URL"] = f"http://127.0.0.1:{port}"
                        os.environ["VIRALCUT_NODE"] = str(node)
                        print(f"POT provider: http://127.0.0.1:{port}", flush=True)
                        return proc
            except Exception:
                time.sleep(0.2)
        print("POT provider did not start in time", flush=True)
        proc.terminate()
    except Exception as exc:  # noqa: BLE001
        print(f"POT provider failed: {exc}", flush=True)
    return None


def setup_paths(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["VIRALCUT_DATA"] = str(data_dir)
    os.environ.setdefault("XDG_CACHE_HOME", str(data_dir / "cache"))
    if getattr(sys, "frozen", False):
        bundle = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        if str(bundle) not in sys.path:
            sys.path.insert(0, str(bundle))
        bundled_model = bundle / "models" / "whisper-small"
        if (bundled_model / "model.bin").is_file():
            os.environ["VIRALCUT_WHISPER_DIR"] = str(bundled_model)


def _acquire_instance_lock(data_dir: Path):
    """Межплатформенная блокировка одного экземпляра на папку данных."""
    data_dir.mkdir(parents=True, exist_ok=True)
    handle = open(data_dir / "instance.lock", "a+", encoding="utf-8")
    try:
        if IS_WINDOWS:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write("0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle
    except OSError:
        try:
            handle.close()
        except Exception:
            pass
        return None


def main() -> None:
    data_dir = default_data_dir()
    setup_paths(data_dir)
    # один экземпляр на папку данных
    lock = _acquire_instance_lock(data_dir)
    if lock is None:
        try:
            print("ViralCut уже запущен — второй экземпляр не нужен", flush=True)
        except Exception:
            pass
        return

    log_path = data_dir / "app.log"
    log = open(log_path, "a", buffering=1, encoding="utf-8")
    sys.stdout = log  # type: ignore[assignment]
    sys.stderr = log  # type: ignore[assignment]
    print(f"\n=== {APP_NAME} start {time.strftime('%Y-%m-%d %H:%M:%S')} ===", flush=True)
    print(f"data: {data_dir}", flush=True)
    print(f"platform: {sys.platform}", flush=True)
    print(f"frozen: {getattr(sys, 'frozen', False)}", flush=True)

    pot_proc = None
    server = None
    clean_exit = False

    def shutdown(*_args: Any) -> None:
        nonlocal pot_proc
        try:
            if server is not None:
                server.should_exit = True
        except Exception:
            pass
        if pot_proc is not None:
            try:
                pot_proc.terminate()
                pot_proc.wait(timeout=3)
            except Exception:
                try:
                    pot_proc.kill()
                except Exception:
                    pass
            pot_proc = None

    try:
        vendor = vendor_dir(data_dir)
        seed_ejs_cache(data_dir, vendor)
        pot_proc = start_pot_provider(data_dir, vendor, log)

        import uvicorn

        from viralcut.main import app as fastapi_app

        port = int(os.environ.get("VIRALCUT_PORT") or free_port())
        config = uvicorn.Config(
            fastapi_app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            access_log=False,
            lifespan="on",
        )
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, name="viralcut-http", daemon=True)
        thread.start()

        if not wait_health(port):
            raise RuntimeError("Сервер не запустился за 40 секунд")

        print(f"server: http://127.0.0.1:{port}", flush=True)
        url = f"http://127.0.0.1:{port}/"

        if os.environ.get("VIRALCUT_HEADLESS"):
            print("headless mode", flush=True)
            while True:
                time.sleep(1)

        import webview

        window = webview.create_window(
            APP_NAME,
            url,
            width=1380,
            height=900,
            min_size=(1024, 720),
            background_color="#07070a",
            js_api=DesktopApi(data_dir),
        )
        try:
            window.events.closing += shutdown
        except Exception:
            pass
        auto_close = os.environ.get("VIRALCUT_AUTOCLOSE")
        if auto_close:
            threading.Timer(float(auto_close), window.destroy).start()
        webview.start()
        shutdown()
        time.sleep(0.3)
        clean_exit = True
    except Exception:
        print(traceback.format_exc(), flush=True)
        raise
    finally:
        shutdown()
        if clean_exit and getattr(sys, "frozen", False):
            # pywebview/WebKit на macOS иногда падает уже после закрытия окна;
            # аккуратно завершаем процесс, не давая системе показать «ошибку».
            try:
                log.flush()
            except Exception:
                pass
            os._exit(0)


if __name__ == "__main__":
    main()
