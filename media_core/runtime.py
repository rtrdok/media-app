"""Заглушка runtime (в боте хранил Telegram Application)."""

application = None


def set_application(_app) -> None:
    global application
    application = _app
