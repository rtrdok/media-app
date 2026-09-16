import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react"
import { fetchHistory, fetchState } from "@/lib/api"
import type { AppState, AppSettings, HistoryItem, PageId, PlayerTrack, QueueItem, RepeatMode } from "@/types"

type QueueMeta = { index: number; length: number }

type LiveSlice = {
  busy: boolean
  paused: boolean
  progress: AppState["progress"]
  running_count?: number
  max_concurrent?: number
  last: AppState["last"]
  queue: QueueItem[]
  last_error: string
  version: string
  files?: { name: string; path: string }[]
}

type DataSlice = {
  history: HistoryItem[]
  settings: AppSettings
  download_dir: string
  pc?: { user?: string; host?: string }
  port?: number
}

type AppContextValue = {
  page: PageId
  setPage: (p: PageId) => void
  /** Совместимость: live + data в одном объекте */
  state: AppState | null
  refresh: (files?: boolean) => Promise<void>
  refreshHistory: () => Promise<void>
  player: PlayerTrack | null
  setPlayer: (t: PlayerTrack | null) => void
  playing: boolean
  setPlaying: (v: boolean | ((prev: boolean) => boolean)) => void
  playWithQueue: (tracks: PlayerTrack[], startIndex: number, opts?: { shuffle?: boolean }) => void
  playNextInQueue: () => boolean
  playPrevInQueue: () => boolean
  jumpToQueue: (index: number) => void
  removeFromQueue: (index: number) => void
  moveInQueue: (from: number, to: number) => void
  playQueue: PlayerTrack[]
  queueMeta: QueueMeta
  closePlayer: () => void
  shuffle: boolean
  setShuffle: (v: boolean | ((prev: boolean) => boolean)) => void
  repeat: RepeatMode
  setRepeat: (v: RepeatMode | ((prev: RepeatMode) => RepeatMode)) => void
  cycleRepeat: () => void
  miniPlayer: boolean
  setMiniPlayer: (v: boolean | ((prev: boolean) => boolean)) => void
  historySearchRef: React.RefObject<HTMLInputElement | null>
  focusHistorySearch: () => void
  globalSearchOpen: boolean
  openGlobalSearch: () => void
  closeGlobalSearch: () => void
  notifyDot: boolean
}

const AppContext = createContext<AppContextValue | null>(null)
const LiveContext = createContext<LiveSlice | null>(null)
const DataContext = createContext<DataSlice | null>(null)
const ActionsContext = createContext<Pick<
  AppContextValue,
  | "refresh"
  | "refreshHistory"
  | "playWithQueue"
  | "historySearchRef"
  | "setPage"
  | "page"
> | null>(null)

function pollDelayMs(page: PageId, busy: boolean, hasQueue: boolean): number {
  if (page === "settings") return 4000
  if (busy || hasQueue) return 500
  return 2200
}

function liveFingerprint(s: LiveSlice): string {
  const q = (s.queue || [])
    .map((x) => `${x.id}:${x.status}:${x.progress?.percent || ""}:${x.progress?.stage || ""}`)
    .join("|")
  const p = s.progress
  return [
    s.busy ? 1 : 0,
    s.paused ? 1 : 0,
    s.running_count || 0,
    p?.stage || "",
    p?.percent || "",
    p?.speed || "",
    p?.eta || "",
    p?.indeterminate ? 1 : 0,
    s.last?.message || "",
    s.last?.error || "",
    s.last?.notify_pending ? 1 : 0,
    s.last?.shazam?.track || "",
    s.last_error || "",
    q,
    (s.files || []).length,
  ].join("\n")
}

function shuffleArray<T>(arr: T[]): T[] {
  const a = [...arr]
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[a[i], a[j]] = [a[j], a[i]]
  }
  return a
}

function shuffleKeepingFirst(list: PlayerTrack[], startIndex: number): PlayerTrack[] {
  if (list.length <= 1) return [...list]
  const current = list[Math.min(Math.max(0, startIndex), list.length - 1)]
  const rest = list.filter((_, i) => i !== startIndex)
  return [current, ...shuffleArray(rest)]
}

const REPEAT_CYCLE: RepeatMode[] = ["off", "all", "one"]

const EMPTY_SETTINGS: AppSettings = {
  download_dir: "",
  theme: "dark",
  rate_limit: "",
  subtitles: "off",
  minimize_to_tray: true,
  notify_on_done: true,
  desktop_shortcut: false,
  autostart: false,
  update_check_url: "",
  cache_max_days: 7,
  use_cookies: false,
  ui_lang: "ru",
}

