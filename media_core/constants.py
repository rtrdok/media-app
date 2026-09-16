"""Общие константы."""

from __future__ import annotations

APP_VERSION = "1.5.3"

# owner/repo — публичный GitHub Releases для автообновления
GITHUB_REPO = "rtrdok/media-app"

CANCELLED = object()


class DownloadCancelled(Exception):
    """Отмена скачивания пользователем."""


URL_PATTERN = (
    r"https?://(?:www\.)?"
    r"(?:tiktok\.com|vm\.tiktok\.com|vt\.tiktok\.com|"
    r"instagram\.com|instagr\.am|youtube\.com|youtu\.be|twitch\.tv|"
    r"coub\.com|c-cdn\.coub\.com|"
    r"vk\.com|vkvideo\.ru|vk\.ru|vkontakte\.ru|"
    r"rutube\.ru|twitter\.com|x\.com|t\.co|"
    r"soundcloud\.com|on\.soundcloud\.com|"
    r"music\.yandex\.(?:ru|com|by|kz|uz))/\S+"
)

SUPPORTED_PLATFORMS_TEXT = (
    "TikTok / Instagram / YouTube / Coub / VK / RuTube / X / SoundCloud / Яндекс Музыка"
)

