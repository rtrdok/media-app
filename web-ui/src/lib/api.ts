import type { AppSettings, AppState, HistoryItem } from "@/types"

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init)
  if (!r.ok) throw new Error(await r.text())
  return r.json() as Promise<T>
}

export function fetchState(files = false, light = false): Promise<AppState> {
  const q = new URLSearchParams()
  if (files) q.set("files", "1")
  if (light) q.set("light", "1")
  const qs = q.toString()
  return json(`/api/state${qs ? `?${qs}` : ""}`)
}

export function fetchHistory(params?: { q?: string; favorite?: boolean }) {
  const q = new URLSearchParams()
  if (params?.q) q.set("q", params.q)
  if (params?.favorite === true) q.set("favorite", "1")
  if (params?.favorite === false) q.set("favorite", "0")
  const qs = q.toString()
  return json<{ ok: boolean; history: HistoryItem[] }>(`/api/history${qs ? `?${qs}` : ""}`)
}

export function postJob(body: Record<string, unknown>) {
  return json<{ ok: boolean }>("/api/job", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
}

export function cancelJob() {
  return fetch("/api/cancel", { method: "POST" })
}

export function ackNotify() {
  return fetch("/api/notify/ack", { method: "POST" })
}

export function previewUrl(url: string) {
  return json<{
    ok: boolean
    error?: string
    platform?: string
    platform_name?: string
    title?: string
    thumb?: string
    duration?: string
    uploader?: string
    qualities?: { value: string; label: string }[]
  }>("/api/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  })
}

export function getClipboard() {
  return json<{ ok: boolean; text?: string }>("/api/clipboard")
}

export function patchHistory(id: number, body: { favorite?: boolean; tags?: string[] }) {
  return json<{ ok: boolean; item: HistoryItem }>(`/api/history/${id}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
}

export function deleteHistory(id: number) {
  return fetch(`/api/history/${id}`, { method: "DELETE" })
}

export function clearHistory() {
  return fetch("/api/history/clear", { method: "POST" })
}

export function saveSettings(body: Partial<AppSettings>) {
  return json<AppSettings>("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
}

export function queuePause() {
  return fetch("/api/queue/pause", { method: "POST" })
}

export function queueResume() {
  return fetch("/api/queue/resume", { method: "POST" })
}

export function queueClear() {
  return fetch("/api/queue/clear", { method: "POST" })
}

export function queueRetry(id: number) {
  return json<{ ok: boolean }>(`/api/queue/${id}/retry`, { method: "POST" })
}

export function openPath(path = "") {
  return fetch("/api/open", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  })
}

export function openUrl(url: string) {
  return fetch("/api/open_url", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  })
}

export function setWindowFullscreen(enable: boolean | null = null) {
  return fetch("/api/window/fullscreen", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enable }),
  })
}

export function setWindowOnTop(enable: boolean) {
  return fetch("/api/window/on_top", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enable }),
  })
}

export function setMiniPlayerWindow(enable: boolean) {
  return json<{ ok: boolean; enable?: boolean }>("/api/window/mini_player", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enable }),
  })
}

type PywebviewApi = {
  apply_mini_player?: (enable: boolean) => Promise<{ ok?: boolean } | boolean>
  hide_mini?: () => Promise<{ ok?: boolean } | boolean>
}

function pywebviewApi(): PywebviewApi | null {
  const w = window as Window & { pywebview?: { api?: PywebviewApi } }
  return w.pywebview?.api ?? null
}

function waitPywebview(ms = 2000): Promise<PywebviewApi | null> {
  const existing = pywebviewApi()
  if (existing) return Promise.resolve(existing)
  return new Promise((resolve) => {
    const done = () => resolve(pywebviewApi())
    const t = window.setTimeout(done, ms)
    window.addEventListener(
      "pywebviewready",
      () => {
        window.clearTimeout(t)
        done()
      },
      { once: true },
    )
  })
}

/** Открыть/закрыть мини-окно из GUI-потока (без зависания WinForms). */
export async function applyMiniPlayerWindow(enable: boolean): Promise<{ ok: boolean }> {
  const api = await waitPywebview()
  if (api?.apply_mini_player) {
    try {
      const r = await api.apply_mini_player(enable)
      const ok = typeof r === "boolean" ? r : Boolean(r && (r as { ok?: boolean }).ok !== false)
      void setMiniPlayerWindow(enable)
      return { ok }
    } catch {
      /* fall through */
    }
  }
  const res = await setMiniPlayerWindow(enable)
  return { ok: Boolean(res.ok) }
}

export function publishPlayerState(body: {
  title?: string
  artist?: string
  playing?: boolean
  current?: number
  duration?: number
  volume?: number
  has_track?: boolean
  thumb?: string
  kind?: "audio" | "video" | string
  position_revision?: number
}) {
  return fetch("/api/player/publish", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
}

export function fetchPlayerCommands() {
  return json<{ ok: boolean; commands?: { action: string; value?: number | null }[] }>(
    "/api/player/commands",
  )
}

export function fetchLyrics(title: string, artist = "", duration?: number) {
  return json<{
    ok: boolean
    lyrics?: string
    synced?: boolean
    error?: string
  }>("/api/lyrics", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, artist, duration }),
  })
}

export function fileUrl(path: string) {
  return `/api/file?p=${encodeURIComponent(path)}`
}

export function fetchLibrary(by = "flat", extra = "") {
  const qs = extra.replace(/^\&/, "")
  return json<{ ok: boolean; items: Record<string, unknown>[]; count?: number }>(
    `/api/library?by=${encodeURIComponent(by)}${qs ? `&${qs}` : ""}`,
  )
}

export function libraryRescan() {
  return fetch("/api/library/rescan", { method: "POST" })
}

export function libraryRemove(path: string, deleteFile = true) {
  return json<{ ok: boolean; file_deleted?: boolean; error?: string | null }>(
    "/api/library/remove",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path, delete_file: deleteFile }),
    },
  )
}

export type LibraryPlaylist = {
  id: number
  name: string
  track_count?: number
  created_at?: number
  updated_at?: number
}

export function libraryPlaylists() {
  return json<{ ok: boolean; items?: LibraryPlaylist[] }>("/api/library/playlists")
}

export function libraryPlaylistCreate(name: string) {
  return json<{ ok: boolean; playlist?: LibraryPlaylist; error?: string }>("/api/library/playlists", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  })
}

export function libraryPlaylistRename(id: number, name: string) {
  return json<{ ok: boolean; playlist?: LibraryPlaylist; error?: string }>(
    `/api/library/playlists/${id}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    },
  )
}

export function libraryPlaylistDelete(id: number) {
  return json<{ ok: boolean }>(`/api/library/playlists/${id}`, { method: "DELETE" })
}

export function libraryPlaylistDetail(id: number) {
  return json<{
    ok: boolean
    playlist?: LibraryPlaylist
    tracks?: Record<string, unknown>[]
    error?: string
  }>(`/api/library/playlists/${id}`)
}

export function libraryPlaylistAddTracks(id: number, paths: string[]) {
  return json<{ ok: boolean; added?: number; error?: string }>(
    `/api/library/playlists/${id}/tracks`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths }),
    },
  )
}

