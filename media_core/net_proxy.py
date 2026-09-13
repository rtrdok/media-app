"""Единый доступ к прокси для всех загрузчиков (не только yt-dlp)."""

from __future__ import annotations


def configured_proxy_urls() -> list[str]:
    from media_core.settings_store import get_configured_proxies

    return get_configured_proxies()


def primary_proxy() -> str | None:
    """Первый настроенный прокси или None (прямое соединение)."""
    urls = configured_proxy_urls()
    return urls[0] if urls else None


def requests_proxies(proxy: str | None = None) -> dict[str, str] | None:
    """Словарь proxies= для requests."""
    p = primary_proxy() if proxy is None else proxy
    if not p:
        return None
    return {"http": p, "https": p}


def httpx_proxy(proxy: str | None = None) -> str | None:
    """Аргумент proxy= для httpx.Client / AsyncClient."""
    return primary_proxy() if proxy is None else proxy


def apply_requests_kwargs(kwargs: dict) -> dict:
    """Добавить proxies в kwargs requests, если ещё нет."""
    if "proxies" not in kwargs:
        px = requests_proxies()
        if px:
            kwargs = {**kwargs, "proxies": px}
    return kwargs
