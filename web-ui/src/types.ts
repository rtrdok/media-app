export type PageId =
  | "home"
  | "downloads"
  | "library"
  | "music"
  | "anime"
  | "settings"

export type HistoryItem = {
  id: number
  url: string
  title: string
  platform: string
  platform_name: string
  duration: string
  format: string
  quality: string
  dest: string
  thumb: string
  status: string
  favorite: boolean
  tags: string[]
}

export type QueueItem = {
  id: number
  url: string
  kind: string
  title: string
  status: string
  error?: string
  progress?: {
    stage?: string
    percent?: string
    speed?: string
    eta?: string
    indeterminate?: boolean
  } | null
}

export type RepeatMode = "off" | "one" | "all"

export type AppSettings = {
  download_dir: string
  theme: string
  accent?: string
  rate_limit: string
  subtitles: string
  minimize_to_tray: boolean
  notify_on_done: boolean
  desktop_shortcut: boolean
  autostart: boolean
  update_check_url: string
  cache_max_days: number
  use_cookies: boolean
  ui_lang: string
  check_disk_space?: boolean
  max_concurrent_downloads?: number
  use_proxy?: boolean
  proxy_list?: string
  onboarding_done?: boolean
  folders_by_service?: boolean
  discord_rpc?: boolean
  discord_client_id?: string
}

export type AppState = {
  busy: boolean
  paused: boolean
  running_count?: number
  max_concurrent?: number
  progress: {
    stage: string
    percent: string
    speed: string
    eta: string
    indeterminate: boolean
  }
  last: {
    error: string
    message: string
    notify_pending?: boolean
    shazam?: ShazamResult | null
  }
  download_dir: string
  settings: AppSettings
  version: string
  history: HistoryItem[]
  queue: QueueItem[]
  files?: { name: string; path: string }[]
  last_error?: string
  port?: number
  pc?: { user?: string; host?: string }
}

export type LibraryItem = {
  path: string
  title: string
  artist?: string
  source?: string
  duration?: string
  kind: "audio" | "video"
  cover?: string
}

export type ShazamResult = {
  track: string
  title?: string
  artist?: string
  preview?: string
  cover?: string
  links?: { name: string; url: string }[]
}

export type PreviewQuality = { value: string; label: string; size?: string }

export type PlayerTrack = {
  title: string
  artist: string
  src: string
  durationLabel?: string
  kind?: "audio" | "video"
  /** Локальный путь файла (для добавления в плейлисты). */
  path?: string
  /** Обложка / превью для панели плеера. */
  thumb?: string
  /** Страница трека (VK/Яндекс) — для fallback live → file. */
  pageUrl?: string
  /** Режим превью: live-прокси или локальный файл. */
  streamMode?: "live" | "file"
}

export type AnimeCandidate = {
  title?: string
  thumb?: string
  moment?: string
  episode?: number | null
  similarity?: number
  preview_url?: string
  video_url?: string
  anilist_url?: string
  shikimori_url?: string
  mal_url?: string
}
