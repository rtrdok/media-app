import { useEffect, useMemo, useRef, useState } from "react"
import { X } from "lucide-react"
import { fetchLyrics } from "@/lib/api"
import { cn } from "@/lib/utils"

type Props = {
  open: boolean
  title: string
  artist: string
  currentTime: number
  duration?: number
  onSeek?: (sec: number) => void
  onClose: () => void
  /** true = панель в основной зоне UI; false = компактный оверлей */
  docked?: boolean
}

type LyricLine = { t: number; text: string }

function parseLrc(raw: string): LyricLine[] | null {
  const lines: LyricLine[] = []
  for (const row of raw.split(/\r?\n/)) {
    const stampRe = /\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\]/g
    const stamps: number[] = []
    let m: RegExpExecArray | null
    while ((m = stampRe.exec(row))) {
      const mm = Number(m[1])
      const ss = Number(m[2])
      const frac = m[3] || "0"
      const ms =
        frac.length <= 2 ? Number(frac) * (frac.length === 1 ? 100 : 10) : Number(frac.slice(0, 3))
      stamps.push(mm * 60 + ss + ms / 1000)
    }
    if (!stamps.length) continue
    const text = row.replace(/\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\]/g, "").trim()
    if (!text) continue
    for (const t of stamps) lines.push({ t, text })
  }
  if (lines.length < 2) return null
  lines.sort((a, b) => a.t - b.t)
  return lines
}

export function LyricsPanel({
  open,
  title,
  artist,
  currentTime,
  duration,
  onSeek,
  onClose,
  docked = true,
}: Props) {
  const [raw, setRaw] = useState("")
  const [syncedFlag, setSyncedFlag] = useState(false)
  const [msg, setMsg] = useState("Загрузка…")
  const [busy, setBusy] = useState(false)
  const activeRef = useRef<HTMLButtonElement | null>(null)

  useEffect(() => {
    if (!open) return
    setBusy(true)
    setMsg("Ищем текст…")
    setRaw("")
    setSyncedFlag(false)
    void fetchLyrics(title, artist, duration)
      .then((j) => {
        if (j.ok && j.lyrics) {
          setRaw(j.lyrics)
          setSyncedFlag(Boolean(j.synced))
          setMsg("")
        } else setMsg(j.error || "Текст не найден")
      })
      .catch((e) => setMsg(String(e)))
      .finally(() => setBusy(false))
  }, [open, title, artist, duration])

  const lines = useMemo(() => (raw ? parseLrc(raw) : null), [raw])
  const synced = Boolean(lines && (syncedFlag || lines.length > 0))

  const activeIdx = useMemo(() => {
    if (!lines?.length) return -1
    let idx = 0
    for (let i = 0; i < lines.length; i++) {
      if (lines[i].t <= currentTime + 0.05) idx = i
      else break
    }
    return idx
  }, [lines, currentTime])

  useEffect(() => {
    if (!open || !synced || activeIdx < 0) return
    activeRef.current?.scrollIntoView({ behavior: "smooth", block: "center" })
  }, [activeIdx, open, synced])

  if (!open) return null

  return (
    <div
      className={cn(
        "bg-background/95 flex flex-col backdrop-blur-sm",
        docked
          ? "absolute inset-0 z-20"
          : "border-border fixed top-16 right-0 bottom-24 left-[232px] z-30 border-t",
      )}
    >
      <div className="border-border flex shrink-0 items-start justify-between gap-4 border-b px-8 py-5">
        <div className="min-w-0">
          <p className="text-muted-foreground text-xs tracking-wide uppercase">Текст песни</p>
          <h2 className="mt-1 truncate text-xl font-semibold tracking-tight">{title || "—"}</h2>
          {artist ? <p className="text-muted-foreground mt-0.5 truncate text-sm">{artist}</p> : null}
        </div>
        <button
          type="button"
          aria-label="Закрыть текст"
          onClick={onClose}
          className="text-muted-foreground hover:text-foreground flex size-9 shrink-0 items-center justify-center rounded-lg"
        >
          <X className="size-4" />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-8 py-8">
        {busy || msg ? (
          <p className="text-muted-foreground text-sm">{msg || "Загрузка…"}</p>
        ) : synced && lines ? (
          <div className="mx-auto max-w-2xl space-y-1">
            {lines.map((line, i) => {
              const active = i === activeIdx
              const near = Math.abs(i - activeIdx) <= 1
              return (
                <button
                  key={`${line.t}-${i}`}
                  type="button"
                  ref={active ? activeRef : undefined}
                  onClick={() => onSeek?.(line.t)}
                  className={cn(
                    "block w-full rounded-lg px-3 py-2.5 text-left transition-all duration-300",
                    active
                      ? "text-foreground scale-[1.02] text-2xl font-semibold tracking-tight"
                      : near
                        ? "text-muted-foreground text-lg"
                        : "text-muted-foreground/40 text-base",
                  )}
                >
                  {line.text}
                </button>
              )
            })}
          </div>
        ) : (
          <pre className="mx-auto max-w-2xl whitespace-pre-wrap font-sans text-sm leading-relaxed">
            {raw}
          </pre>
        )}
      </div>
    </div>
  )
}

/** @deprecated имя для совместимости */
export const LyricsModal = LyricsPanel
