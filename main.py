"""Точка входа: Python-ядро + HTML-окно."""

from __future__ import annotations

import asyncio
import os
import socket
import sys
import threading
import time
import traceback
from pathlib import Path

import urllib.request

if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent

os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if sys.stdout is None or not hasattr(sys.stdout, "isatty"):
    sys.stdout = open(ROOT / "media_app.log", "a", encoding="utf-8", errors="replace")
if sys.stderr is None or not hasattr(sys.stderr, "isatty"):
    sys.stderr = sys.stdout

from media_core.database import init_db
from media_core.logging_setup import log
from media_core.process_cleanup import arm_hard_exit, terminate_child_processes
from media_core.settings_store import get_bool, get_download_dir
from media_core.single_instance import (
    MUTEX_UNAVAILABLE,
    release_mutex,
    set_show_callback,
    try_acquire_mutex,
    wake_existing_instance,
    write_listen_port,
)
from media_core.utils import cleanup_temp_files
from web.server import (
    app,
    set_fullscreen_callback,
    set_listen_port,
    set_mini_player_callback,
    set_on_top_callback,
    set_quit_callback,
    set_show_window_callback,
    set_uvicorn_server,
)

HOST = "127.0.0.1"
PREFERRED_PORT = 17865
PORT = PREFERRED_PORT
_serve_error = ""
_window = None
_tray = None
_exit_requested = False
_mutex_handle = None
_mini_apply: dict = {"fn": None}
_mini_win_ref: dict = {"win": None}
_shutdown_lock = threading.Lock()
_shutdown_started = False
_uvicorn_server_ref: dict = {"server": None}


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((HOST, port))
            return True
        except OSError:
            return False


def _pick_port() -> int:
    if _port_free(PREFERRED_PORT):
        return PREFERRED_PORT
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((HOST, 0))
        return int(sock.getsockname()[1])


def _serve(port: int) -> None:
    global _serve_error
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
        import uvicorn

        config = uvicorn.Config(
            app,
            host=HOST,
            port=port,
            log_config=None,
            access_log=False,
            loop="asyncio",
        )
        server = uvicorn.Server(config)
        _uvicorn_server_ref["server"] = server
        set_uvicorn_server(server)
        server.run()
    except Exception:
        _serve_error = traceback.format_exc()
        log.exception("HTTP-сервер не запустился")


def _wait(port: int) -> None:
    url = f"http://{HOST}:{port}/"
    for _ in range(150):
        if _serve_error:
            raise RuntimeError(_serve_error)
        try:
            urllib.request.urlopen(url, timeout=0.4)
            return
        except Exception:
            time.sleep(0.1)
    raise RuntimeError(f"Не удалось запустить интерфейс: {_serve_error or 'таймаут'}")


def _ensure_ffmpeg() -> None:
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        folder = str(Path(exe).resolve().parent)
        os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")
        os.environ["FFMPEG_BINARY"] = exe
    except Exception:
        pass


def _make_tray_icon():
    from PIL import Image

    from media_core.config import BASE_DIR, RESOURCE_DIR

    for base in (RESOURCE_DIR, BASE_DIR, ROOT):
        for name in ("branding/app-64.png", "branding/app.png", "branding/app.ico"):
            path = base / name
            if path.is_file():
                try:
                    return Image.open(path).convert("RGBA")
                except Exception:
                    pass
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    from PIL import ImageDraw

    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, 61, 61), fill=(37, 99, 235, 255))
    return img


def _window_icon_path() -> str | None:
    from media_core.config import BASE_DIR, RESOURCE_DIR

    for base in (RESOURCE_DIR, BASE_DIR, ROOT):
        for name in ("branding/app.ico", "branding/app.png"):
            path = base / name
            if path.is_file():
                return str(path)
    return None


def _show_window() -> None:
    global _window
    if _window is None:
        return
    try:
        fn = _mini_apply.get("fn")
        if callable(fn):
            try:
                from media_core.player_bridge import is_mini_open

                if is_mini_open():
                    fn(False)
            except Exception:
                pass
        try:
            h = int(getattr(_window, "height", 0) or 0)
            w = int(getattr(_window, "width", 0) or 0)
            if h < 400 or w < 900:
                _window.resize(1180, 780)
        except Exception:
            pass
        try:
            _window.on_top = False
        except Exception:
            pass
        _window.show()
        _window.restore()
    except Exception:
        try:
            _window.show()
        except Exception:
            pass


def _stop_tray() -> None:
    global _tray
    try:
        if _tray is not None:
            _tray.stop()
    except Exception:
        pass
    _tray = None


def _destroy_mini() -> None:
    from media_core.player_bridge import set_mini_open

    set_mini_open(False)
    mw = _mini_win_ref.get("win")
    _mini_win_ref["win"] = None
    if mw is None:
        return
    try:
        mw.destroy()
        log.info("shutdown: mini destroyed")
    except Exception as e:
        log.warning("shutdown: mini destroy failed: %s", e)


