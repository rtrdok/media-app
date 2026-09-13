"""Вспомогательные утилиты."""

from __future__ import annotations

import asyncio
import os
import re
from urllib.parse import parse_qs, quote, urlencode, urlparse, urlunparse

import requests

from pathlib import Path

from media_core.config import COOKIES_FILE, TEMP_FILE_PREFIXES
from media_core.logging_setup import log


def subprocess_no_window_kwargs() -> dict:
    """Windows: не показывать мигающее консольное окно при subprocess."""
    import sys
    import subprocess

    if sys.platform != "win32":
        return {}
    kwargs: dict = {}
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    else:
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        kwargs["startupinfo"] = si
    return kwargs


def open_path_in_shell(path: str | Path) -> None:
    """Открыть файл или папку в проводнике без консольного окна."""
    import sys
    import subprocess

    p = Path(path)
    if sys.platform == "win32":
        kw = subprocess_no_window_kwargs()
        if p.is_file():
            subprocess.run(["explorer.exe", "/select,", str(p.resolve())], check=False, **kw)
        else:
            p.mkdir(parents=True, exist_ok=True)
            subprocess.run(["explorer.exe", str(p.resolve())], check=False, **kw)
        return
    if p.is_file():
        os.startfile(str(p))
    else:
        p.mkdir(parents=True, exist_ok=True)
        os.startfile(str(p))


def clean_media_url(url: str) -> str:
    """Убрать плейлисты/радио YouTube и нормализовать VK/IG ссылки."""
    url = (url or "").strip()
    if not url:
        return url
    try:
        p = urlparse(url)
        host = (p.netloc or "").lower()
        qs = parse_qs(p.query)
        if "youtu.be" in host:
            vid = p.path.strip("/")
            return f"https://www.youtube.com/watch?v={vid}" if vid else url
        if "youtube.com" in host or "youtube-nocookie.com" in host:
            if p.path.startswith("/shorts/"):
                vid = p.path.strip("/").split("/")[-1]
                return f"https://www.youtube.com/watch?v={vid}" if vid else url
            if p.path.startswith("/embed/"):
                vid = p.path.strip("/").split("/")[-1]
                return f"https://www.youtube.com/watch?v={vid}" if vid else url
            vid = (qs.get("v") or [None])[0]
            if vid:
                return f"https://www.youtube.com/watch?v={vid}"
            keep = {k: v for k, v in qs.items() if k in ("v", "t", "start")}
            return urlunparse((p.scheme, p.netloc, p.path, "", urlencode(keep, doseq=True), ""))
        # VK clips / video
        if any(h in host for h in ("vk.com", "vk.ru", "vkvideo.ru", "vkontakte.ru")):
            path = p.path or ""
            # clip-123_456 or video-123_456
            m = re.search(r"/(clip|video)(-?\d+_\d+)", path, re.I)
            if m:
                kind, oid = m.group(1).lower(), m.group(2)
                domain = "vk.com" if "vkvideo" not in host else "vkvideo.ru"
                return f"https://{domain}/{kind}{oid}"
            if "z=" in (p.query or ""):
                z = (qs.get("z") or [""])[0]
                m = re.search(r"(clip|video)(-?\d+_\d+)", z, re.I)
                if m:
                    return f"https://vk.com/{m.group(1).lower()}{m.group(2)}"
        # Instagram stories keep as-is but strip tracking
        if "instagram.com" in host or "instagr.am" in host:
            keep = {k: v for k, v in qs.items() if k in ("igshid",)}
            # drop igshid noise
            return urlunparse((p.scheme, p.netloc, p.path.rstrip("/") + ("/" if p.path.endswith("/") else ""), "", "", ""))
    except Exception:
        return url
    return url


def is_instagram_stories_url(url: str) -> bool:
    u = (url or "").lower()
    return "instagram.com" in u and "/stories/" in u


def is_vk_clip_or_video_url(url: str) -> bool:
    u = (url or "").lower()
    if not any(x in u for x in ("vk.com", "vk.ru", "vkvideo.ru", "vkontakte.ru")):
        return False
    return bool(re.search(r"/(clip|video)|[?&]z=(clip|video)", u))


def detect_platform(url: str) -> str | None:
    url = url.lower()
    if any(x in url for x in ("tiktok.com", "vm.tiktok.com", "vt.tiktok.com")):
        return "tiktok"
    if any(x in url for x in ("instagram.com", "instagr.am")):
        return "instagram"
    if any(x in url for x in ("youtube.com", "youtu.be")):
        return "youtube"
    if "venchester.ru" in url or "/venbox/" in url:
        return "venbox"
    from media_core.direct_download import is_direct_file_url
    if is_direct_file_url(url):
        return "direct"
    if "twitch.tv" in url:
        return "twitch"
    if "coub.com" in url or "c-cdn.coub.com" in url:
        return "coub"
    if any(x in url for x in ("vk.com", "vkvideo.ru", "vk.ru", "vkontakte.ru")):
        return "vk"
    if "rutube.ru" in url:
        return "rutube"
    if any(x in url for x in ("twitter.com", "x.com", "t.co/")):
        return "x"
    if "soundcloud.com" in url:
        return "soundcloud"
    if _is_yandex_music_host(url) and "/track/" in url:
        return "yandex_music"
    return None


