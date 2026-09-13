"""Конфигурация: .env, cookies, прокси, папка загрузок."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pyinstaller / minimal env

    def load_dotenv(*_args, **_kwargs) -> bool:
        return False


def _migrate_userdata(src: Path, dest: Path) -> None:
    """Один раз переносит настройки из папки exe в %APPDATA%\\MediaApp."""
    marker = dest / ".migrated_from_install"
    if marker.is_file():
        return
    names = (
        ".env",
        "cookies.txt",
        "vk_cookies.txt",
        "yandex_cookies.txt",
        "soundcloud_cookies.txt",
        "history.db",
        "config",
        "file_cache",
    )
    moved_any = False
    for name in names:
        s = src / name
        d = dest / name
        if not s.exists() or d.exists():
            continue
        try:
            if s.is_dir():
                shutil.copytree(s, d)
            else:
                shutil.copy2(s, d)
            moved_any = True
        except OSError:
            pass
    try:
        marker.write_text("1" if moved_any else "0", encoding="utf-8")
    except OSError:
        pass


def _dirs() -> tuple[Path, Path]:
    """resource = код и static; data = настройки/БД (%APPDATA% при exe)."""
    if getattr(sys, "frozen", False):
        resource = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        install = Path(sys.executable).resolve().parent
        roaming = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        data = roaming / "MediaApp"
        try:
            data.mkdir(parents=True, exist_ok=True)
            _migrate_userdata(install, data)
        except OSError:
            data = install
        return resource, data
    root = Path(__file__).resolve().parent.parent
    return root, root


RESOURCE_DIR, BASE_DIR = _dirs()
load_dotenv(BASE_DIR / ".env")


def _load_proxy_list() -> list[str]:
    raw = os.getenv("PROXY_LIST", "").strip()
    if raw:
        from media_core.settings_store import parse_proxy_lines

        return parse_proxy_lines(raw.replace("|", "\n"))

    proxy_file = os.getenv("PROXY_FILE", "").strip()
    if not proxy_file:
        return []

    path = BASE_DIR / proxy_file if not os.path.isabs(proxy_file) else Path(proxy_file)
    if not path.exists():
        return []

    from media_core.settings_store import parse_proxy_lines

    return parse_proxy_lines(path.read_text(encoding="utf-8"))


def _default_download_dir() -> Path:
    home = Path.home()
    downloads = home / "Downloads" / "MediaApp"
    return downloads


DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "").strip() or str(_default_download_dir())

HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "500"))

TRACE_MOE_URL = os.getenv("TRACE_MOE_URL", "https://api.trace.moe").rstrip("/")
TRACE_MOE_API_KEY = os.getenv("TRACE_MOE_API_KEY", "").strip()
TRACE_MOE_MIN_SIMILARITY = float(os.getenv("TRACE_MOE_MIN_SIMILARITY", "0.90"))
TRACE_MOE_REJECT_SIMILARITY = float(os.getenv("TRACE_MOE_REJECT_SIMILARITY", "0.72"))
TRACE_MOE_GUESS_MIN = float(os.getenv("TRACE_MOE_GUESS_MIN", "0.80"))
TRACE_MOE_MIN_GAP = float(os.getenv("TRACE_MOE_MIN_GAP", "0.04"))

PROGRESS_UPDATE_INTERVAL = 0.4

FILE_CACHE_DIR = str(BASE_DIR / "file_cache")
FILE_CACHE_TTL_SECONDS = int(os.getenv("FILE_CACHE_TTL_HOURS", "24")) * 3600

DB_FILE = str(BASE_DIR / os.getenv("DB_FILE", "history.db"))
LOG_FILE = str(BASE_DIR / os.getenv("LOG_FILE", "media_app.log"))
COOKIES_FILE = str(BASE_DIR / "cookies.txt")
YOUTUBE_USE_COOKIES = os.getenv("YOUTUBE_USE_COOKIES", "0").strip().lower() in ("1", "true", "yes")

VK_ACCESS_TOKEN = os.getenv("VK_ACCESS_TOKEN", "").strip()
VK_COOKIES = os.getenv("VK_COOKIES", "").strip()
VK_COOKIES_FILE = str(BASE_DIR / os.getenv("VK_COOKIES_FILE", "vk_cookies.txt"))
VK_API_VERSION = os.getenv("VK_API_VERSION", "5.199")

# Для запросов к сайту предпочитаем .vk.ru (сейчас основной домен VK).
_VK_COOKIE_HOST_PREF = (
    "m.vk.ru",
    ".vk.ru",
    "vk.ru",
    "login.vk.ru",
    ".login.vk.ru",
    "id.vk.ru",
    ".id.vk.ru",
    "m.vk.com",
    ".vk.com",
    "vk.com",
    "login.vk.com",
    ".login.vk.com",
)


def _is_vk_cookie_domain(domain: str) -> bool:
    d = (domain or "").lower().lstrip(".")
    return (
        d == "vk.com"
        or d.endswith(".vk.com")
        or d == "vk.ru"
        or d.endswith(".vk.ru")
        or d == "vk.me"
        or d.endswith(".vk.me")
        or d == "vkontakte.ru"
        or d.endswith(".vkontakte.ru")
        or d.startswith("login.vk")
        or d.startswith("id.vk")
    )


def _filter_netscape_vk(raw: str) -> str:
    lines = ["# Netscape HTTP Cookie File", "# vk filter from cookies.txt", ""]
    n = 0
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        cols = s.split("\t")
        if len(cols) < 7:
            continue
        if _is_vk_cookie_domain(cols[0] or ""):
            lines.append(s)
            n += 1
    if not n:
        return ""
    return "\n".join(lines) + "\n"


def _parse_netscape_cookie_rows(raw: str) -> list[tuple[str, str, str]]:
    """(domain, name, value) из Netscape или пусто."""
    rows: list[tuple[str, str, str]] = []
    for line in (raw or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        cols = s.split("\t")
        if len(cols) < 7 or not cols[5]:
            continue
        rows.append(((cols[0] or "").lower(), cols[5], cols[6]))
    return rows


def _domain_preference(domain: str, prefer_hosts: tuple[str, ...]) -> int:
    d = (domain or "").lower()
    d_bare = d.lstrip(".")
    for i, host in enumerate(prefer_hosts):
        h = host.lower()
        h_bare = h.lstrip(".")
        if d == h or d_bare == h_bare:
            return i
        if d.startswith(".") and (h_bare == d_bare or h_bare.endswith(d)):
            return i + 50
        if h.startswith(".") and (d_bare == h_bare or d_bare.endswith(h_bare)):
            return i + 50
    return 10_000


def _cookie_header_from_rows(
    rows: list[tuple[str, str, str]],
    prefer_hosts: tuple[str, ...] = _VK_COOKIE_HOST_PREF,
) -> str:
    """Один Cookie header без дублей имён (иначе VK игнорирует сессию)."""
    if not rows:
        return ""
    best: dict[str, tuple[int, str]] = {}
    for domain, name, value in rows:
        score = _domain_preference(domain, prefer_hosts)
        prev = best.get(name)
        if prev is None or score < prev[0]:
            best[name] = (score, value)
    # важные session-cookie первыми
    priority = ("remixsid", "remixnsid", "remixstid", "p", "httoken")
    names = list(best.keys())
    names.sort(key=lambda n: (0 if n in priority else 1, n))
    return "; ".join(f"{n}={best[n][1]}" for n in names)


def _netscape_or_header_to_cookie_header(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    first = next((ln.strip() for ln in raw.splitlines() if ln.strip() and not ln.strip().startswith("#")), "")
    if "Netscape HTTP Cookie File" in raw or (first and "\t" in first):
        return _cookie_header_from_rows(_parse_netscape_cookie_rows(raw))
    return first


def _vk_netscape_source() -> str:
    """Сырой Netscape с VK-cookie (для доменной сборки header)."""
    if VK_COOKIES_FILE and os.path.isfile(VK_COOKIES_FILE):
        raw = Path(VK_COOKIES_FILE).read_text(encoding="utf-8", errors="replace").strip()
        if raw and ("\t" in raw or "Netscape" in raw):
            return raw
    if COOKIES_FILE and os.path.isfile(COOKIES_FILE):
        raw = Path(COOKIES_FILE).read_text(encoding="utf-8", errors="replace").strip()
        if not raw:
            return ""
        filtered = _filter_netscape_vk(raw)
        if filtered:
            dest = BASE_DIR / "file_cache" / "vk_from_extension.txt"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(filtered, encoding="utf-8")
            return filtered
    return ""


def resolve_vk_cookies(*, prefer_hosts: tuple[str, ...] | None = None) -> str:
    """Cookie header для VK: env → vk_cookies.txt → общий cookies.txt из расширения."""
    hosts = prefer_hosts or _VK_COOKIE_HOST_PREF
    if VK_COOKIES:
        # уже готовый header — убрать дубли имён (оставить первое)
        seen: set[str] = set()
        parts: list[str] = []
        for part in VK_COOKIES.split(";"):
            part = part.strip()
            if not part or "=" not in part:
                continue
            name = part.split("=", 1)[0].strip()
            if name in seen:
                continue
            seen.add(name)
            parts.append(part)
        return "; ".join(parts)

    raw = _vk_netscape_source()
    if raw:
        rows = _parse_netscape_cookie_rows(raw)
        if rows:
            return _cookie_header_from_rows(rows, hosts)
        return _netscape_or_header_to_cookie_header(raw)

    path = VK_COOKIES_FILE
    if path and os.path.isfile(path):
        raw2 = Path(path).read_text(encoding="utf-8", errors="replace").strip()
        return _netscape_or_header_to_cookie_header(raw2)
    return ""


def load_vk_cookies() -> str:
    return resolve_vk_cookies()


def load_vk_cookies_for(*hosts: str) -> str:
    pref = tuple(hosts) + _VK_COOKIE_HOST_PREF if hosts else _VK_COOKIE_HOST_PREF
    return resolve_vk_cookies(prefer_hosts=pref)


def get_vk_netscape_path() -> str | None:
    """Путь к Netscape-файлу VK (для CookieJar по доменам)."""
    raw = _vk_netscape_source()
    if not raw:
        return None
    if "\t" not in raw and "Netscape" not in raw:
        return None
    dest = BASE_DIR / "file_cache" / "vk_jar.txt"
    dest.parent.mkdir(parents=True, exist_ok=True)
    text = raw if raw.endswith("\n") else raw + "\n"
    if not text.lstrip().startswith("#"):
        text = "# Netscape HTTP Cookie File\n" + text
    dest.write_text(text, encoding="utf-8")
    return str(dest)


def load_vk_cookie_jar():
    """MozillaCookieJar с VK cookies — httpx сам подставит нужные по домену."""
    from http.cookiejar import MozillaCookieJar

    path = get_vk_netscape_path()
    if not path:
        return None
    try:
        jar = MozillaCookieJar(path)
        jar.load(ignore_discard=True, ignore_expires=True)
        return jar if len(jar) else None
    except Exception:
        return None


def vk_cookies_configured() -> bool:
    return bool(VK_ACCESS_TOKEN or resolve_vk_cookies() or get_vk_netscape_path())


SOUNDCLOUD_COOKIES = os.getenv("SOUNDCLOUD_COOKIES", "").strip()
SOUNDCLOUD_COOKIES_FILE = str(BASE_DIR / os.getenv("SOUNDCLOUD_COOKIES_FILE", "soundcloud_cookies.txt"))


def resolve_soundcloud_cookies() -> tuple[str | None, str | None]:
    if SOUNDCLOUD_COOKIES:
        return SOUNDCLOUD_COOKIES, None
    path = SOUNDCLOUD_COOKIES_FILE
    if not os.path.isfile(path):
        return None, None
    raw = Path(path).read_text(encoding="utf-8").strip()
    if not raw:
        return None, None
    if "Netscape HTTP Cookie File" in raw:
        return None, path
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in line:
            return None, path
        return line, None
    return None, None


def soundcloud_cookies_configured() -> bool:
    header, cookiefile = resolve_soundcloud_cookies()
    return bool(header or cookiefile)


YANDEX_COOKIES = os.getenv("YANDEX_COOKIES", "").strip()
YANDEX_COOKIES_FILE = str(BASE_DIR / os.getenv("YANDEX_COOKIES_FILE", "yandex_cookies.txt"))


def resolve_yandex_cookies() -> tuple[str | None, str | None]:
    """Cookies для Яндекс Музыки: env → yandex_cookies.txt → общий cookies.txt из расширения."""
    if YANDEX_COOKIES:
        from media_core.cookie_netscape import cookie_header_to_tempfile
        return None, cookie_header_to_tempfile(YANDEX_COOKIES)

    candidates = [YANDEX_COOKIES_FILE, COOKIES_FILE]
    for path in candidates:
        if not path or not os.path.isfile(path):
            continue
        raw = Path(path).read_text(encoding="utf-8", errors="replace").strip()
        if not raw:
            continue
        # отдельный yandex_cookies.txt — берём целиком
        if os.path.abspath(path) == os.path.abspath(YANDEX_COOKIES_FILE):
            if "Netscape HTTP Cookie File" in raw or "\t" in (raw.splitlines()[0] if raw else ""):
                return None, path
            from media_core.cookie_netscape import cookie_header_to_tempfile
            return None, cookie_header_to_tempfile(raw)
        # общий cookies.txt — только домены Яндекса
        filtered = _filter_netscape_yandex(raw)
        if filtered:
            dest = BASE_DIR / "file_cache" / "yandex_from_extension.txt"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(filtered, encoding="utf-8")
            return None, str(dest)
    return None, None


def _filter_netscape_yandex(raw: str) -> str:
    lines = ["# Netscape HTTP Cookie File", "# yandex filter from cookies.txt", ""]
    n = 0
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        cols = s.split("\t")
        if len(cols) < 7:
            continue
        domain = (cols[0] or "").lower()
        if "yandex." in domain or domain.endswith(".yandex") or "passport.yandex" in domain:
            lines.append(s)
            n += 1
    if not n:
        return ""
    return "\n".join(lines) + "\n"


def yandex_music_configured() -> bool:
    header, cookiefile = resolve_yandex_cookies()
    return bool(header or cookiefile)


LONG_VIDEO_THRESHOLD = 600
DEFAULT_RECOGNIZE_CLIP_SECONDS = 60
QUALITY_HEIGHTS = [("360", 360), ("480", 480), ("720", 720), ("1080", 1080)]
YOUTUBE_CLIENT_FALLBACKS = ["android", "ios", "web_safari", "web_embedded", "mweb"]

PROXY_LIST: list[str] = _load_proxy_list()
PROBE_CACHE_TTL_SECONDS = int(os.getenv("PROBE_CACHE_TTL_MINUTES", "20")) * 60
LOG_MAX_BYTES = int(os.getenv("LOG_MAX_BYTES", str(5 * 1024 * 1024)))
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "5"))
TEMP_FILE_PREFIXES = ("tmp_", "audio_", "tiktok_", "tmp_cache_")
