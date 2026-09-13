import {
  ListMusic,
  Maximize,
  Mic2,
  Minimize,
  Pause,
  PictureInPicture2,
  Play,
  Repeat,
  Repeat1,
  Shuffle,
  SkipBack,
  SkipForward,
  Volume2,
  X,
} from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { AddToPlaylistsModal } from "@/components/library/AddToPlaylistsModal"
import { LyricsPanel } from "@/components/player/LyricsModal"
import { PlayerQueuePanel } from "@/components/player/PlayerQueuePanel"
import { useApp } from "@/context/AppProvider"
import {
  applyMiniPlayerWindow,
  fetchPlayerCommands,
  publishPlayerState,
  setWindowFullscreen,
} from "@/lib/api"
import { filePathFromPlayerSrc, isVideoSrc } from "@/lib/media"
import { cn } from "@/lib/utils"

/** Высота нижней видео-сцены (16:9) + панель в оконном режиме. */
export const VIDEO_PLAYER_DOCK_PAD = "pb-[min(calc(38vh+4.5rem),28rem)]"

export function PlayerBar({ showOnSettings = false }: { showOnSettings?: boolean }) {
  const {
    page,
    player,
    playing,
    setPlaying,
    closePlayer,
    playNextInQueue,
    playPrevInQueue,
    queueMeta,
    shuffle,
    setShuffle,
    repeat,
    cycleRepeat,
    miniPlayer,
    setMiniPlayer,
  } = useApp()
  const mediaRef = useRef<HTMLVideoElement | HTMLAudioElement | null>(null)
  const shellRef = useRef<HTMLDivElement | null>(null)
  const nativeFs = useRef(false)
  const [progress, setProgress] = useState(0)
  const [current, setCurrent] = useState("0:00")
  const [currentSec, setCurrentSec] = useState(0)
  const [durationSec, setDurationSec] = useState(0)
  const [total, setTotal] = useState(player?.durationLabel ?? "0:00")
  const [volume, setVolume] = useState(0.85)
  const [seeking, setSeeking] = useState(false)
  const [theater, setTheater] = useState(false)
  const [uiVisible, setUiVisible] = useState(true)
  const [addPlOpen, setAddPlOpen] = useState(false)
  const [queueOpen, setQueueOpen] = useState(false)
  const [lyricsOpen, setLyricsOpen] = useState(false)
  const hideTimer = useRef(0)
  const volumeRef = useRef(volume)
  volumeRef.current = volume
  const playingRef = useRef(playing)
  playingRef.current = playing

  const hidden = page === "settings" && !showOnSettings
  const hasSrc = Boolean(player?.src)
  const isVideo =
    player?.kind === "video" || (player?.src ? isVideoSrc(player.src) : false)
  const canPrev = queueMeta.length > 1 && queueMeta.index > 0
  const canNext =
    queueMeta.length > 1 &&
    (queueMeta.index < queueMeta.length - 1 || shuffle || repeat !== "off")

  async function applyFullscreen(on: boolean) {
    setTheater(on)
    if (nativeFs.current === on) return
    nativeFs.current = on
    try {
      await setWindowFullscreen(on)
    } catch {
      nativeFs.current = !on
      setTheater(!on)
    }
  }

  useEffect(() => {
    setTotal(player?.durationLabel ?? "0:00")
    setCurrent("0:00")
    setCurrentSec(0)
    setDurationSec(0)
    setProgress(0)
    void applyFullscreen(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [player?.src, player?.durationLabel])

  useEffect(() => {
    const el = mediaRef.current
    if (!el) return
    el.volume = volume
  }, [volume, player?.src])

  useEffect(() => {
    const el = mediaRef.current
    if (!el || !player?.src) return
    const onError = () => setPlaying(false)
    el.addEventListener("error", onError)
    el.load()
    return () => el.removeEventListener("error", onError)
  }, [player?.src, setPlaying])

  useEffect(() => {
    const el = mediaRef.current
    if (!el || !player?.src) return
    if (playing) void el.play().catch(() => setPlaying(false))
    else el.pause()
  }, [playing, player?.src, setPlaying])

  useEffect(() => {
    if (!hasSrc) void applyFullscreen(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasSrc])

  useEffect(() => {
    if (!theater) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") void applyFullscreen(false)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theater])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      const tag = t?.tagName
      if (tag === "INPUT" || tag === "TEXTAREA" || t?.isContentEditable) return
      if (e.code === "Space") {
        e.preventDefault()
        setPlaying((p) => !p)
      } else if (e.code === "ArrowRight" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault()
        playNextInQueue()
      } else if (e.code === "ArrowLeft" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault()
        playPrevInQueue()
      } else if (e.code === "ArrowUp") {
        e.preventDefault()
        setVolume((v) => Math.min(1, Math.round((v + 0.05) * 100) / 100))
      } else if (e.code === "ArrowDown") {
        e.preventDefault()
        setVolume((v) => Math.max(0, Math.round((v - 0.05) * 100) / 100))
      } else if (e.key.toLowerCase() === "l" && !e.ctrlKey && !e.metaKey) {
        setLyricsOpen((v) => !v)
      } else if (e.key.toLowerCase() === "q" && !e.ctrlKey && !e.metaKey) {
        setQueueOpen((v) => !v)
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [playNextInQueue, playPrevInQueue, setPlaying])

  useEffect(() => {
    if (!isVideo) {
      setUiVisible(true)
      return
    }
    const bump = () => {
      setUiVisible(true)
      window.clearTimeout(hideTimer.current)
      if (playing) {
        hideTimer.current = window.setTimeout(() => setUiVisible(false), 2600)
      }
    }
    bump()
    const el = shellRef.current
    if (!el) return
    el.addEventListener("mousemove", bump)
    el.addEventListener("mousedown", bump)
    return () => {
      window.clearTimeout(hideTimer.current)
      el.removeEventListener("mousemove", bump)
      el.removeEventListener("mousedown", bump)
    }
  }, [isVideo, playing, player?.src, theater])

  // Мост с отдельным мини-окном (главное скрыто, аудио здесь)
  useEffect(() => {
    if (!hasSrc || !miniPlayer) return
    const publish = () => {
      const el = mediaRef.current
      void publishPlayerState({
        title: player?.title || "",
        artist: player?.artist || "",
        playing: playingRef.current,
        current: el?.currentTime ?? 0,
        duration: el?.duration && Number.isFinite(el.duration) ? el.duration : 0,
        volume: volumeRef.current,
        has_track: true,
      })
    }
    publish()
    const id = window.setInterval(publish, 500)
    return () => window.clearInterval(id)
  }, [hasSrc, miniPlayer, player?.title, player?.artist, playing, volume])

  useEffect(() => {
    if (!hasSrc || !miniPlayer) return
    const id = window.setInterval(() => {
      void fetchPlayerCommands()
        .then((j) => {
          for (const c of j.commands || []) {
            if (c.action === "toggle") setPlaying((p) => !p)
            else if (c.action === "play") setPlaying(true)
            else if (c.action === "pause") setPlaying(false)
            else if (c.action === "next") playNextInQueue()
            else if (c.action === "prev") playPrevInQueue()
            else if (c.action === "volume" && typeof c.value === "number") {
              setVolume(Math.min(1, Math.max(0, c.value)))
            } else if (c.action === "close_mini") {
              setMiniPlayer(false)
              void applyMiniPlayerWindow(false)
            }
          }
        })
        .catch(() => {})
    }, 350)
    return () => window.clearInterval(id)
  }, [hasSrc, miniPlayer, playNextInQueue, playPrevInQueue, setPlaying, setMiniPlayer])

  useEffect(() => {
    if (!hasSrc && miniPlayer) {
      setMiniPlayer(false)
      void applyMiniPlayerWindow(false)
    }
  }, [hasSrc, miniPlayer, setMiniPlayer])

  useEffect(() => {
    if (miniPlayer) setLyricsOpen(false)
  }, [miniPlayer])

  const onTime = () => {
    if (seeking) return
    const el = mediaRef.current
    if (!el || !el.duration) return
    setProgress(el.currentTime / el.duration)
    setCurrent(fmt(el.currentTime))
    setCurrentSec(el.currentTime)
    setDurationSec(el.duration)
    setTotal(fmt(el.duration))
  }

  function seekTo(fraction: number) {
    const el = mediaRef.current
    if (!el || !el.duration) return
    const t = Math.min(1, Math.max(0, fraction)) * el.duration
    el.currentTime = t
    setProgress(fraction)
    setCurrent(fmt(t))
    setCurrentSec(t)
    setTotal(fmt(el.duration))
  }

  function seekToSec(sec: number) {
    const el = mediaRef.current
    if (!el || !el.duration) return
    const t = Math.min(el.duration, Math.max(0, sec))
    el.currentTime = t
    setProgress(t / el.duration)
    setCurrent(fmt(t))
    setCurrentSec(t)
  }

  function onEnded() {
    if (!playNextInQueue()) setPlaying(false)
  }

  function onClose() {
    void applyFullscreen(false)
    if (miniPlayer) {
      setMiniPlayer(false)
      void applyMiniPlayerWindow(false)
    }
    closePlayer()
  }

  async function toggleMiniPlayer() {
    const next = !miniPlayer
    setMiniPlayer(next)
    try {
      const res = await applyMiniPlayerWindow(next)
      if (next && !res.ok) setMiniPlayer(false)
    } catch {
      setMiniPlayer(false)
    }
  }

  if (hidden || !hasSrc) return null

  const trackPath = player?.path || (player?.src ? filePathFromPlayerSrc(player.src) : "")
  const RepeatIcon = repeat === "one" ? Repeat1 : Repeat

  const audioEl =
    !isVideo && player?.src ? (
      <audio
        ref={mediaRef as React.RefObject<HTMLAudioElement>}
        src={player.src}
        onTimeUpdate={onTime}
        onEnded={onEnded}
        className="pointer-events-none absolute h-0 w-0 opacity-0"
      />
    ) : null

  // Spotify-like: left meta | center transport+seek | right utils
  const controls = (
    <div
      className={cn(
        "bg-card/95 border-border grid h-[84px] shrink-0 grid-cols-[minmax(160px,1fr)_minmax(240px,1.4fr)_minmax(160px,1fr)] items-center gap-2 border-t px-4 backdrop-blur-sm transition-opacity duration-300",
        !isVideo && "fixed z-40 right-0 bottom-0 left-[232px]",
        isVideo && !uiVisible && "pointer-events-none opacity-0",
        miniPlayer && "pointer-events-none opacity-0",
      )}
    >
      {/* Left */}
      <div className="flex min-w-0 items-center gap-2">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{player?.title ?? "—"}</p>
          <p className="text-muted-foreground truncate text-xs">
            {player?.artist ?? ""}
            {isVideo ? " · Видео" : ""}
          </p>
        </div>
        <button
          type="button"
          aria-label="Закрыть трек"
          onClick={onClose}
          className="text-muted-foreground hover:text-foreground flex size-8 shrink-0 items-center justify-center rounded-lg"
        >
          <X className="size-3.5" />
        </button>
        <button
          type="button"
          title="В плейлист"
          disabled={!trackPath}
          onClick={() => setAddPlOpen(true)}
          className="text-muted-foreground hover:text-foreground flex size-8 shrink-0 items-center justify-center rounded-lg disabled:opacity-40"
        >
          <span className="text-sm font-bold">+</span>
        </button>
      </div>

      {/* Center */}
      <div className="flex min-w-0 flex-col items-center justify-center gap-1.5">
        <div className="flex items-center gap-1">
          <button
            type="button"
            title={shuffle ? "Перемешивание вкл." : "Вперемешку"}
            onClick={() => setShuffle((v) => !v)}
            className={cn(
              "flex size-8 items-center justify-center rounded-lg",
              shuffle ? "text-primary" : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Shuffle className="size-3.5" />
          </button>
          <button
            type="button"
            aria-label="Предыдущий"
            disabled={!canPrev}
            onClick={() => playPrevInQueue()}
            className={cn(
              "flex size-8 items-center justify-center rounded-lg",
              canPrev ? "text-muted-foreground hover:text-foreground" : "text-muted-foreground/40",
            )}
          >
            <SkipBack className="size-4" />
          </button>
          <button
            type="button"
            aria-label={playing ? "Пауза" : "Воспроизведение"}
            onClick={() => setPlaying(!playing)}
            className="bg-primary text-primary-foreground flex size-9 items-center justify-center rounded-full"
          >
            {playing ? <Pause className="size-4" /> : <Play className="size-4" />}
          </button>
          <button
            type="button"
            aria-label="Следующий"
            disabled={!canNext}
            onClick={() => playNextInQueue()}
            className={cn(
              "flex size-8 items-center justify-center rounded-lg",
              canNext ? "text-muted-foreground hover:text-foreground" : "text-muted-foreground/40",
            )}
          >
            <SkipForward className="size-4" />
          </button>
          <button
            type="button"
            title={
              repeat === "off"
                ? "Повтор выкл."
                : repeat === "all"
                  ? "Повтор очереди"
                  : "Повтор трека"
            }
            onClick={() => cycleRepeat()}
            className={cn(
              "flex size-8 items-center justify-center rounded-lg",
              repeat !== "off" ? "text-primary" : "text-muted-foreground hover:text-foreground",
            )}
          >
            <RepeatIcon className="size-3.5" />
          </button>
        </div>
        <div className="flex w-full max-w-md items-center gap-2 px-1">
          <span className="text-muted-foreground w-8 shrink-0 text-right text-[11px] tabular-nums">
            {current}
          </span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.001}
            value={Number.isFinite(progress) ? progress : 0}
            aria-label="Позиция"
            className="accent-primary h-1 min-w-0 flex-1 cursor-pointer"
            onChange={(e) => {
              setSeeking(true)
              seekTo(Number(e.target.value))
            }}
            onMouseUp={() => setSeeking(false)}
            onTouchEnd={() => setSeeking(false)}
          />
          <span className="text-muted-foreground w-8 shrink-0 text-[11px] tabular-nums">{total}</span>
        </div>
      </div>

      {/* Right */}
      <div className="relative flex items-center justify-end gap-0.5">
        <button
          type="button"
          title="Текст песни (L)"
          onClick={() => setLyricsOpen((v) => !v)}
          className={cn(
            "flex size-8 items-center justify-center rounded-lg",
            lyricsOpen ? "text-primary" : "text-muted-foreground hover:text-foreground",
          )}
        >
          <Mic2 className="size-4" />
        </button>
        <button
          type="button"
          title="Очередь (Q)"
          onClick={() => setQueueOpen((v) => !v)}
          className={cn(
            "flex size-8 items-center justify-center rounded-lg",
            queueOpen ? "text-primary" : "text-muted-foreground hover:text-foreground",
          )}
        >
          <ListMusic className="size-4" />
        </button>
        {isVideo ? (
          <button
            type="button"
            aria-label={theater ? "Выйти из полного экрана" : "На весь экран"}
            onClick={() => void applyFullscreen(!theater)}
            className="text-muted-foreground hover:text-foreground flex size-8 items-center justify-center rounded-lg"
          >
            {theater ? <Minimize className="size-4" /> : <Maximize className="size-4" />}
          </button>
        ) : null}
        <Volume2 className="text-muted-foreground ml-1 size-4 shrink-0" aria-hidden />
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={volume}
          onChange={(e) => setVolume(Number(e.target.value))}
          className="accent-primary h-1 w-20 cursor-pointer"
          aria-label="Громкость"
        />
        <button
          type="button"
          title="Мини-плеер"
          onClick={() => void toggleMiniPlayer()}
          className={cn(
            "flex size-8 items-center justify-center rounded-lg",
            miniPlayer ? "text-primary" : "text-muted-foreground hover:text-foreground",
          )}
        >
          <PictureInPicture2 className="size-4" />
        </button>
        <PlayerQueuePanel open={queueOpen} onClose={() => setQueueOpen(false)} />
      </div>
    </div>
  )

  const extras = (
    <>
      <AddToPlaylistsModal
        open={addPlOpen}
        path={trackPath || null}
        trackTitle={player?.title}
        onClose={() => setAddPlOpen(false)}
      />
      <LyricsPanel
        open={lyricsOpen}
        title={player?.title || ""}
        artist={player?.artist || ""}
        currentTime={currentSec}
        duration={durationSec || undefined}
        onSeek={seekToSec}
        onClose={() => setLyricsOpen(false)}
        docked={false}
      />
    </>
  )

  if (!isVideo)
    return (
      <>
        {audioEl}
        {controls}
        {extras}
      </>
    )

  return (
    <>
      {audioEl}
      <div
        ref={shellRef}
        className={cn(
          "flex flex-col overflow-hidden",
          theater
            ? "fixed inset-0 z-[100] bg-black"
            : "border-border bg-background/95 fixed right-0 bottom-0 left-[232px] z-40 border-t backdrop-blur-sm",
        )}
      >
        <div
          className={cn(
            "relative flex min-h-0 w-full items-center justify-center",
            theater ? "min-h-0 flex-1 bg-black" : "bg-background",
          )}
          onDoubleClick={() => void applyFullscreen(!theater)}
        >
          <div
            className={cn(
              "relative overflow-hidden",
              theater
                ? "h-full w-full bg-black"
                : "aspect-video h-[min(38vh,calc((100vw-232px)*9/16))] w-auto max-w-full bg-zinc-950",
            )}
          >
            <video
              ref={mediaRef as React.RefObject<HTMLVideoElement>}
              src={player?.src}
              className={cn(
                "object-contain",
                theater ? "h-full w-full" : "absolute inset-0 h-full w-full",
              )}
              onTimeUpdate={onTime}
              onEnded={onEnded}
              onClick={() => setPlaying(!playing)}
              controls={false}
              playsInline
            />
          </div>
        </div>
        <div
          className={cn(
            "z-10 shrink-0 transition-opacity duration-300",
            theater && "absolute inset-x-0 bottom-0",
            theater && !uiVisible && "pointer-events-none opacity-0",
          )}
        >
          {controls}
        </div>
      </div>
      {extras}
    </>
  )
}

function fmt(sec: number) {
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${m}:${String(s).padStart(2, "0")}`
}