export function libraryPlaylistRemoveTrack(id: number, path: string) {
  return json<{ ok: boolean }>(
    `/api/library/playlists/${id}/tracks?path=${encodeURIComponent(path)}`,
    { method: "DELETE" },
  )
}

export function checkUpdate(quiet = false) {
  return json<{
    ok: boolean
    current?: string
    remote?: string
    update?: { version: string; url: string; changelog?: string } | null
    message?: string
    changelog?: string
    error?: string
  }>(`/api/app/check_update?quiet=${quiet ? 1 : 0}`, { method: "POST" })
}

export function applyUpdate(url?: string) {
  return json<{
    ok: boolean
    applied?: boolean
    restart?: boolean
    status?: string
    message?: string
    error?: string
  }>("/api/app/apply_update", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url: url || null }),
  })
}

export function updateStatus() {
  return json<{
    ok: boolean
    status?: string
    pct?: number
    bytes_done?: number
    bytes_total?: number
    speed_bps?: number
    message?: string
    error?: string
    restart?: boolean
  }>("/api/app/update_status")
}

export function cookiesStatus() {
  return json<{ ok: boolean; active: boolean; path?: string }>("/api/cookies/status")
}

export function extensionSave() {
  return json<{ ok: boolean; path?: string; folder?: string }>("/api/extension/save", {
    method: "POST",
  })
}

