"""Локальная SQLite: кэш, история, Shazam, библиотека."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time

from media_core.config import DB_FILE, HISTORY_LIMIT, PROXY_LIST


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_file: str | None = None) -> None:
    """Initialize/migrate the active database, or an isolated backup candidate."""
    conn = _connect() if db_file is None else sqlite3.connect(db_file)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS file_cache (
                cache_key TEXT PRIMARY KEY,
                url TEXT,
                file_path TEXT,
                size INTEGER,
                created_at REAL,
                last_used REAL
            );
            CREATE TABLE IF NOT EXISTS probe_cache (
                url TEXT PRIMARY KEY,
                created_at REAL,
                payload TEXT
            );
            CREATE TABLE IF NOT EXISTS recognized_cache (
                url TEXT PRIMARY KEY,
                track TEXT,
                created_at REAL
            );
            CREATE TABLE IF NOT EXISTS history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                title TEXT,
                platform TEXT,
                created_at REAL,
                duration TEXT,
                format TEXT,
                quality TEXT,
                dest TEXT,
                thumb TEXT,
                status TEXT,
                favorite INTEGER DEFAULT 0,
                tags TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS library_index (
                path TEXT PRIMARY KEY,
                mtime REAL,
                size INTEGER,
                title TEXT,
                artist TEXT,
                album TEXT,
                duration REAL,
                cover_path TEXT,
                updated_at REAL,
                kind TEXT DEFAULT 'audio'
            );
            CREATE TABLE IF NOT EXISTS library_playlists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at REAL,
                updated_at REAL
            );
            CREATE TABLE IF NOT EXISTS library_playlist_items (
                playlist_id INTEGER NOT NULL,
                path TEXT NOT NULL,
                position INTEGER NOT NULL DEFAULT 0,
                added_at REAL,
                PRIMARY KEY (playlist_id, path),
                FOREIGN KEY (playlist_id) REFERENCES library_playlists(id) ON DELETE CASCADE
            );
            """
        )
        cols = {r[1] for r in conn.execute("PRAGMA table_info(history)").fetchall()}
        for name, decl in (
            ("duration", "TEXT"),
            ("format", "TEXT"),
            ("quality", "TEXT"),
            ("dest", "TEXT"),
            ("thumb", "TEXT"),
            ("status", "TEXT"),
            ("favorite", "INTEGER DEFAULT 0"),
            ("tags", "TEXT DEFAULT ''"),
        ):
            if name not in cols:
                conn.execute(f"ALTER TABLE history ADD COLUMN {name} {decl}")
        lib_cols = {r[1] for r in conn.execute("PRAGMA table_info(library_index)").fetchall()}
        if "kind" not in lib_cols:
            conn.execute("ALTER TABLE library_index ADD COLUMN kind TEXT DEFAULT 'audio'")
        conn.commit()
    finally:
        conn.close()


init_db()


def mask_proxy(p: str) -> str:
    if not p:
        return "direct"
    if "@" not in p:
        return p
    scheme_and_creds, host_part = p.rsplit("@", 1)
    if "://" in scheme_and_creds:
        scheme, creds = scheme_and_creds.split("://", 1)
        if ":" in creds:
            user = creds.split(":", 1)[0]
            return f"{scheme}://{user}:****@{host_part}"
    return p


async def get_proxies_to_try(*, force_direct: bool = False) -> list[str | None]:
    """Список попыток: при включённом прокси сначала прокси (для РФ), затем direct.

    force_direct=True — только напрямую (VK / Яндекс и т.п.).
    """
    if force_direct:
        return [None]
    from media_core.settings_store import get_configured_proxies

    extra = get_configured_proxies()
    if not extra:
        return [None]
    return list(extra) + [None]


async def record_proxy_result(
    proxy: str | None,
    success: bool,
    latency_ms: float | None = None,
    error: str | None = None,
) -> bool:
    return False


async def probe_cache_get(url: str) -> tuple[float, str] | None:
    def _sync():
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT created_at, payload FROM probe_cache WHERE url = ?", (url,)
            ).fetchone()
            if not row:
                return None
            return float(row["created_at"]), row["payload"]
        finally:
            conn.close()

    return await asyncio.to_thread(_sync)


async def probe_cache_put(url: str, payload: str) -> None:
    def _sync():
        conn = _connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO probe_cache (url, created_at, payload) VALUES (?, ?, ?)",
                (url, time.time(), payload),
            )
            conn.commit()
        finally:
            conn.close()

    await asyncio.to_thread(_sync)


async def file_cache_get(key: str) -> tuple[str, float] | None:
    def _sync():
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT file_path, created_at FROM file_cache WHERE cache_key = ?", (key,)
            ).fetchone()
            if not row:
                return None
            return row["file_path"], float(row["created_at"])
        finally:
            conn.close()

    return await asyncio.to_thread(_sync)


