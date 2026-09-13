"""Алерты отключены в десктоп-приложении."""

from media_core.logging_setup import log


async def notify_admins(application, message: str, *, alert_key: str = "generic") -> None:
    log.warning("alert [%s]: %s", alert_key, message)