export function cookiesOpenFolder() {
  return fetch("/api/cookies/open", { method: "POST" })
}

export function backupExport() {
  window.location.href = "/api/backup/export"
}

export function backupImport(file: File) {
  const fd = new FormData()
  fd.append("file", file)
  return json<{ ok: boolean; error?: string }>("/api/backup/import", { method: "POST", body: fd })
}

export function uploadShazam(file: File) {
  const fd = new FormData()
  fd.append("file", file)
  return json<{ ok: boolean; title?: string; artist?: string; error?: string }>(
    "/api/shazam/file",
    { method: "POST", body: fd },
  )
}

export function uploadAnime(file: File) {
  const fd = new FormData()
  fd.append("file", file)
  return fetch("/api/anime", { method: "POST", body: fd })
}

export function playlistUrls(url: string) {
  return json<{
    ok: boolean
    title?: string
    entries?: { id?: string; title: string; url: string; duration?: number }[]
    count?: number
    error?: string
  }>("/api/playlist", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  })
}

export function libraryDuplicates() {
  return json<{
    ok: boolean
    groups?: { key: string; count: number; items: Record<string, unknown>[] }[]
    count?: number
  }>("/api/library/duplicates")
}

export function libraryOrganize(paths?: string[]) {
  return json<{ ok: boolean; moved?: unknown[]; count?: number; errors?: unknown[] }>(
    "/api/library/organize",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths: paths || null }),
    },
  )
}

export function ytdlpUpdate() {
  return json<{ ok: boolean; version?: string; log?: string }>("/api/ytdlp/update", {
    method: "POST",
  })
}

export type YandexPlaylist = {
  id: string
  kind: string
  uid: string
  title: string
  track_count?: number | null
  is_likes?: boolean
  access_hash?: string
}

export type YandexTrack = {
  id: string
  album_id?: string
  title: string
  artist: string
  album?: string
  label: string
  duration?: number | null
  duration_label?: string
  url: string
  cover?: string
}

export function yandexStatus() {
  return json<{ ok: boolean; configured?: boolean; login?: string; uid?: string; error?: string }>(
    "/api/yandex/status",
  )
}

export function yandexPlaylists() {
  return json<{ ok: boolean; items?: YandexPlaylist[]; error?: string }>("/api/yandex/playlists")
}

export function yandexPlaylistTracks(kind: string, uid = "") {
  const qs = new URLSearchParams({ kind })
  if (uid) qs.set("uid", uid)
  return json<{ ok: boolean; title?: string; tracks?: YandexTrack[]; count?: number; error?: string }>(
    `/api/yandex/playlist?${qs}`,
  )
}

export function yandexDownload(urls: string[]) {
  return json<{ ok: boolean; ids?: number[]; count?: number; error?: string }>("/api/yandex/download", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ urls }),
  })
}

export type VkPlaylist = YandexPlaylist
export type VkTrack = YandexTrack

export function vkStatus() {
  return json<{ ok: boolean; configured?: boolean; login?: string; uid?: string; error?: string }>("/api/vk/status")
}

export function vkPlaylists() {
  return json<{ ok: boolean; items?: VkPlaylist[]; error?: string }>("/api/vk/playlists")
}

export function vkPlaylistTracks(kind: string, uid = "", accessHash = "") {
  const qs = new URLSearchParams({ kind })
  if (uid) qs.set("uid", uid)
  if (accessHash) qs.set("access_hash", accessHash)
  return json<{ ok: boolean; title?: string; tracks?: VkTrack[]; count?: number; error?: string }>(
    `/api/vk/playlist?${qs}`,
  )
}

export function vkDownload(urls: string[]) {
  return json<{ ok: boolean; ids?: number[]; count?: number; error?: string }>("/api/vk/download", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ urls }),
  })
}

export function musicStreamUrl(pageUrl: string) {
  return `/api/music/stream?url=${encodeURIComponent(pageUrl)}`
}

/** Превью в плеер: quick — сразу live-стрим; file — полный локальный mp3. */
export function prepareMusicPreview(pageUrl: string, prefer: "quick" | "file" = "quick") {
  return json<{
    ok: boolean
    stream?: string
    title?: string
    artist?: string
    cover?: string
    label?: string
    mode?: "live" | "file" | string
    error?: string
  }>("/api/music/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url: pageUrl, prefer }),
  })
}
