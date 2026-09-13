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
import { fetchState } from "@/lib/api"
import type { AppState, PageId, PlayerTrack, RepeatMode } from "@/types"

type QueueMeta = { index: number; length: number }

type AppContextValue = {
  page: PageId
  setPage: (p: PageId) => void
  state: AppState | null
  refresh: (files?: boolean) => Promise<void>
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
  notifyDot: boolean
}

const AppContext = createContext<AppContextValue | null>(null)

function pollDelayMs(page: PageId, state: AppState | null): number {
  if (page === "settings") return 2500
  const active =
    Boolean(state?.busy) ||
    Boolean(state?.queue?.some((q) => q.status === "queued" || q.status === "running"))
  return active ? 400 : 1600
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

export function AppProvider({ children }: { children: ReactNode }) {
  const [page, setPage] = useState<PageId>("home")
  const [state, setState] = useState<AppState | null>(null)
  const [player, setPlayer] = useState<PlayerTrack | null>(null)
  const [playing, setPlaying] = useState(false)
  const [playQueue, setPlayQueue] = useState<PlayerTrack[]>([])
  const [queueMeta, setQueueMeta] = useState<QueueMeta>({ index: 0, length: 0 })
  const [shuffle, setShuffleState] = useState(false)
  const [repeat, setRepeatState] = useState<RepeatMode>("off")
  const [miniPlayer, setMiniPlayerState] = useState(false)
  const historySearchRef = useRef<HTMLInputElement | null>(null)
  const queueRef = useRef<PlayerTrack[]>([])
  const queueIndexRef = useRef(0)
  const shuffleRef = useRef(false)
  const repeatRef = useRef<RepeatMode>("off")
  const pageRef = useRef(page)
  const stateRef = useRef(state)
  pageRef.current = page
  stateRef.current = state
  shuffleRef.current = shuffle
  repeatRef.current = repeat

  const syncQueue = useCallback(() => {
    setPlayQueue([...queueRef.current])
    setQueueMeta({ index: queueIndexRef.current, length: queueRef.current.length })
  }, [])

  const refresh = useCallback(async (files = false) => {
    const s = await fetchState(files)
    setState(s)
  }, [])

  useEffect(() => {
    void refresh(page === "downloads")
  }, [page, refresh])

  useEffect(() => {
    let timer = 0
    let cancelled = false

    const tick = async () => {
      if (cancelled) return
      const p = pageRef.current
      if (p !== "settings") {
        await refresh(p === "downloads")
      }
      if (cancelled) return
      timer = window.setTimeout(tick, pollDelayMs(pageRef.current, stateRef.current))
    }

    timer = window.setTimeout(tick, pollDelayMs(pageRef.current, stateRef.current))
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [refresh])

  useEffect(() => {
    const theme = state?.settings?.theme || "dark"
    let dark = theme !== "light"
    if (theme === "system") {
      dark = !window.matchMedia("(prefers-color-scheme: light)").matches
    }
    document.documentElement.classList.toggle("dark", dark)
    document.documentElement.classList.toggle("light", !dark)

    const accent = state?.settings?.accent || "blue"
    document.documentElement.dataset.accent = accent
  }, [state?.settings?.theme, state?.settings?.accent])

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

    if (shuffleRef.current && q.length > 1) {
      const current = q[queueIndexRef.current]
      const reshuffled = shuffleKeepingFirst(q, queueIndexRef.current)
      queueRef.current =
        reshuffled.length && reshuffled[0].src === current.src
          ? reshuffled
          : [current, ...shuffleArray(q.filter((t) => t.src !== current.src))]
      queueIndexRef.current = 0
      if (queueRef.current.length > 1) {
        queueIndexRef.current = 1
        setPlayer(queueRef.current[1])
        setPlaying(true)
        syncQueue()
        return true
      }
    }
    return false
  }, [syncQueue])

  const playPrevInQueue = useCallback(() => {
    const q = queueRef.current
    const prev = queueIndexRef.current - 1
    if (prev < 0 || !q.length) return false
    queueIndexRef.current = prev
    setPlayer(q[prev])
    setPlaying(true)
    syncQueue()
    return true
  }, [syncQueue])

  const jumpToQueue = useCallback(
    (index: number) => {
      const q = queueRef.current
      if (index < 0 || index >= q.length) return
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
      const next = q.filter((_, i) => i !== index)
      const wasCurrent = index === queueIndexRef.current
      let newIdx = queueIndexRef.current
      if (index < queueIndexRef.current) newIdx -= 1
      else if (wasCurrent) newIdx = Math.min(index, next.length - 1)
      queueRef.current = next
      queueIndexRef.current = Math.max(0, newIdx)
      if (!next.length) {
        setPlaying(false)
        setPlayer(null)
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
    setRepeat((prev) => {
      const i = REPEAT_CYCLE.indexOf(prev)
      return REPEAT_CYCLE[(i + 1) % REPEAT_CYCLE.length]
    })
  }, [setRepeat])

  const setMiniPlayer = useCallback((v: boolean | ((prev: boolean) => boolean)) => {
    setMiniPlayerState((prev) => (typeof v === "function" ? v(prev) : v))
  }, [])

  const closePlayer = useCallback(() => {
    setPlaying(false)
    setPlayer(null)
    setMiniPlayerState(false)
    queueRef.current = []
    queueIndexRef.current = 0
    syncQueue()
  }, [syncQueue])

  const focusHistorySearch = useCallback(() => {
    setPage("home")
    window.setTimeout(() => historySearchRef.current?.focus(), 50)
  }, [])

  const notifyDot = Boolean(state?.last?.notify_pending)

  const value = useMemo(
    () => ({
      page,
      setPage,
      state,
      refresh,
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
      notifyDot,
    }),
    [
      page,
      state,
      refresh,
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
      notifyDot,
    ],
  )

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

export function useApp() {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error("useApp outside AppProvider")
  return ctx
}