YANDEX_MUSIC_HOSTS = (
    "music.yandex.ru", "music.yandex.com", "music.yandex.by",
    "music.yandex.kz", "music.yandex.uz",
)


def _is_yandex_music_host(url: str) -> bool:
    u = url.lower()
    return any(h in u for h in YANDEX_MUSIC_HOSTS)


VK_AUDIO_ID_RE = re.compile(r"(?:^|[?&#/=])audio(-?\d+_\d+)", re.I)


def parse_vk_audio_id(url: str) -> str | None:
    m = VK_AUDIO_ID_RE.search(url)
    if m:
        return m.group(1)
    m = re.search(r"aid=(-?\d+_\d+)", url, re.I)
    return m.group(1) if m else None


def is_vk_audio_url(url: str) -> bool:
    return detect_platform(url) == "vk" and parse_vk_audio_id(url) is not None


def is_soundcloud_url(url: str) -> bool:
    return detect_platform(url) == "soundcloud"


def is_yandex_music_url(url: str) -> bool:
    return detect_platform(url) == "yandex_music"


def is_track_download_url(url: str) -> bool:
    return is_vk_audio_url(url) or is_soundcloud_url(url) or is_yandex_music_url(url)


def is_vault101_url(url: str) -> bool:
    return is_track_download_url(url)


def vk_audio_configured() -> bool:
    from media_core.config import VK_ACCESS_TOKEN, load_vk_cookies
    return bool(VK_ACCESS_TOKEN or load_vk_cookies())


def is_unsupported_media_url(url: str) -> bool:
    if is_vk_audio_url(url) or is_soundcloud_url(url) or is_yandex_music_url(url):
        return False
    u = url.lower()
    if "/wall" in u and any(x in u for x in ("vk.com", "vk.ru", "vkontakte.ru")):
        return True
    if any(x in u for x in ("vk.com", "vk.ru")) and "video" not in u and "clip" not in u:
        if "vkvideo.ru" not in u:
            return True
    return False


PLATFORM_NAMES = {
    "tiktok": "TikTok",
    "instagram": "Instagram",
    "youtube": "YouTube",
    "twitch": "Twitch",
    "coub": "Coub",
    "vk": "VK",
    "rutube": "RuTube",
    "x": "X",
    "soundcloud": "SoundCloud",
    "yandex_music": "Яндекс Музыка",
    "venbox": "VenBox",
    "direct": "Файл",
    "generic": "Другое",
}


def has_youtube_video_id(url: str) -> bool:
    u = url.lower()
    return any(x in u for x in ("watch?v=", "youtu.be/", "/shorts/", "/live/"))


def is_playlist_url(url: str) -> bool:
    u = url.lower().split("#", 1)[0]
    if "/playlist" in u:
        return True
    if "list=" in u and detect_platform(url) == "youtube" and not has_youtube_video_id(url):
        return True
    return False


def safe_filename(name: str, ext: str = ".mp3") -> str:
    cleaned = re.sub(r'[\\/*?:"<>|]', "", name).strip().strip(".")
    if not cleaned:
        cleaned = "track"
    if len(cleaned) > 120:
        cleaned = cleaned[:120].rstrip()
    if ext and not ext.startswith("."):
        ext = "." + ext
    if cleaned.lower().endswith(ext.lower()):
        return cleaned
    return cleaned + ext


def cache_display_filename(
    url: str,
    audio_only: bool,
    cached_path: str,
    *,
    track: str | None = None,
) -> str:
    ext = os.path.splitext(cached_path)[1] or (".mp3" if audio_only else ".mp4")
    if track:
        return safe_filename(track, ext)

    platform = detect_platform(url)
    if platform == "youtube":
        m = re.search(r"(?:[?&]v=|youtu\.be/|/shorts/|/live/)([\w-]{11})", url, re.I)
        if m:
            kind = "audio" if audio_only else "video"
            return f"youtube_{kind}_{m.group(1)}{ext}"

    labels = {
        "tiktok": "tiktok",
        "instagram": "instagram",
        "youtube": "youtube",
        "coub": "coub",
        "vk": "vk",
        "rutube": "rutube",
        "x": "x",
        "soundcloud": "soundcloud",
        "yandex_music": "yandex",
    }
    base = labels.get(platform or "", "media")
    kind = "audio" if audio_only else "video"
    return safe_filename(f"{base}_{kind}", ext)


