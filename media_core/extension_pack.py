"""Сборка zip расширения Media App Cookies."""

from __future__ import annotations

import io
import secrets
import zipfile

from media_core.config import RESOURCE_DIR
from media_core.settings_store import get_all, update_settings

EXTENSION_DIR = RESOURCE_DIR / "extension"
BRIDGE_PORTS = [17865, 8765, 18765]


def ensure_extension_token() -> str:
    data = get_all()
    token = str(data.get("extension_token") or "").strip()
    if len(token) < 16:
        token = secrets.token_hex(16)
        update_settings(extension_token=token)
    return token


def build_extension_zip(port: int | None = None) -> bytes:
    """Zip с подставленным config.js (порт + токен)."""
    token = ensure_extension_token()
    ports = list(BRIDGE_PORTS)
    if port and port not in ports:
        ports.insert(0, int(port))
    elif port:
        ports = [int(port)] + [p for p in ports if p != int(port)]

    config = (
        "window.MEDIA_APP_BRIDGE = {\n"
        f"  ports: {ports},\n"
        f"  token: {token!r}\n"
        "};\n"
    )
    files = [
        "manifest.json",
        "background.js",
        "popup.html",
        "popup.js",
        "icon16.png",
        "icon48.png",
        "icon128.png",
    ]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name in files:
            path = EXTENSION_DIR / name
            if not path.is_file():
                continue
            zf.write(path, arcname=name)
        zf.writestr("config.js", config)
        zf.writestr(
            "INSTALL.txt",
            "Media App — расширение браузера\n"
            "================================\n\n"
            "Chrome / Edge / Brave:\n"
            "1) chrome://extensions  (или edge://extensions)\n"
            "2) Включи «Режим разработчика»\n"
            "3) «Загрузить распакованное расширение»\n"
            "4) Распакуй этот zip в папку и выбери её\n\n"
            "Firefox:\n"
            "1) about:debugging#/runtime/this-firefox\n"
            "2) «Загрузить временное дополнение»\n"
            "3) Выбери manifest.json из распакованной папки\n\n"
            "Как пользоваться:\n"
            "• «Отправить в Media App» — текущая вкладка сразу в очередь загрузок\n"
            "• ПКМ по ссылке / странице → «Отправить в Media App»\n"
            "• «Отправить cookies» — YouTube / Instagram / VK / Яндекс и др.\n"
            "Media App при этом должно быть запущено.\n",
        )
    return buf.getvalue()