def _stop_discord_rpc_agent() -> None:
    """Попросить elevated Discord RPC-агент завершиться (иначе exe залочен)."""
    try:
        import urllib.request

        req = urllib.request.Request(
            "http://127.0.0.1:17965/shutdown",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=1.5):
            pass
    except Exception:
        pass


def _shutdown_app(*, from_gui: bool = False) -> None:
    """Полный выход: mini → main → queue/uvicorn → дети → hard exit."""
    global _exit_requested, _shutdown_started, _mutex_handle, _window

    with _shutdown_lock:
        if _shutdown_started:
            return
        _shutdown_started = True
        _exit_requested = True

    log.info("shutdown: begin (from_gui=%s)", from_gui)
    _stop_tray()

    try:
        _stop_discord_rpc_agent()
    except Exception:
        pass

    try:
        from web.server import request_app_shutdown

        request_app_shutdown()
    except Exception:
        log.exception("shutdown: request_app_shutdown")

    _destroy_mini()

    win = _window
    if win is not None:
        try:
            win.destroy()
            log.info("shutdown: main destroyed")
        except Exception as e:
            log.warning("shutdown: main destroy failed: %s", e)
        _window = None

    try:
        cleanup_temp_files()
    except Exception:
        pass

    try:
        terminate_child_processes()
    except Exception:
        pass

    try:
        release_mutex(_mutex_handle)
    except Exception:
        pass
    _mutex_handle = None

    arm_hard_exit(2.5)
    log.info("shutdown: hard exit armed")


def _request_quit_from_tray() -> None:
    """Трей работает не в GUI-потоке — просим выход через JS API / HTTP."""
    global _exit_requested
    _exit_requested = True
    _stop_tray()

    def _emergency() -> None:
        if not _shutdown_started:
            log.warning("shutdown: emergency fallback from tray")
            _shutdown_app(from_gui=False)

    threading.Timer(5.0, _emergency).start()

    win = _window
    if win is not None:
        try:
            win.evaluate_js(
                "window.pywebview && window.pywebview.api && window.pywebview.api.quit_app()"
            )
            return
        except Exception as e:
            log.warning("shutdown: evaluate_js quit failed: %s", e)

    try:
        req = urllib.request.Request(
            f"http://{HOST}:{PORT}/api/window/quit",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=2.0)
        return
    except Exception as e:
        log.warning("shutdown: HTTP quit failed: %s", e)

    _shutdown_app(from_gui=False)


def _start_tray(window) -> None:
    global _tray
    try:
        import pystray
        from pystray import MenuItem as Item
    except ImportError:
        log.warning("pystray не установлен — трей отключён")
        return

    def show(icon=None, item=None):
        _show_window()

    def quit_app(icon=None, item=None):
        _request_quit_from_tray()

    menu = pystray.Menu(
        Item("Показать", show, default=True),
        Item("Выход", quit_app),
    )
    _tray = pystray.Icon("MediaApp", _make_tray_icon(), "Media App", menu)
    threading.Thread(target=_tray.run, daemon=True).start()


def _ensure_single_instance() -> bool:
    """True = можно продолжать запуск. False = уже есть экземпляр (разбудили его)."""
    global _mutex_handle
    _mutex_handle = try_acquire_mutex()
    if _mutex_handle is MUTEX_UNAVAILABLE:
        log.warning("Mutex недоступен — single-instance отключён")
        _mutex_handle = None
        return True
    if _mutex_handle is not None:
        return True
    if wake_existing_instance((PREFERRED_PORT, 8765, 18765)):
        log.info("Уже запущено — показываю существующее окно")
        return False
    log.warning("Другой экземпляр держит mutex, но не ответил на show")
    return False


