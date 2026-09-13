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
import type { AppState, PageId, PlayerTrack } from "@/types"

type QueueMeta = { index: number; length: number }

type AppContextValue = {
  page: PageId
  setPage: (p: PageId) => void
  state: AppState | null
  refresh: (files?: boolean) => Promise<void>
  player: PlayerTrack | null
  setPlayer: (t: PlayerTrack | null) => void
  playing: boolean
  setPlaying: (v: boolean) => void
  playWithQueue: (tracks: PlayerTrack[], startIndex: number, opts?: { shuffle?: boolean }) => void
  playNextInQueue: () => boolean
  playPrevInQueue: () => boolean
  queueMeta: QueueMeta
  closePlayer: () => void
  shuffle: boolean
  setShuffle: (v: boolean | ((prev: boolean) => boolean)) => void
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

/** Перемешать так, чтобы текущий трек остался первым. */
function shuffleKeepingFirst(list: PlayerTrack[], startIndex: number): PlayerTrack[] {
  if (list.length <= 1) return [...list]
  const current = list[Math.min(Math.max(0, startIndex), list.length - 1)]
  const rest = list.filter((_, i) => i !== startIndex)
  return [current, ...shuffleArray(rest)]
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [page, setPage] = useState<PageId>("home")
  const [state, setState] = useState<AppState | null>(null)
  const [player, setPlayer] = useState<PlayerTrack | null>(null)
  const [playing, setPlaying] = useState(false)
  const [queueMeta, setQueueMeta] = useState<QueueMeta>({ index: 0, length: 0 })
  const [shuffle, setShuffleState] = useState(false)
  const historySearchRef = useRef<HTMLInputElement | null>(null)
  const queueRef = useRef<PlayerTrack[]>([])
  const queueIndexRef = useRef(0)
  const shuffleRef = useRef(false)
  const pageRef = useRef(page)
  const stateRef = useRef(state)
  pageRef.current = page
  stateRef.current = state
  shuffleRef.current = shuffle

  const syncQueueMeta = useCallback(() => {
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
  }, [state?.settings?.theme])

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
      syncQueueMeta()
    },
    [syncQueueMeta],
  )

  const playNextInQueue = useCallback(() => {
    const q = queueRef.current
    if (!q.length) return false
    const next = queueIndexRef.current + 1
    if (next < q.length) {
      queueIndexRef.current = next
      setPlayer(q[next])
      setPlaying(true)
      syncQueueMeta()
      return true
    }
    // Конец очереди: в режиме shuffle — новая перетасовка без повторов до полного круга
    if (shuffleRef.current && q.length > 1) {
      const current = q[queueIndexRef.current]
      const reshuffled = shuffleKeepingFirst(q, queueIndexRef.current)
      // если первый совпал со старым текущим — ок; иначе уже другой порядок
      queueRef.current = reshuffled.length && reshuffled[0].src === current.src
        ? reshuffled
        : [current, ...shuffleArray(q.filter((t) => t.src !== current.src))]
      queueIndexRef.current = 0
      // следующий после текущего в новом круге
      if (queueRef.current.length > 1) {
        queueIndexRef.current = 1
        setPlayer(queueRef.current[1])
        setPlaying(true)
        syncQueueMeta()
        return true
      }
    }
    return false
  }, [syncQueueMeta])

  const playPrevInQueue = useCallback(() => {
    const q = queueRef.current
    const prev = queueIndexRef.current - 1
    if (prev < 0 || !q.length) return false
    queueIndexRef.current = prev
    setPlayer(q[prev])
    setPlaying(true)
    syncQueueMeta()
    return true
  }, [syncQueueMeta])

  const setShuffle = useCallback(
    (v: boolean | ((prev: boolean) => boolean)) => {
      setShuffleState((prev) => {
        const next = typeof v === "function" ? v(prev) : v
        shuffleRef.current = next
        // При включении shuffle — перетасовать оставшиеся после текущего
        if (next && queueRef.current.length > 1) {
          const i = queueIndexRef.current
          const current = queueRef.current[i]
          const rest = queueRef.current.filter((_, idx) => idx !== i)
          queueRef.current = [current, ...shuffleArray(rest)]
          queueIndexRef.current = 0
          syncQueueMeta()
        }
        return next
      })
    },
    [syncQueueMeta],
  )

  const closePlayer = useCallback(() => {
    setPlaying(false)
    setPlayer(null)
    queueRef.current = []
    queueIndexRef.current = 0
    syncQueueMeta()
  }, [syncQueueMeta])

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
      queueMeta,
      closePlayer,
      shuffle,
      setShuffle,
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
      queueMeta,
      closePlayer,
      shuffle,
      setShuffle,
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
