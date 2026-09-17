"""Индекс аудиобиблиотеки: скан, теги, дубликаты, папки артистов."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
from pathlib import Path

from media_core.config import BASE_DIR
from media_core.database import (
    history_list,
    library_index_delete_missing,
    library_index_list,
    library_index_update_path,
    library_index_upsert,
)
from media_core.logging_setup import log
from media_core.settings_store import get_download_dir
from media_core.utils import fmt_time

AUDIO_EXT = {".mp3", ".m4a", ".flac", ".opus", ".wav", ".ogg", ".aac"}
VIDEO_EXT = {".mp4", ".webm", ".mkv", ".mov", ".avi", ".m4v"}
MEDIA_EXT = AUDIO_EXT | VIDEO_EXT
COVERS = BASE_DIR / "file_cache" / "covers"


def media_kind(path: str | Path) -> str:
    ext = Path(path).suffix.lower()
    if ext in VIDEO_EXT:
        return "video"
    return "audio"


def _safe_name(s: str) -> str:
    s = (s or "").strip() or "Unknown"
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    return s[:80] or "Unknown"


def _video_frame(path: Path) -> str:
    """Кадр из видео как обложка."""
    COVERS.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha1(str(path).encode("utf-8", errors="replace")).hexdigest()[:20] + ".jpg"
    dest = COVERS / name
    if dest.is_file() and dest.stat().st_size > 0:
        return str(dest)
    try:
        import subprocess

        import imageio_ffmpeg

        from media_core.utils import subprocess_no_window_kwargs

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                "00:00:02",
                "-i",
                str(path),
                "-frames:v",
                "1",
                "-q:v",
                "4",
                str(dest),
            ],
            check=False,
            capture_output=True,
            timeout=45,
            **subprocess_no_window_kwargs(),
        )
        if dest.is_file() and dest.stat().st_size > 0:
            return str(dest)
    except Exception as e:
        log.debug("video frame failed %s: %s", path, e)
    try:
        if dest.is_file() and dest.stat().st_size == 0:
            dest.unlink(missing_ok=True)
    except OSError:
        pass
    return ""


def _read_tags(path: Path) -> dict:
    title = path.stem
    artist = ""
    album = ""
    duration = 0.0
    cover_path = ""
    kind = media_kind(path)
    try:
        from mutagen import File as MutagenFile

        audio = MutagenFile(str(path), easy=True)
        if audio is not None:
            if getattr(audio, "info", None) and getattr(audio.info, "length", None):
                duration = float(audio.info.length or 0)
            tags = getattr(audio, "tags", None) or {}

            def _first(key: str) -> str:
                v = tags.get(key)
                if isinstance(v, list) and v:
                    return str(v[0]).strip()
                return str(v).strip() if v else ""

            title = _first("title") or title
            artist = _first("artist") or _first("albumartist") or ""
            album = _first("album") or ""
    except Exception as e:
        log.debug("library tags easy failed %s: %s", path, e)

    # cover extract (mp3 / flac / m4a / mp4 covr)
    try:
        cover_bytes = None
        mime = "image/jpeg"
        from mutagen import File as MutagenFile

        raw = MutagenFile(str(path))
        if raw is not None:
            tags = getattr(raw, "tags", None)
            if tags is not None:
                if hasattr(tags, "getall"):
                    apics = tags.getall("APIC")
                    if apics:
                        cover_bytes = apics[0].data
                        mime = getattr(apics[0], "mime", None) or mime
                elif "covr" in tags:  # MP4
                    covr = tags["covr"]
                    if covr:
                        cover_bytes = bytes(covr[0])
                elif hasattr(tags, "pictures") and tags.pictures:
                    cover_bytes = tags.pictures[0].data
                    mime = tags.pictures[0].mime or mime
        if cover_bytes:
            COVERS.mkdir(parents=True, exist_ok=True)
            ext = ".png" if "png" in (mime or "") else ".jpg"
            name = hashlib.sha1(str(path).encode("utf-8", errors="replace")).hexdigest()[:20] + ext
            dest = COVERS / name
            if not dest.is_file() or dest.stat().st_size != len(cover_bytes):
                dest.write_bytes(cover_bytes)
            cover_path = str(dest)
    except Exception as e:
        log.debug("library cover failed %s: %s", path, e)

    if kind == "video" and not cover_path:
        cover_path = _video_frame(path)
    if kind == "video" and not artist:
        artist = "Video"
    elif not artist:
        artist = "Unknown"

    return {
        "title": title,
        "artist": artist,
        "album": album,
        "duration": duration,
        "cover_path": cover_path,
        "kind": kind,
    }


def _candidate_paths(download_dir: str) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []

    def add(p: Path) -> None:
        try:
            key = str(p.resolve()).lower()
        except OSError:
            key = str(p).lower()
        if key in seen:
            return
        if not p.is_file():
            return
        if p.suffix.lower() not in MEDIA_EXT:
            return
        seen.add(key)
        out.append(p)

    root = Path(download_dir)
    if root.is_dir():
        for p in root.rglob("*"):
            if p.is_file():
                add(p)
    for item in history_list(limit=2000):
        dest = item.get("dest") or ""
        if dest:
            add(Path(dest))
    return out


def scan_library(force: bool = False) -> dict:
    download_dir = get_download_dir()
    existing = {r["path"]: r for r in library_index_list()}
    paths = _candidate_paths(download_dir)
    upsert: list[dict] = []
    keep: set[str] = set()

    for p in paths:
        try:
            st = p.stat()
        except OSError:
            continue
        path_s = str(p)
        keep.add(path_s)
        prev = existing.get(path_s)
        if (
            not force
            and prev
            and abs(float(prev.get("mtime") or 0) - st.st_mtime) < 0.5
            and int(prev.get("size") or 0) == int(st.st_size)
            and (prev.get("kind") in ("audio", "video"))
        ):
            continue
        meta = _read_tags(p)
        upsert.append(
            {
                "path": path_s,
                "mtime": st.st_mtime,
                "size": st.st_size,
                **meta,
            }
        )

    if upsert:
        library_index_upsert(upsert)
    library_index_delete_missing(keep)
    items = library_index_list()
    return {"ok": True, "count": len(items), "updated": len(upsert)}


def remove_library_item(path: str, *, delete_file: bool = True) -> dict:
    """Удалить файл из библиотеки (индекс + плейлисты) и опционально с диска."""
    import time

    from media_core.database import library_index_remove_path

    path_s = str(path or "").strip()
    if not path_s:
        return {"ok": False, "error": "Путь не указан"}

    p = Path(path_s)
    # нормализуем путь как в индексе
    try:
        p = p.resolve()
        path_s = str(p)
    except OSError:
        pass

    # This endpoint is intentionally limited to files the application has
    # already indexed as media.  Without this check any loopback API caller
    # could use the library action as an arbitrary-file delete primitive.
    indexed_paths = set()
    for row in library_index_list():
        candidate = str(row.get("path") or "")
        if not candidate:
            continue
        try:
            indexed_paths.add(str(Path(candidate).resolve()).lower())
        except OSError:
            indexed_paths.add(candidate.lower())
    if str(p).lower() not in indexed_paths or p.suffix.lower() not in MEDIA_EXT:
        return {"ok": False, "error": "Файл не входит в библиотеку"}

    deleted = False
    err = ""
    if delete_file and p.is_file():
        for attempt in range(5):
            try:
                p.unlink()
                deleted = True
                err = ""
                break
            except OSError as e:
                err = str(e)
                time.sleep(0.25 * (attempt + 1))
        if err:
            # Windows names the locking process only while the handle is live.
            # Ask Restart Manager before returning the error to the UI.
            try:
                from media_core.windows_locks import describe_file_lockers

                err += describe_file_lockers(p)
            except Exception:
                pass
            return {"ok": False, "removed_from_index": False, "file_deleted": False, "error": err}

    # A failed filesystem delete must not erase playlist membership. Only
    # remove database records once the file is gone (or for index-only removal).
    removed_db = library_index_remove_path(path_s)
    if not removed_db:
        alt = path_s.replace("/", "\\") if "/" in path_s else path_s.replace("\\", "/")
        if alt != path_s:
            removed_db = library_index_remove_path(alt) or removed_db

    ok = removed_db or deleted or (delete_file and not p.is_file())
    return {
        "ok": bool(ok),
        "removed_from_index": removed_db,
        "file_deleted": deleted,
        "error": err or None,
    }


def get_library(by: str = "flat", artist: str = "", kind: str = "all") -> dict:
    items = library_index_list()
    artist_f = (artist or "").strip().lower()
    kind_f = (kind or "all").strip().lower()
    if kind_f in ("audio", "video"):
        items = [i for i in items if (i.get("kind") or media_kind(i.get("path") or "")) == kind_f]
    if artist_f:
        items = [i for i in items if (i.get("artist") or "").lower() == artist_f]

    def enrich(i: dict) -> dict:
        cover = i.get("cover_path") or ""
        k = i.get("kind") or media_kind(i.get("path") or "")
        dur = i.get("duration")
        try:
            dur_sec = float(dur) if dur not in (None, "") else 0.0
        except (TypeError, ValueError):
            dur_sec = 0.0
            # already a formatted string like "3:05"
            if isinstance(dur, str) and ":" in dur:
                return {
                    **i,
                    "kind": k,
                    "cover": cover if cover and os.path.isfile(cover) else "",
                    "exists": os.path.isfile(i.get("path") or ""),
                    "duration": dur,
                }
        return {
            **i,
            "kind": k,
            "cover": cover if cover and os.path.isfile(cover) else "",
            "exists": os.path.isfile(i.get("path") or ""),
            "duration": fmt_time(dur_sec) if dur_sec else (str(dur) if isinstance(dur, str) and dur else ""),
            "duration_sec": dur_sec or None,
        }

    items = [enrich(i) for i in items if i.get("path")]
    by = (by or "flat").lower()
    if by == "artist":
        groups: dict[str, list] = {}
        for i in items:
            key = i.get("artist") or "Unknown"
            groups.setdefault(key, []).append(i)
        return {
            "ok": True,
            "by": "artist",
            "kind": kind_f,
            "groups": [{"name": k, "items": v} for k, v in sorted(groups.items(), key=lambda x: x[0].lower())],
            "artists": sorted({(i.get("artist") or "Unknown") for i in items}, key=str.lower),
            "count": len(items),
        }
    if by == "album":
        groups = {}
        for i in items:
            key = f"{i.get('artist') or 'Unknown'} — {i.get('album') or 'Unknown'}"
            groups.setdefault(key, []).append(i)
        return {
            "ok": True,
            "by": "album",
            "kind": kind_f,
            "groups": [{"name": k, "items": v} for k, v in sorted(groups.items(), key=lambda x: x[0].lower())],
            "artists": sorted({(i.get("artist") or "Unknown") for i in items}, key=str.lower),
            "count": len(items),
        }
    return {
        "ok": True,
        "by": "flat",
        "kind": kind_f,
        "items": items,
        "artists": sorted({(i.get("artist") or "Unknown") for i in items}, key=str.lower),
        "count": len(items),
    }


def find_duplicates() -> dict:
    items = [i for i in library_index_list() if os.path.isfile(i.get("path") or "")]
    buckets: dict[str, list] = {}
    for i in items:
        title = re.sub(r"\s+", " ", (i.get("title") or "").strip().lower())
        artist = re.sub(r"\s+", " ", (i.get("artist") or "").strip().lower())
        key = f"{artist}|{title}"
        if not title:
            # fallback: size + rounded duration
            key = f"size:{int(i.get('size') or 0)}|dur:{int(float(i.get('duration') or 0))}"
        buckets.setdefault(key, []).append(i)
    groups = []
    for key, lst in buckets.items():
        if len(lst) < 2:
            continue
        groups.append(
            {
                "key": key,
                "items": lst,
                "count": len(lst),
            }
        )
    groups.sort(key=lambda g: -g["count"])
    return {"ok": True, "groups": groups, "count": len(groups)}


def organize_by_artist(paths: list[str] | None = None) -> dict:
    download_dir = Path(get_download_dir())
    download_dir.mkdir(parents=True, exist_ok=True)
    index = {r["path"]: r for r in library_index_list()}
    targets = paths or list(index.keys())
    moved = []
    errors = []
    for path_s in targets:
        src = Path(path_s)
        # Only move records already present in the library index.  Besides
        # avoiding surprising moves, this keeps the API from accepting an
        # arbitrary source path supplied by a caller.
        try:
            canonical = str(src.resolve())
        except OSError:
            canonical = str(src)
        meta = index.get(path_s) or index.get(canonical)
        if meta is None:
            errors.append({"path": path_s, "error": "Файл не входит в библиотеку"})
            continue
        if not src.is_file():
            continue
        if src.suffix.lower() not in MEDIA_EXT:
            errors.append({"path": path_s, "error": "Неподдерживаемый тип файла"})
            continue
        artist = _safe_name(meta.get("artist") or "Unknown")
        dest_dir = download_dir / artist
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        if dest.resolve() == src.resolve():
            continue
        if dest.exists():
            stem, suf = dest.stem, dest.suffix
            n = 1
            while dest.exists():
                dest = dest_dir / f"{stem} ({n}){suf}"
                n += 1
        try:
            shutil.move(str(src), str(dest))
            library_index_update_path(path_s, str(dest), artist=artist, cover_path=meta.get("cover_path") or "")
            moved.append({"from": path_s, "to": str(dest)})
        except OSError as e:
            errors.append({"path": path_s, "error": str(e)})
    return {"ok": True, "moved": moved, "errors": errors, "count": len(moved)}
