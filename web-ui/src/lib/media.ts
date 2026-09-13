import { fileUrl } from "@/lib/api"
import type { HistoryItem, PlayerTrack } from "@/types"

const VIDEO_EXT = /\.(mp4|webm|mkv|mov|avi|m4v)(\?|$)/i

export function isVideoSrc(src: string): boolean {
  return VIDEO_EXT.test(src)
}

export function mediaKindFromPath(path: string): "audio" | "video" {
  return isVideoSrc(path) ? "video" : "audio"
}

export function playerTrackFromHistory(it: HistoryItem): PlayerTrack {
  return {
    title: it.title,
    artist: it.platform_name || it.platform,
    src: fileUrl(it.dest),
    durationLabel: it.duration,
    kind: mediaKindFromPath(it.dest),
    thumb: it.thumb || undefined,
  }
}

export function playerTrackFromLibrary(it: {
  title: string
  artist?: string
  path: string
  duration?: string
  kind?: string
  cover?: string
}): PlayerTrack {
  const kind = it.kind === "video" ? "video" : mediaKindFromPath(it.path)
  return {
    title: it.title,
    artist: it.artist || "",
    src: fileUrl(it.path),
    durationLabel: it.duration,
    kind,
    path: it.path,
    thumb: it.cover || undefined,
  }
}

/** Достаёт путь из /api/file?p=... если path не задан. */
export function filePathFromPlayerSrc(src: string): string {
  try {
    const u = new URL(src, "http://local")
    return u.searchParams.get("p") || ""
  } catch {
    return ""
  }
}