def build_source_links(track_name: str) -> list[tuple[str, str]]:
    q = quote(track_name)
    return [
        ("Spotify", f"https://open.spotify.com/search/{q}"),
        ("SoundCloud", f"https://soundcloud.com/search?q={q}"),
        ("Яндекс Музыка", f"https://music.yandex.ru/search?text={q}"),
    ]


def fmt_time(seconds: float | int | None) -> str:
    if seconds is None:
        return "?"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def parse_time_to_seconds(text: str) -> int | None:
    text = text.strip()
    if not text:
        return None
    parts = text.split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    if len(nums) == 1:
        return nums[0]
    if len(nums) == 2:
        m, s = nums
        return m * 60 + s
    if len(nums) == 3:
        h, m, s = nums
        return h * 3600 + m * 60 + s
    return None


def cleanup_temp_files(cache_max_days: int | None = None) -> dict:
    """Удалить временные файлы в cwd и устаревший file_cache."""
    import time
    from media_core.config import BASE_DIR, FILE_CACHE_DIR

    removed = 0
    freed = 0
    for name in os.listdir("."):
        if not os.path.isfile(name):
            continue
        drop = False
        if name.startswith(TEMP_FILE_PREFIXES):
            drop = True
        elif name.startswith("media_") and (
            name.endswith(".part") or name.endswith(".ytdl") or ".part-Frag" in name
        ):
            drop = True
        elif name.startswith(("tmp_shazam_", "tmp_anime_", "tmp_cache_")):
            drop = True
        if drop:
            try:
                freed += os.path.getsize(name)
                os.remove(name)
                removed += 1
            except OSError as e:
                log.warning("Не удалось удалить %s: %s", name, e)

    if cache_max_days is None:
        try:
            from media_core.settings_store import get_cache_max_days
            cache_max_days = get_cache_max_days()
        except Exception:
            cache_max_days = 7
    cutoff = time.time() - max(1, int(cache_max_days)) * 86400
    cache_root = Path(FILE_CACHE_DIR)
    if cache_root.is_dir():
        for p in cache_root.rglob("*"):
            if not p.is_file():
                continue
            try:
                if p.stat().st_mtime < cutoff:
                    freed += p.stat().st_size
                    p.unlink()
                    removed += 1
            except OSError:
                pass

    if removed:
        log.info("Очистка: удалено %s файлов (~%.1f MB)", removed, freed / (1024 * 1024))
    return {"removed": removed, "freed_bytes": freed}


def write_bytes(filename: str, content: bytes) -> None:
    with open(filename, "wb") as f:
        f.write(content)


def cookies_path_exists() -> bool:
    return os.path.exists(COOKIES_FILE)


def youtube_cookies_active() -> bool:
    from media_core.config import YOUTUBE_USE_COOKIES
    try:
        from media_core.settings_store import use_cookies_enabled
        settings_on = use_cookies_enabled()
    except Exception:
        settings_on = False
    return (YOUTUBE_USE_COOKIES or settings_on) and cookies_path_exists()


def _requests_get_sync(url: str, **kwargs):
    from media_core.net_proxy import apply_requests_kwargs

    return requests.get(url, **apply_requests_kwargs(kwargs))


async def safe_get(url: str, **kwargs):
    return await asyncio.to_thread(_requests_get_sync, url, **kwargs)


def _create_slideshow_sync(images: list[str], audio_path: str | None, output_path: str) -> bool:
    try:
        from moviepy import AudioFileClip, ImageClip, concatenate_videoclips

        clips = [ImageClip(img).with_duration(2.5) for img in images]
        video = concatenate_videoclips(clips, method="compose")
        if audio_path and os.path.exists(audio_path):
            audio = AudioFileClip(audio_path)
            if audio.duration > video.duration:
                audio = audio.subclipped(0, video.duration)
            video = video.with_audio(audio)
        video.write_videofile(output_path, fps=24, codec="libx264", audio_codec="aac", logger=None)
        video.close()
        return True
    except Exception as e:
        log.error("Slideshow error: %s", e)
        return False


async def create_slideshow(images: list[str], audio_path: str | None, output_path: str) -> bool:
    return await asyncio.to_thread(_create_slideshow_sync, images, audio_path, output_path)


def _trim_audio_sync(path: str, start: float, duration: float) -> str | None:
    import subprocess

    out = f"tmp_clip_{os.path.basename(path)}"
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", path, "-ss", str(start), "-t", str(duration),
        "-c:a", "libmp3lame", "-q:a", "2", out,
    ]
    try:
        subprocess.run(
            cmd, check=True, capture_output=True, timeout=120, **subprocess_no_window_kwargs()
        )
        return out if os.path.isfile(out) else None
    except Exception as e:
        log.warning("trim_audio: %s", e)
        return None


