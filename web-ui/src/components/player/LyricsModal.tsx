import { useEffect, useMemo, useRef, useState } from "react"
import { AppModal } from "@/components/ui/AppModal"
import { Button } from "@/components/ui/button"
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

export function LyricsModal({
  open,
  title,
  artist,
  currentTime,
  duration,
  onSeek,
  onClose,
}: Props) {
  const [raw, setRaw] = useState("")
  const [syncedFlag, setSyncedFlag] = useState(false)
  const [msg, setMsg] = useState("Загрузка…")
  const [busy, setBusy] = useState(false)
  const listRef = useRef<HTMLDivElement | null>(null)
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

  return (
    <AppModal
      open={open}
      title="Текст песни"
      description={artist ? `${title} — ${artist}` : title}
      onClose={onClose}
      className="max-w-xl"
      footer={
        <Button variant="ghost" onClick={onClose}>
          Закрыть
        </Button>
      }
    >
      {busy || msg ? (
        <p className="text-muted-foreground text-sm">{msg || "Загрузка…"}</p>
      ) : synced && lines ? (
        <div
          ref={listRef}
          className="max-h-[min(60vh,520px)] space-y-1 overflow-y-auto px-1 py-6"
        >
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
                  "block w-full rounded-lg px-3 py-2 text-left transition-all duration-300",
                  active
                    ? "text-foreground scale-[1.02] text-lg font-semibold tracking-tight"
                    : near
                      ? "text-muted-foreground text-base"
                      : "text-muted-foreground/45 text-sm",
                )}
              >
                {line.text}
              </button>
            )
          })}
        </div>
      ) : (
        <pre className="max-h-[50vh] overflow-y-auto whitespace-pre-wrap font-sans text-sm leading-relaxed">
          {raw}
        </pre>
      )}
    </AppModal>
  )
}
