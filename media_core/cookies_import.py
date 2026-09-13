"""Импорт cookies из браузера / файла в Netscape cookies.txt."""



from __future__ import annotations



import shutil

from pathlib import Path



from media_core.config import BASE_DIR, COOKIES_FILE

from media_core.logging_setup import log


def _clear_probe_cache() -> None:
    import asyncio

    from media_core.probe_cache import clear_probe_cache

    try:
        asyncio.run(clear_probe_cache())
    except Exception as e:
        log.debug("probe cache clear: %s", e)


def _enable_cookies_setting() -> None:

    try:

        from media_core.settings_store import update_settings

        update_settings(use_cookies=True)

    except Exception:

        pass

    try:
        from media_core.yandex_music_token import clear_yandex_token_cache

        clear_yandex_token_cache()
    except Exception:
        pass

    env_path = BASE_DIR / ".env"

    try:

        text = env_path.read_text(encoding="utf-8") if env_path.is_file() else ""

        if "YOUTUBE_USE_COOKIES" not in text:

            with env_path.open("a", encoding="utf-8") as f:

                f.write("\nYOUTUBE_USE_COOKIES=1\n")

        elif "YOUTUBE_USE_COOKIES=0" in text:

            env_path.write_text(

                text.replace("YOUTUBE_USE_COOKIES=0", "YOUTUBE_USE_COOKIES=1"),

                encoding="utf-8",

            )

    except OSError:

        pass

    _clear_probe_cache()


def _count_netscape(path: Path) -> int:

    if not path.is_file():

        return 0

    n = 0

    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():

        line = line.strip()

        if line and not line.startswith("#") and line.count("\t") >= 6:

            n += 1

    return n





def _friendly_decrypt_error(err: str) -> str:

    low = (err or "").lower()

    if "unable to get key" in low or "decrypt" in low or "app-bound" in low or "aes" in low:

        return (

            "Chrome шифрует cookies (новый ключ). Автоимпорт часто не работает.\n"

            "Сделай так:\n"

            "1) Расширение «Get cookies.txt LOCALLY» → экспорт youtube.com\n"

            "2) Настройки → «Загрузить cookies.txt»\n"

            "Или полностью закрой Chrome (трей → Выйти) и попробуй Edge."

        )

    return err





def import_browser_cookies(browser: str = "chrome") -> dict:

    browser = (browser or "chrome").strip().lower()

    if browser == "google":

        browser = "chrome"

    if browser not in ("chrome", "edge", "chromium", "firefox", "brave", "opera"):

        browser = "chrome"



    dest = Path(COOKIES_FILE)

    dest.parent.mkdir(parents=True, exist_ok=True)



    # Основной путь: API yt-dlp (лучше, чем browser-cookie3)

    try:

        from yt_dlp.cookies import YoutubeDLCookieJar, extract_cookies_from_browser



        jar = extract_cookies_from_browser(browser)

        if jar is None:

            raise RuntimeError("browser returned no cookie jar")

        # сохранить в Netscape

        if not isinstance(jar, YoutubeDLCookieJar):

            # иногда обычный MozillaCookieJar

            pass

        jar.save(filename=str(dest), ignore_discard=True, ignore_expires=True)

        count = _count_netscape(dest)

        if count > 0:

            _enable_cookies_setting()

            return {

                "ok": True,

                "count": count,

                "path": str(dest),

                "browser": browser,

                "via": "yt-dlp",

            }

        raise RuntimeError("cookie file empty after export")

    except Exception as e:

        log.warning("yt-dlp cookies extract (%s): %s", browser, e)

        ytdlp_err = str(e)



    # Fallback browser_cookie3 — на новом Chrome почти всегда падает с decrypt

    try:

        import browser_cookie3



        loaders = {

            "chrome": browser_cookie3.chrome,

            "edge": browser_cookie3.edge,

            "chromium": getattr(browser_cookie3, "chromium", browser_cookie3.chrome),

            "firefox": getattr(browser_cookie3, "firefox", None),

            "brave": getattr(browser_cookie3, "brave", None),

        }

        loader = loaders.get(browser)

        if loader:

            jar = loader(domain_name=".youtube.com")

            lines = ["# Netscape HTTP Cookie File", "# Media App", ""]

            n = 0

            for c in jar:

                domain = c.domain or ""

                include_sub = "TRUE" if domain.startswith(".") else "FALSE"

                lines.append(

                    f"{domain}\t{include_sub}\t{c.path or '/'}\t"

                    f"{'TRUE' if c.secure else 'FALSE'}\t{int(c.expires or 0)}\t"

                    f"{c.name}\t{c.value or ''}"

                )

                n += 1

            if n:

                dest.write_text("\n".join(lines) + "\n", encoding="utf-8")

                _enable_cookies_setting()

                return {"ok": True, "count": n, "path": str(dest), "browser": browser, "via": "browser_cookie3"}

    except Exception as e:

        log.warning("browser_cookie3 fallback: %s", e)

        ytdlp_err = f"{ytdlp_err}; {e}"



    return {

        "ok": False,

        "error": _friendly_decrypt_error(ytdlp_err),

        "browser": browser,

    }





def save_uploaded_cookies(raw: bytes, filename: str = "cookies.txt") -> dict:

    """Пользователь загрузил Netscape cookies.txt."""

    text = raw.decode("utf-8", errors="replace").strip()

    if not text or ("\t" not in text and "Netscape" not in text):

        return {

            "ok": False,

            "error": "Это не Netscape cookies.txt. Экспортируй через «Get cookies.txt LOCALLY».",

        }

    dest = Path(COOKIES_FILE)

    dest.write_text(text + ("\n" if not text.endswith("\n") else ""), encoding="utf-8")

    count = _count_netscape(dest)

    if count == 0:

        return {"ok": False, "error": "В файле нет cookie-строк."}

    _enable_cookies_setting()

    return {"ok": True, "count": count, "path": str(dest), "via": "upload", "filename": filename}





def cookies_status() -> dict:

    path = Path(COOKIES_FILE)

    return {

        "path": str(path),

        "exists": path.is_file(),

        "count": _count_netscape(path) if path.is_file() else 0,

    }