async def file_cache_put(key: str, url: str, path: str, size: int) -> None:
    def _sync():
        now = time.time()
        conn = _connect()
        try:
            conn.execute(
                """INSERT OR REPLACE INTO file_cache
                   (cache_key, url, file_path, size, created_at, last_used)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (key, url, path, size, now, now),
            )
            conn.commit()
        finally:
            conn.close()

    await asyncio.to_thread(_sync)


async def file_cache_touch(key: str) -> None:
    def _sync():
        conn = _connect()
        try:
            conn.execute(
                "UPDATE file_cache SET last_used = ? WHERE cache_key = ?",
                (time.time(), key),
            )
            conn.commit()
        finally:
            conn.close()

    await asyncio.to_thread(_sync)


async def cache_get(url: str) -> str | None:
    def _sync():
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT track FROM recognized_cache WHERE url = ?", (url,)
            ).fetchone()
            return row["track"] if row else None
        finally:
            conn.close()

    return await asyncio.to_thread(_sync)


async def cache_set(url: str, track: str) -> None:
    def _sync():
        conn = _connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO recognized_cache (url, track, created_at) VALUES (?, ?, ?)",
                (url, track, time.time()),
            )
            conn.commit()
        finally:
            conn.close()

    await asyncio.to_thread(_sync)


def _normalize_tags(tags) -> str:
    if tags is None:
        return ""
    if isinstance(tags, str):
        parts = [t.strip() for t in tags.replace(";", ",").split(",") if t.strip()]
    elif isinstance(tags, (list, tuple)):
        parts = [str(t).strip() for t in tags if str(t).strip()]
    else:
        parts = []
    # unique preserve order
    seen = set()
    out = []
    for p in parts:
        key = p.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return json.dumps(out, ensure_ascii=False)


def _parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    raw = raw.strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [str(x) for x in data if str(x).strip()]
    except json.JSONDecodeError:
        pass
    return [t.strip() for t in raw.replace(";", ",").split(",") if t.strip()]


def history_add(
    url: str,
    title: str | None,
    platform: str | None,
    *,
    duration: str | None = None,
    format: str | None = None,
    quality: str | None = None,
    dest: str | None = None,
    thumb: str | None = None,
    status: str = "Готово",
) -> None:
    conn = _connect()
    try:
        prev = conn.execute(
            "SELECT favorite, tags FROM history WHERE url = ?", (url,)
        ).fetchone()
        fav = int(prev["favorite"] or 0) if prev else 0
        tags = prev["tags"] if prev and prev["tags"] is not None else "[]"
        conn.execute("DELETE FROM history WHERE url = ?", (url,))
        conn.execute(
            """INSERT INTO history
               (url, title, platform, created_at, duration, format, quality, dest, thumb, status, favorite, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                url,
                title,
                platform,
                time.time(),
                duration,
                format,
                quality,
                dest,
                thumb,
                status,
                fav,
                tags or "[]",
            ),
        )
        conn.execute(
            """DELETE FROM history WHERE id NOT IN (
                 SELECT id FROM history ORDER BY id DESC LIMIT ?
               )""",
            (HISTORY_LIMIT,),
        )
        conn.commit()
    finally:
        conn.close()


def history_list(limit: int | None = None) -> list[dict]:
    limit = limit or HISTORY_LIMIT
    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT id, url, title, platform, created_at, duration, format, quality,
                      dest, thumb, status, favorite, tags
               FROM history ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["favorite"] = bool(d.get("favorite"))
            d["tags"] = _parse_tags(d.get("tags"))
            out.append(d)
        return out
    finally:
        conn.close()