def main() -> None:
    global PORT, _window, _exit_requested
    try:
        if not _ensure_single_instance():
            return

        _ensure_ffmpeg()
        init_db()
        Path(get_download_dir()).mkdir(parents=True, exist_ok=True)
        cleanup_temp_files()

        PORT = _pick_port()
        set_listen_port(PORT)
        write_listen_port(PORT)
        set_show_window_callback(_show_window)
        set_show_callback(_show_window)
        set_quit_callback(lambda: _shutdown_app(from_gui=False))

        _fs_active = {"on": False}

        def _set_fullscreen(enable: bool | None = None):
            win = _window
            if win is None:
                return
            want = (not _fs_active["on"]) if enable is None else bool(enable)
            if want == _fs_active["on"]:
                return
            try:
                win.toggle_fullscreen()
                _fs_active["on"] = want
            except Exception:
                log.exception("toggle_fullscreen failed")

        set_fullscreen_callback(_set_fullscreen)

        def _set_on_top(enable: bool):
            win = _window
            if win is None:
                return
            try:
                win.on_top = bool(enable)
            except Exception:
                log.exception("on_top failed")

        set_on_top_callback(_set_on_top)

        def _apply_mini_player(enable: bool) -> bool:
            from media_core.player_bridge import set_mini_open

            main = _window
            mini = _mini_win_ref.get("win")
            if main is None or mini is None:
                set_mini_open(False)
                return False
            try:
                if enable:
                    set_mini_open(True)
                    try:
                        import ctypes

                        user32 = ctypes.windll.user32
                        sw = int(user32.GetSystemMetrics(0))
                        sh = int(user32.GetSystemMetrics(1))
                        mini.move(max(0, sw - 640), max(0, sh - 120))
                    except Exception:
                        pass
                    mini.resize(620, 68)
                    mini.on_top = True
                    mini.show()
                    try:
                        main.hide()
                    except Exception:
                        pass
                else:
                    try:
                        mini.hide()
                    except Exception:
                        pass
                    set_mini_open(False)
                    try:
                        main.on_top = False
                    except Exception:
                        pass
                    try:
                        h = int(getattr(main, "height", 0) or 0)
                        w = int(getattr(main, "width", 0) or 0)
                        if h < 400 or w < 900:
                            main.resize(1180, 780)
                    except Exception:
                        pass
                    main.show()
                    try:
                        main.restore()
                    except Exception:
                        pass
                return True
            except Exception:
                log.exception("mini player failed")
                set_mini_open(False)
                try:
                    main.show()
                    main.restore()
                except Exception:
                    pass
                return False

        class GuiApi:
            def apply_mini_player(self, enable: bool):
                return {"ok": _apply_mini_player(bool(enable))}

            def hide_mini(self):
                return {"ok": _apply_mini_player(False)}

            def quit_app(self):
                """Вызывается с GUI-потока (из трея через evaluate_js)."""
                _shutdown_app(from_gui=True)
                return {"ok": True}

        def _set_mini_player(enable: bool):
            from media_core.player_bridge import set_mini_want

            set_mini_want(bool(enable))

        set_mini_player_callback(_set_mini_player)
        _mini_apply["fn"] = _apply_mini_player

        log.info("Media App (web UI) -> http://%s:%s  downloads=%s", HOST, PORT, get_download_dir())
        threading.Thread(target=_serve, args=(PORT,), daemon=True).start()
        _wait(PORT)

        import webview

        icon = _window_icon_path()
        gui_api = GuiApi()
        window = webview.create_window(
            "Media App",
            f"http://{HOST}:{PORT}/",
            width=1180,
            height=780,
            min_size=(1040, 680),
            background_color="#0B1020",
            frameless=False,
            easy_drag=False,
            js_api=gui_api,
        )
        _window = window

        mini = webview.create_window(
            "Media App",
            f"http://{HOST}:{PORT}/mini",
            width=620,
            height=68,
            on_top=True,
            frameless=True,
            easy_drag=True,
            background_color="#0f172a",
            resizable=False,
            hidden=True,
            js_api=gui_api,
        )
        _mini_win_ref["win"] = mini

        def on_mini_closing():
            from media_core.player_bridge import push_command, set_mini_open

            set_mini_open(False)
            try:
                push_command("close_mini")
            except Exception:
                pass
            try:
                mini.hide()
            except Exception:
                pass
            try:
                window.show()
                window.restore()
            except Exception:
                pass
            return False

        try:
            mini.events.closing += on_mini_closing
        except Exception:
            pass

        def on_closing():
            global _exit_requested
            if _exit_requested or _shutdown_started:
                return True
            if get_bool("minimize_to_tray", True) and _tray is not None:
                try:
                    window.hide()
                except Exception:
                    pass
                return False
            # крестик без трея — полный выход
            _exit_requested = True
            return True

        try:
            window.events.closing += on_closing
        except Exception:
            pass

        def on_closed():
            if not _shutdown_started:
                _shutdown_app(from_gui=True)

        try:
            window.events.closed += on_closed
        except Exception:
            pass

        def _after_start():
            if get_bool("minimize_to_tray", True):
                _start_tray(window)

        start_kwargs = {"func": _after_start, "debug": False}
        if icon:
            start_kwargs["icon"] = icon
        webview.start(**start_kwargs)

        # webview.start вернулся — добить процесс, если ещё жив
        if not _shutdown_started:
            _shutdown_app(from_gui=True)
        else:
            arm_hard_exit(1.0)
    except Exception:
        log.exception("Media App crashed")
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                0,
                "Media App завершился с ошибкой.\nПодробности в media_app.log рядом с программой.",
                "Media App",
                0x10,
            )
        except Exception:
            pass
        raise


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    if "--discord-rpc-agent" in sys.argv:
        # Elevated sidecar для Discord RPC (Discord от администратора)
        try:
            from media_core.discord_rpc_agent import run_agent

            run_agent()
        except Exception:
            log.exception("Discord RPC agent crashed")
            raise
    else:
        main()
