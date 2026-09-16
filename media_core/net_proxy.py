"""Единый доступ к прокси для всех загрузчиков (не только yt-dlp).

Важно: системный VPN/прокси Windows НЕ меняем.
Если в настройках приложения прокси выключен — ходим напрямую и явно
игнорируем WinINET/HTTP_PROXY (иначе «VPN для Cursor» тормозит всё приложение).
"""

from __future__ import annotations


def configured_proxy_urls() -> list[str]:
    from media_core.settings_store import get_configured_proxies

    return get_configured_proxies()


def primary_proxy() -> str | None:
    """Первый настроенный прокси приложения или None (прямое соединение)."""
    urls = configured_proxy_urls()
    return urls[0] if urls else None


def requests_proxies(proxy: str | None = None) -> dict[str, str | None]:
    """Словарь proxies= для requests.

    Всегда явный словарь: если прокси приложения нет — None (не брать системный).
    """
    p = primary_proxy() if proxy is None else proxy
    if not p:
        return {"http": None, "https": None}
    return {"http": p, "https": p}


def httpx_proxy(proxy: str | None = None) -> str | None:
    """Аргумент proxy= для httpx.Client / AsyncClient."""
    return primary_proxy() if proxy is None else proxy


def httpx_client_kwargs(proxy: str | None = None, **extra) -> dict:
    """kwargs для httpx: trust_env=False, чтобы не подхватывать системный VPN."""
    kw = {"trust_env": False, "proxy": httpx_proxy(proxy), **extra}
    return kw


def apply_requests_kwargs(kwargs: dict) -> dict:
    """Добавить proxies + trust_env=False, если ещё нет."""
    out = dict(kwargs)
    if "proxies" not in out:
        out["proxies"] = requests_proxies()
    # не читать HTTP_PROXY / WinINET — VPN системы остаётся для других программ
    out.setdefault("trust_env", False)
    return out


def ytdlp_proxy_opt(proxy: str | None) -> str:
    """Значение proxy для yt-dlp: пустая строка = только напрямую (без системного)."""
    return proxy or ""