async def trim_audio(path: str, start: float, duration: float) -> str | None:
    return await asyncio.to_thread(_trim_audio_sync, path, start, duration)


def _remux_coub_looped_sync(path: str) -> str:
    import subprocess

    if not path or not os.path.isfile(path):
        return path
    base, ext = os.path.splitext(path)
    out = f"{base}_coubloop{ext or '.mp4'}"
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-stream_loop", "-1", "-i", path,
        "-i", path,
        "-shortest", "-shortest_buf_duration", "0",
        "-map", "0:v:0", "-map", "1:a:0",
        "-c", "copy",
        out,
    ]
    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            timeout=300,
            text=True,
            **subprocess_no_window_kwargs(),
        )
        if not os.path.isfile(out) or os.path.getsize(out) < 1024:
            raise RuntimeError("coub remux output missing or too small")
        os.replace(out, path)
        log.info("coub remux: ok %s", os.path.basename(path))
        return path
    except subprocess.CalledProcessError as e:
        log.warning("coub remux: %s", (e.stderr or e.stdout or str(e)).strip())
    except Exception as e:
        log.warning("coub remux: %s", e)
        if os.path.isfile(out):
            try:
                os.remove(out)
            except OSError:
                pass
        return path
    return path


async def remux_coub_looped(path: str) -> str:
    return await asyncio.to_thread(_remux_coub_looped_sync, path)


def _ffmpeg_bin() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def _convert_media_sync(src: str, target: str) -> str:
    """Привести файл к контейнеру/кодеку: mp4, webm, mkv, mp3. Без смены — исходник."""
    import subprocess
    from pathlib import Path

    target = (target or "").lower().lstrip(".")
    if not target or not src or not os.path.isfile(src):
        return src
    src_ext = Path(src).suffix.lower().lstrip(".")
    if src_ext == target:
        return src

    ffmpeg = _ffmpeg_bin()
    out = str(Path(src).with_suffix("." + target))
    if target == "mp3":
        cmd = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", src, "-vn", "-c:a", "libmp3lame", "-q:a", "2", out,
        ]
    elif target == "mp4":
        # сначала попытка без перекодирования
        cmd_copy = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", src, "-c", "copy", "-movflags", "+faststart", out,
        ]
        try:
            subprocess.run(
                cmd_copy, check=True, capture_output=True, timeout=600, **subprocess_no_window_kwargs()
            )
            if os.path.isfile(out) and os.path.getsize(out) > 1024:
                if os.path.abspath(out) != os.path.abspath(src):
                    try:
                        os.remove(src)
                    except OSError:
                        pass
                return out
        except Exception:
            pass
        cmd = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", src,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart", out,
        ]
    elif target == "webm":
        cmd_copy = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", src, "-c", "copy", out,
        ]
        try:
            subprocess.run(
                cmd_copy, check=True, capture_output=True, timeout=600, **subprocess_no_window_kwargs()
            )
            if os.path.isfile(out) and os.path.getsize(out) > 1024:
                if os.path.abspath(out) != os.path.abspath(src):
                    try:
                        os.remove(src)
                    except OSError:
                        pass
                return out
        except Exception:
            pass
        cmd = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", src,
            "-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0",
            "-c:a", "libopus", "-b:a", "128k", out,
        ]
    elif target in ("mkv", "mov"):
        cmd_copy = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", src, "-c", "copy", out,
        ]
        try:
            subprocess.run(
                cmd_copy, check=True, capture_output=True, timeout=600, **subprocess_no_window_kwargs()
            )
            if os.path.isfile(out) and os.path.getsize(out) > 1024:
                if os.path.abspath(out) != os.path.abspath(src):
                    try:
                        os.remove(src)
                    except Exception:
                        pass
                return out
        except Exception:
            pass
        cmd = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", src,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k", out,
        ]
    elif target == "avi":
        cmd = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-i", src,
            "-c:v", "libxvid", "-qscale:v", "3",
            "-c:a", "libmp3lame", "-q:a", "4", out,
        ]
    else:
        return src

    try:
        subprocess.run(
            cmd, check=True, capture_output=True, timeout=1800, **subprocess_no_window_kwargs()
        )
        if os.path.isfile(out) and os.path.getsize(out) > 1024:
            if os.path.abspath(out) != os.path.abspath(src):
                try:
                    os.remove(src)
                except OSError:
                    pass
            return out
    except Exception as e:
        log.warning("convert %s->%s failed: %s", src_ext, target, e)
    return src


async def convert_media(path: str, target_format: str) -> str:
    return await asyncio.to_thread(_convert_media_sync, path, target_format)
