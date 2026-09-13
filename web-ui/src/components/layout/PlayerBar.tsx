import {
  ListMusic,
  Maximize,
  Minimize,
  Pause,
  Play,
  Shuffle,
  SkipBack,
  SkipForward,
  Volume2,
  X,
} from "lucide-react"
import { useEffect, useRef, useState } from "react"
import { AddToPlaylistsModal } from "@/components/library/AddToPlaylistsModal"
import { useApp } from "@/context/AppProvider"
import { setWindowFullscreen } from "@/lib/api"
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
  } = useApp()
  const mediaRef = useRef<HTMLVideoElement | HTMLAudioElement | null>(null)
  const shellRef = useRef<HTMLDivElement | null>(null)
  const nativeFs = useRef(false)
  const [progress, setProgress] = useState(0)
  const [current, setCurrent] = useState("0:00")
  const [total, setTotal] = useState(player?.durationLabel ?? "0:00")
  const [volume, setVolume] = useState(0.85)
  const [seeking, setSeeking] = useState(false)
  /** Настоящий fullscreen монитора (только по кнопке / двойному клику). */
  const [theater, setTheater] = useState(false)
  const [uiVisible, setUiVisible] = useState(true)
  const [addPlOpen, setAddPlOpen] = useState(false)
  const hideTimer = useRef(0)

  const hidden = page === "settings" && !showOnSettings
  const hasSrc = Boolean(player?.src)
  const isVideo =
    player?.kind === "video" || (player?.src ? isVideoSrc(player.src) : false)
  const canPrev = queueMeta.length > 1 && queueMeta.index > 0
  const canNext =
    queueMeta.length > 1 &&
    (queueMeta.index < queueMeta.length - 1 || shuffle)

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
    setProgress(0)
    void applyFullscreen(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps -- только смена трека
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

  const onTime = () => {
    if (seeking) return
    const el = mediaRef.current
    if (!el || !el.duration) return
    setProgress(el.currentTime / el.duration)
    setCurrent(fmt(el.currentTime))
    setTotal(fmt(el.duration))
  }

  function seekTo(fraction: number) {
    const el = mediaRef.current
    if (!el || !el.duration) return
    const t = Math.min(1, Math.max(0, fraction)) * el.duration
    el.currentTime = t
    setProgress(fraction)
    setCurrent(fmt(t))
    setTotal(fmt(el.duration))
  }

  function onEnded() {
    if (!playNextInQueue()) setPlaying(false)
  }

  function onClose() {
    void applyFullscreen(false)
    closePlayer()
  }

  if (hidden || !hasSrc) return null

  const trackPath = player?.path || (player?.src ? filePathFromPlayerSrc(player.src) : "")

  const controls = (
    <div
      className={cn(
        "bg-card/95 border-border flex h-[72px] shrink-0 items-center gap-4 border-t pr-6 pl-6 backdrop-blur-sm transition-opacity duration-300",
        !isVideo && "fixed z-40 right-0 bottom-0 left-[232px]",
        isVideo && !uiVisible && "pointer-events-none opacity-0",
      )}
    >
      {!isVideo && player?.src ? (
        <audio
          ref={mediaRef as React.RefObject<HTMLAudioElement>}
          src={player.src}
          onTimeUpdate={onTime}
          onEnded={onEnded}
        />
      ) : null}
      <div className="flex shrink-0 items-center gap-2">
        <button
          type="button"
          aria-label="Предыдущий трек"
          disabled={!canPrev}
          onClick={() => playPrevInQueue()}
          className={cn(
            "flex size-9 items-center justify-center rounded-lg",
            canPrev ? "text-muted-foreground hover:text-foreground" : "text-muted-foreground/40",
          )}
        >
          <SkipBack className="size-4" />
        </button>
        <button
          type="button"
          aria-label={playing ? "Пауза" : "Воспроизведение"}
          onClick={() => setPlaying(!playing)}
          className="bg-primary text-primary-foreground flex size-10 items-center justify-center rounded-full"
        >
          {playing ? <Pause className="size-4" /> : <Play className="size-4" />}
        </button>
        <button
          type="button"
          aria-label="Следующий трек"
          disabled={!canNext}
          onClick={() => playNextInQueue()}
          className={cn(
            "flex size-9 items-center justify-center rounded-lg",
            canNext ? "text-muted-foreground hover:text-foreground" : "text-muted-foreground/40",
          )}
        >
          <SkipForward className="size-4" />
        </button>
      </div>
      <div className="w-44 min-w-0 shrink-0">
        <p className="truncate text-sm font-medium">{player?.title ?? "—"}</p>
        <p className="text-muted-foreground truncate text-xs">
          {player?.artist ?? ""}
          {isVideo ? " · Видео" : ""}
          {queueMeta.length > 1 ? ` · ${queueMeta.index + 1}/${queueMeta.length}` : ""}
        </p>
      </div>
      <div className="flex min-w-0 flex-1 items-center gap-3">
        <span className="text-muted-foreground w-9 shrink-0 text-xs tabular-nums">{current}</span>
        <input
          type="range"
          min={0}
          max={1}
          step={0.001}
          value={Number.isFinite(progress) ? progress : 0}
          aria-label="Позиция воспроизведения"
          className="accent-primary h-1.5 min-w-[80px] flex-1 cursor-pointer"
          onChange={(e) => {
            setSeeking(true)
            seekTo(Number(e.target.value))
          }}
          onMouseUp={() => setSeeking(false)}
          onTouchEnd={() => setSeeking(false)}
        />
        <span className="text-muted-foreground w-9 shrink-0 text-right text-xs tabular-nums">{total}</span>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <Volume2 className="text-muted-foreground size-4 shrink-0" aria-hidden />
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={volume}
          onChange={(e) => setVolume(Number(e.target.value))}
          className="accent-primary h-1.5 w-24 cursor-pointer"
          aria-label="Уровень громкости"
        />
        {isVideo ? (
          <button
            type="button"
            aria-label={theater ? "Выйти из полного экрана" : "На весь экран"}
            title={theater ? "Выйти (Esc)" : "На весь экран монитора"}
            onClick={() => void applyFullscreen(!theater)}
            className="text-muted-foreground hover:text-foreground flex size-9 items-center justify-center rounded-lg"
          >
            {theater ? <Minimize className="size-4" /> : <Maximize className="size-4" />}
          </button>
        ) : null}
        <button
          type="button"
          aria-label={shuffle ? "Выключить перемешивание" : "Слушать вперемешку"}
          title={
            shuffle
              ? "Перемешивание вкл.: без повторов до конца очереди"
              : "Перемешать очередь (без повторов, пока все не сыграют)"
          }
          onClick={() => setShuffle((v) => !v)}
          className={cn(
            "flex size-9 items-center justify-center rounded-lg",
            shuffle ? "text-primary" : "text-muted-foreground hover:text-foreground",
          )}
        >
          <Shuffle className="size-4" />
        </button>
        <button
          type="button"
          aria-label="В плейлист"
          title="Добавить текущий трек в плейлист(ы)"
          disabled={!trackPath}
          onClick={() => setAddPlOpen(true)}
          className="text-muted-foreground hover:text-foreground flex size-9 items-center justify-center rounded-lg disabled:opacity-40"
        >
          <ListMusic className="size-4" />
        </button>
        <button
          type="button"
          aria-label="Закрыть плеер"
          onClick={onClose}
          className="text-muted-foreground hover:text-foreground flex size-9 items-center justify-center rounded-lg"
        >
          <X className="size-4" />
        </button>
      </div>
    </div>
  )

  const playlistModal = (
    <AddToPlaylistsModal
      open={addPlOpen}
      path={trackPath || null}
      trackTitle={player?.title}
      onClose={() => setAddPlOpen(false)}
    />
  )

  if (!isVideo)
    return (
      <>
        {controls}
        {playlistModal}
      </>
    )

  return (
    <>
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
    {playlistModal}
    </>
  )
}

function fmt(sec: number) {
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${m}:${String(s).padStart(2, "0")}`
}