def history_search(
    *,
    q: str = "",
    favorite: bool | None = None,
    tag: str = "",
    limit: int | None = None,
) -> list[dict]:
    limit = limit or HISTORY_LIMIT
    q = (q or "").strip().lower()
    tag = (tag or "").strip().lower()
    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT id, url, title, platform, created_at, duration, format, quality,
                      dest, thumb, status, favorite, tags
               FROM history ORDER BY id DESC LIMIT ?""",
            (max(limit, HISTORY_LIMIT),),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["favorite"] = bool(d.get("favorite"))
            d["tags"] = _parse_tags(d.get("tags"))
            if favorite is True and not d["favorite"]:
                continue
            if favorite is False and d["favorite"]:
                continue
            if tag:
                if not any(t.lower() == tag for t in d["tags"]):
                    continue
            if q:
                blob = " ".join(
                    [
                        str(d.get("title") or ""),
                        str(d.get("url") or ""),
                        str(d.get("platform") or ""),
                        " ".join(d["tags"]),
                    ]
                ).lower()
                if q not in blob:
                    continue
            out.append(d)
            if len(out) >= limit:
                break
        return out
    finally:
        conn.close()


def history_get(item_id: int) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute(
            """SELECT id, url, title, platform, created_at, duration, format, quality,
                      dest, thumb, status, favorite, tags
               FROM history WHERE id = ?""",
            (item_id,),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["favorite"] = bool(d.get("favorite"))
        d["tags"] = _parse_tags(d.get("tags"))
        return d
    finally:
        conn.close()


def history_update(item_id: int, *, favorite: bool | None = None, tags=None) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute("SELECT id FROM history WHERE id = ?", (item_id,)).fetchone()
        if not row:
            return None
        if favorite is not None:
            conn.execute(
                "UPDATE history SET favorite = ? WHERE id = ?",
                (1 if favorite else 0, item_id),
            )
        if tags is not None:
            conn.execute(
                "UPDATE history SET tags = ? WHERE id = ?",
                (_normalize_tags(tags), item_id),
            )
        conn.commit()
    finally:
        conn.close()
    return history_get(item_id)


def history_delete(item_id: int) -> bool:
    conn = _connect()
    try:
        cur = conn.execute("DELETE FROM history WHERE id = ?", (item_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def history_clear() -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM history")
        conn.commit()
    finally:
        conn.close()


def history_prune_missing() -> None:
    """Убрать записи, чей файл уже удалён с диска."""
    import os

    conn = _connect()
    try:
        rows = conn.execute("SELECT id, dest FROM history").fetchall()
        gone = [r["id"] for r in rows if r["dest"] and not os.path.isfile(r["dest"])]
        if gone:
            conn.executemany("DELETE FROM history WHERE id = ?", [(i,) for i in gone])
            conn.commit()
    finally:
        conn.close()


def library_index_list() -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT path, mtime, size, title, artist, album, duration, cover_path, updated_at, kind
               FROM library_index ORDER BY artist COLLATE NOCASE, album COLLATE NOCASE, title COLLATE NOCASE"""
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            if not d.get("kind"):
                ext = (d.get("path") or "").rsplit(".", 1)
                suf = ("." + ext[-1].lower()) if len(ext) == 2 else ""
                d["kind"] = "video" if suf in {".mp4", ".webm", ".mkv", ".mov", ".avi", ".m4v"} else "audio"
            out.append(d)
        return out
    finally:
        conn.close()