function liveFromState(s: AppState): LiveSlice {
  return {
    busy: !!s.busy,
    paused: !!s.paused,
    progress: s.progress,
    running_count: s.running_count,
    max_concurrent: s.max_concurrent,
    last: s.last,
    queue: s.queue || [],
    last_error: s.last_error || "",
    version: s.version || "",
    files: s.files,
  }
}

function dataFromState(s: AppState): DataSlice {
  return {
    history: s.history || [],
    settings: s.settings || EMPTY_SETTINGS,
    download_dir: s.download_dir || "",
    pc: s.pc,
    port: s.port,
  }
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [page, setPage] = useState<PageId>("home")
  const [live, setLive] = useState<LiveSlice | null>(null)
  const [data, setData] = useState<DataSlice | null>(null)
  const [player, setPlayer] = useState<PlayerTrack | null>(null)
  const [playing, setPlaying] = useState(false)
  const [playQueue, setPlayQueue] = useState<PlayerTrack[]>([])
  const [queueMeta, setQueueMeta] = useState<QueueMeta>({ index: 0, length: 0 })
  const [shuffle, setShuffleState] = useState(false)
  const [repeat, setRepeatState] = useState<RepeatMode>("off")
  const [miniPlayer, setMiniPlayerState] = useState(false)
  const [globalSearchOpen, setGlobalSearchOpen] = useState(false)
  const historySearchRef = useRef<HTMLInputElement | null>(null)
  const queueRef = useRef<PlayerTrack[]>([])
  const queueIndexRef = useRef(0)
  const shuffleRef = useRef(false)
  const repeatRef = useRef<RepeatMode>("off")
  const pageRef = useRef(page)
  const liveRef = useRef(live)
  const liveFpRef = useRef("")
  const wasBusyRef = useRef(false)
  pageRef.current = page
  liveRef.current = live
  shuffleRef.current = shuffle
  repeatRef.current = repeat

  const syncQueue = useCallback(() => {
    setPlayQueue([...queueRef.current])
    setQueueMeta({ index: queueIndexRef.current, length: queueRef.current.length })
  }, [])

  const applyLive = useCallback((next: LiveSlice) => {
    const fp = liveFingerprint(next)
    if (fp === liveFpRef.current) return false
    liveFpRef.current = fp
    setLive(next)
    return true
  }, [])

  const refreshHistory = useCallback(async () => {
    try {
      const j = await fetchHistory()
      if (j.ok) {
        setData((prev) =>
          prev
            ? { ...prev, history: j.history }
            : {
                history: j.history,
                settings: EMPTY_SETTINGS,
                download_dir: "",
              },
        )
      }
    } catch {
      /* ignore */
    }
  }, [])

  const refresh = useCallback(
    async (files = false) => {
      const s = await fetchState(files, false)
      applyLive(liveFromState(s))
      setData(dataFromState(s))
    },
    [applyLive],
  )

  const refreshLight = useCallback(
    async (files = false) => {
      const s = await fetchState(files, true)
      const next = liveFromState(s)
      if (files && s.files) next.files = s.files
      else if (liveRef.current?.files) next.files = liveRef.current.files
      applyLive(next)
      return next
    },
    [applyLive],
  )

  // Полная загрузка при смене страницы (настройки/история/файлы)
  useEffect(() => {
    void refresh(page === "downloads")
  }, [page, refresh])

  // Лёгкий poll: только очередь/прогресс
  useEffect(() => {
    let timer = 0
    let cancelled = false

    const tick = async () => {
      if (cancelled) return
      const p = pageRef.current
      if (p !== "settings") {
        const next = await refreshLight(p === "downloads")
        const busyNow = Boolean(next.busy)
        // После завершения загрузок — подтянуть историю один раз
        if (wasBusyRef.current && !busyNow && (p === "home" || p === "downloads" || p === "library")) {
          void refreshHistory()
        }
        wasBusyRef.current = busyNow
      }
      if (cancelled) return
      const cur = liveRef.current
      const hasQueue = Boolean(cur?.queue?.some((q) => q.status === "queued" || q.status === "running"))
      timer = window.setTimeout(
        tick,
        pollDelayMs(pageRef.current, Boolean(cur?.busy), hasQueue),
      )
    }

    timer = window.setTimeout(tick, 600)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [refreshLight, refreshHistory])

  useEffect(() => {
    const theme = data?.settings?.theme || "dark"
    let dark = theme !== "light"
    if (theme === "system") {
      dark = !window.matchMedia("(prefers-color-scheme: light)").matches
    }
    document.documentElement.classList.toggle("dark", dark)
    document.documentElement.classList.toggle("light", !dark)

    const accent = data?.settings?.accent || "blue"
    document.documentElement.dataset.accent = accent
  }, [data?.settings?.theme, data?.settings?.accent])

  const playWithQueue = useCallback(
    (tracks: PlayerTrack[], startIndex: number, opts?: { shuffle?: boolean }) => {
      const list = tracks.filter((t) => t.src)
      if (!list.length) return
      const wantShuffle = opts?.shuffle ?? shuffleRef.current
      if (opts?.shuffle != null) {
        setShuffleState(opts.shuffle)
        shuffleRef.current = opts.shuffle
      }
      let ordered = list
      let idx = Math.min(Math.max(0, startIndex), list.length - 1)
      if (wantShuffle) {
        ordered = shuffleKeepingFirst(list, idx)
        idx = 0
      }
      queueRef.current = ordered
      queueIndexRef.current = idx
      setPlayer(ordered[idx])
      setPlaying(true)
      syncQueue()
    },
    [syncQueue],
  )

  const playNextInQueue = useCallback(() => {
    const q = queueRef.current
    if (!q.length) return false
    const mode = repeatRef.current

    if (mode === "one") {
      const cur = q[queueIndexRef.current]
      if (cur) {
        setPlayer({ ...cur })
        setPlaying(true)
        syncQueue()
        return true
      }
    }

    const next = queueIndexRef.current + 1
    if (next < q.length) {
      queueIndexRef.current = next
      setPlayer(q[next])
      setPlaying(true)
      syncQueue()
      return true
    }

    if (mode === "all" && q.length) {
      if (shuffleRef.current && q.length > 1) {
        const reshuffled = shuffleArray(q)
        queueRef.current = reshuffled
        queueIndexRef.current = 0
        setPlayer(reshuffled[0])
      } else {
        queueIndexRef.current = 0
        setPlayer(q[0])
      }
      setPlaying(true)
      syncQueue()
      return true
    }
    return false
  }, [syncQueue])

  const playPrevInQueue = useCallback(() => {
    const q = queueRef.current
    const prev = queueIndexRef.current - 1
    if (prev < 0 || !q[prev]) return false
    queueIndexRef.current = prev
    setPlayer(q[prev])
    setPlaying(true)
    syncQueue()
    return true
  }, [syncQueue])

  const jumpToQueue = useCallback(
    (index: number) => {
      const q = queueRef.current
      if (!q[index]) return
      queueIndexRef.current = index
      setPlayer(q[index])
      setPlaying(true)
      syncQueue()
    },
    [syncQueue],
  )

  const removeFromQueue = useCallback(
    (index: number) => {
      const q = queueRef.current
      if (index < 0 || index >= q.length) return
      const wasCurrent = index === queueIndexRef.current
      let newIdx = queueIndexRef.current
      if (index < queueIndexRef.current) newIdx -= 1
      const next = q.filter((_, i) => i !== index)
      queueRef.current = next
      queueIndexRef.current = Math.max(0, Math.min(newIdx, Math.max(0, next.length - 1)))
      if (!next.length) {
        setPlayer(null)
        setPlaying(false)
      } else if (wasCurrent) {
        setPlayer(next[queueIndexRef.current])
        setPlaying(true)
      }
      syncQueue()
    },
    [syncQueue],
  )

  const moveInQueue = useCallback(
    (from: number, to: number) => {
      const q = [...queueRef.current]
      if (from < 0 || from >= q.length || to < 0 || to >= q.length || from === to) return
      const [item] = q.splice(from, 1)
      q.splice(to, 0, item)
      let idx = queueIndexRef.current
      if (idx === from) idx = to
      else if (from < idx && to >= idx) idx -= 1
      else if (from > idx && to <= idx) idx += 1
      queueRef.current = q
      queueIndexRef.current = idx
      syncQueue()
    },
    [syncQueue],
  )

  const setShuffle = useCallback(
    (v: boolean | ((prev: boolean) => boolean)) => {
      setShuffleState((prev) => {
        const next = typeof v === "function" ? v(prev) : v
        shuffleRef.current = next
        if (next && queueRef.current.length > 1) {
          const i = queueIndexRef.current
          const current = queueRef.current[i]
          const rest = queueRef.current.filter((_, idx) => idx !== i)
          queueRef.current = [current, ...shuffleArray(rest)]
          queueIndexRef.current = 0
          syncQueue()
        }
        return next
      })
    },
    [syncQueue],
  )

  const setRepeat = useCallback((v: RepeatMode | ((prev: RepeatMode) => RepeatMode)) => {
    setRepeatState((prev) => {
      const next = typeof v === "function" ? v(prev) : v
      repeatRef.current = next
      return next
    })
  }, [])

  const cycleRepeat = useCallback(() => {
    setRepeat((r) => {
      const i = REPEAT_CYCLE.indexOf(r)
      return REPEAT_CYCLE[(i + 1) % REPEAT_CYCLE.length]
    })
  }, [setRepeat])

  const setMiniPlayer = useCallback((v: boolean | ((prev: boolean) => boolean)) => {
    setMiniPlayerState(v)
  }, [])

  const closePlayer = useCallback(() => {
    setPlaying(false)
    setPlayer(null)
    queueRef.current = []
    queueIndexRef.current = 0
    syncQueue()
  }, [syncQueue])

  const focusHistorySearch = useCallback(() => {
    historySearchRef.current?.focus()
  }, [])

  const openGlobalSearch = useCallback(() => setGlobalSearchOpen(true), [])
  const closeGlobalSearch = useCallback(() => setGlobalSearchOpen(false), [])

  const notifyDot = Boolean(live?.last?.notify_pending)

  const state: AppState | null = useMemo(() => {
    if (!live && !data) return null
    return {
      busy: live?.busy ?? false,
      paused: live?.paused ?? false,
      progress: live?.progress ?? {
        stage: "",
        percent: "",
        speed: "",
        eta: "",
        indeterminate: false,
      },
      running_count: live?.running_count,
      max_concurrent: live?.max_concurrent,
      last: live?.last ?? { error: "", message: "" },
      download_dir: data?.download_dir ?? "",
      settings: data?.settings ?? EMPTY_SETTINGS,
      version: live?.version ?? "",
      history: data?.history ?? [],
      queue: live?.queue ?? [],
      files: live?.files,
      last_error: live?.last_error,
      pc: data?.pc,
      port: data?.port,
    }
  }, [live, data])

  const value = useMemo<AppContextValue>(
    () => ({
      page,
      setPage,
      state,
      refresh,
      refreshHistory,
      player,
      setPlayer,
      playing,
      setPlaying,
      playWithQueue,
      playNextInQueue,
      playPrevInQueue,
      jumpToQueue,
      removeFromQueue,
      moveInQueue,
      playQueue,
      queueMeta,
      closePlayer,
      shuffle,
      setShuffle,
      repeat,
      setRepeat,
      cycleRepeat,
      miniPlayer,
      setMiniPlayer,
      historySearchRef,
      focusHistorySearch,
      globalSearchOpen,
      openGlobalSearch,
      closeGlobalSearch,
      notifyDot,
    }),
    [
      page,
      state,
      refresh,
      refreshHistory,
      player,
      playing,
      playWithQueue,
      playNextInQueue,
      playPrevInQueue,
      jumpToQueue,
      removeFromQueue,
      moveInQueue,
      playQueue,
      queueMeta,
      closePlayer,
      shuffle,
      setShuffle,
      repeat,
      setRepeat,
      cycleRepeat,
      miniPlayer,
      setMiniPlayer,
      focusHistorySearch,
      globalSearchOpen,
      openGlobalSearch,
      closeGlobalSearch,
      notifyDot,
    ],
  )

  const actionsValue = useMemo(
    () => ({
      refresh,
      refreshHistory,
      playWithQueue,
      historySearchRef,
      setPage,
      page,
    }),
    [refresh, refreshHistory, playWithQueue, page],
  )

  return (
    <LiveContext.Provider value={live}>
      <DataContext.Provider value={data}>
        <ActionsContext.Provider value={actionsValue}>
          <AppContext.Provider value={value}>{children}</AppContext.Provider>
        </ActionsContext.Provider>
      </DataContext.Provider>
    </LiveContext.Provider>
  )
}

export function useApp() {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error("useApp outside AppProvider")
  return ctx
}

/** Только очередь/прогресс — меньше лишних ререндеров на тяжёлых страницах. */
export function useLiveState() {
  return useContext(LiveContext)
}

export function useAppData() {
  return useContext(DataContext)
}

/** Действия без подписки на progress tick. */
export function useAppActions() {
  const ctx = useContext(ActionsContext)
  if (!ctx) throw new Error("useAppActions outside AppProvider")
  return ctx
}