def library_index_upsert(items: list[dict]) -> None:
    conn = _connect()
    try:
        now = time.time()
        for it in items:
            conn.execute(
                """INSERT OR REPLACE INTO library_index
                   (path, mtime, size, title, artist, album, duration, cover_path, updated_at, kind)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    it["path"],
                    float(it.get("mtime") or 0),
                    int(it.get("size") or 0),
                    it.get("title") or "",
                    it.get("artist") or "",
                    it.get("album") or "",
                    float(it.get("duration") or 0),
                    it.get("cover_path") or "",
                    now,
                    it.get("kind") or "audio",
                ),
            )
        conn.commit()
    finally:
        conn.close()


def library_index_delete_missing(keep_paths: set[str]) -> None:
    conn = _connect()
    try:
        rows = conn.execute("SELECT path FROM library_index").fetchall()
        gone = [r["path"] for r in rows if r["path"] not in keep_paths]
        if gone:
            conn.executemany("DELETE FROM library_index WHERE path = ?", [(p,) for p in gone])
            conn.commit()
    finally:
        conn.close()


def library_index_remove_path(path: str) -> bool:
    """Убрать путь из индекса и всех плейлистов (с учётом разных слэшей)."""
    path = str(path or "").strip()
    if not path:
        return False
    variants = {path, path.replace("/", "\\"), path.replace("\\", "/")}
    conn = _connect()
    try:
        removed = False
        for p in variants:
            conn.execute("DELETE FROM library_playlist_items WHERE path = ?", (p,))
            cur = conn.execute("DELETE FROM library_index WHERE path = ?", (p,))
            if cur.rowcount > 0:
                removed = True
        # также case-insensitive на Windows
        if not removed:
            low = path.lower().replace("/", "\\")
            rows = conn.execute("SELECT path FROM library_index").fetchall()
            for r in rows:
                rp = str(r["path"] or "")
                if rp.lower().replace("/", "\\") == low:
                    conn.execute("DELETE FROM library_playlist_items WHERE path = ?", (rp,))
                    conn.execute("DELETE FROM library_index WHERE path = ?", (rp,))
                    removed = True
        conn.commit()
        return removed
    finally:
        conn.close()


def library_index_update_path(old: str, new: str, *, artist: str = "", cover_path: str = "") -> None:
    conn = _connect()
    try:
        conn.execute(
            """UPDATE library_index SET path = ?, artist = COALESCE(NULLIF(?, ''), artist),
               cover_path = COALESCE(NULLIF(?, ''), cover_path), updated_at = ?
               WHERE path = ?""",
            (new, artist, cover_path, time.time(), old),
        )
        conn.execute(
            "UPDATE library_playlist_items SET path = ? WHERE path = ?",
            (new, old),
        )
        conn.commit()
    finally:
        conn.close()


def library_playlists_list() -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT p.id, p.name, p.created_at, p.updated_at,
                      COUNT(i.path) AS track_count
               FROM library_playlists p
               LEFT JOIN library_playlist_items i ON i.playlist_id = p.id
               GROUP BY p.id
               ORDER BY p.updated_at DESC, p.id DESC"""
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def library_playlist_create(name: str) -> dict:
    name = (name or "").strip() or "Новый плейлист"
    now = time.time()
    conn = _connect()
    try:
        cur = conn.execute(
            "INSERT INTO library_playlists (name, created_at, updated_at) VALUES (?, ?, ?)",
            (name, now, now),
        )
        conn.commit()
        return {"id": int(cur.lastrowid), "name": name, "created_at": now, "updated_at": now, "track_count": 0}
    finally:
        conn.close()


def library_playlist_rename(playlist_id: int, name: str) -> dict | None:
    name = (name or "").strip()
    if not name:
        return None
    conn = _connect()
    try:
        conn.execute(
            "UPDATE library_playlists SET name = ?, updated_at = ? WHERE id = ?",
            (name, time.time(), playlist_id),
        )
        conn.commit()
        row = conn.execute(
            """SELECT p.id, p.name, p.created_at, p.updated_at, COUNT(i.path) AS track_count
               FROM library_playlists p
               LEFT JOIN library_playlist_items i ON i.playlist_id = p.id
               WHERE p.id = ?
               GROUP BY p.id""",
            (playlist_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def library_playlist_delete(playlist_id: int) -> bool:
    conn = _connect()
    try:
        conn.execute("DELETE FROM library_playlist_items WHERE playlist_id = ?", (playlist_id,))
        cur = conn.execute("DELETE FROM library_playlists WHERE id = ?", (playlist_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def library_playlist_tracks(playlist_id: int) -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(
            """SELECT i.path, i.position, i.added_at,
                      l.title, l.artist, l.album, l.duration, l.cover_path, l.kind, l.mtime
               FROM library_playlist_items i
               LEFT JOIN library_index l ON l.path = i.path
               WHERE i.playlist_id = ?
               ORDER BY i.position ASC, i.added_at ASC""",
            (playlist_id,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            if not d.get("title"):
                d["title"] = (d.get("path") or "").rsplit("\\", 1)[-1].rsplit("/", 1)[-1] or "Трек"
            if not d.get("kind"):
                suf = ("." + (d.get("path") or "").rsplit(".", 1)[-1].lower()) if "." in (d.get("path") or "") else ""
                d["kind"] = "video" if suf in {".mp4", ".webm", ".mkv", ".mov", ".avi", ".m4v"} else "audio"
            out.append(d)
        return out
    finally:
        conn.close()


def library_playlist_add_tracks(playlist_id: int, paths: list[str]) -> dict:
    paths = [p.strip() for p in paths if p and str(p).strip()]
    if not paths:
        return {"ok": False, "added": 0, "error": "Нет путей"}
    conn = _connect()
    try:
        # Reserve the write transaction before reading MAX(position). Otherwise
        # simultaneous requests can both append at the same playlist position.
        conn.execute("BEGIN IMMEDIATE")
        exists = conn.execute("SELECT id FROM library_playlists WHERE id = ?", (playlist_id,)).fetchone()
        if not exists:
            return {"ok": False, "added": 0, "error": "Плейлист не найден"}
        row = conn.execute(
            "SELECT COALESCE(MAX(position), -1) AS m FROM library_playlist_items WHERE playlist_id = ?",
            (playlist_id,),
        ).fetchone()
        pos = int(row["m"] if row else -1) + 1
        added = 0
        now = time.time()
        for path in paths:
            before = conn.total_changes
            conn.execute(
                """INSERT OR IGNORE INTO library_playlist_items
                   (playlist_id, path, position, added_at) VALUES (?, ?, ?, ?)""",
                (playlist_id, path, pos, now),
            )
            if conn.total_changes > before:
                added += 1
                pos += 1
        conn.execute(
            "UPDATE library_playlists SET updated_at = ? WHERE id = ?",
            (now, playlist_id),
        )
        conn.commit()
        return {"ok": True, "added": added}
    finally:
        conn.close()


def library_playlist_remove_track(playlist_id: int, path: str) -> bool:
    conn = _connect()
    try:
        cur = conn.execute(
            "DELETE FROM library_playlist_items WHERE playlist_id = ? AND path = ?",
            (playlist_id, path),
        )
        conn.execute(
            "UPDATE library_playlists SET updated_at = ? WHERE id = ?",
            (time.time(), playlist_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
