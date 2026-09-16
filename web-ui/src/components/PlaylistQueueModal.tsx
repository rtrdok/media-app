import { useEffect, useMemo, useState } from "react"
import { AppModal } from "@/components/ui/AppModal"
import { Button } from "@/components/ui/button"
import { playlistUrls, postJob } from "@/lib/api"

export type PlaylistEntry = { id?: string; title: string; url: string; duration?: number }

type Props = {
  open: boolean
  url: string
  kind: "audio" | "video"
  quality: string
  fmt: string
  onClose: () => void
  onQueued: () => void
}

export function PlaylistQueueModal({ open, url, kind, quality, fmt, onClose, onQueued }: Props) {
  const [title, setTitle] = useState("Плейлист")
  const [entries, setEntries] = useState<PlaylistEntry[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState("")

  useEffect(() => {
    if (!open || !url) return
    setBusy(true)
    setErr("")
    setEntries([])
    setSelected(new Set())
    void playlistUrls(url)
      .then((j) => {
        if (!j.ok && !(j.entries && j.entries.length)) {
          setErr(j.error || "Не удалось прочитать плейлист")
          return
        }
        setTitle(j.title || "Плейлист")
        const list = j.entries || []
        setEntries(list)
        setSelected(new Set(list.map((e) => e.url)))
        if (!list.length) {
          setErr(j.error || "В плейлисте 0 роликов — проверьте ссылку (нужен list=PL…) или cookies")
        }
      })
      .catch((e) => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }, [open, url])

  const allOn = useMemo(
    () => entries.length > 0 && selected.size === entries.length,
    [entries, selected],
  )

  function toggle(u: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(u)) next.delete(u)
      else next.add(u)
      return next
    })
  }

  function toggleAll() {
    if (allOn) setSelected(new Set())
    else setSelected(new Set(entries.map((e) => e.url)))
  }

  async function enqueue() {
    const urls = entries.filter((e) => selected.has(e.url)).map((e) => e.url)
    if (!urls.length) return
    setBusy(true)
    try {
      await postJob({ url: urls.join("\n"), kind, quality, fmt })
      onQueued()
      onClose()
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AppModal
      open={open}
      onClose={onClose}
      title={title}
      description="Выберите ролики для очереди загрузок"
      className="max-w-lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Отмена
          </Button>
          <Button onClick={() => void enqueue()} disabled={busy || !selected.size}>
            В очередь ({selected.size})
          </Button>
        </>
      }
    >
      {err ? <p className="text-destructive mb-2 text-sm">{err}</p> : null}
      {busy && !entries.length ? (
        <p className="text-muted-foreground py-8 text-center text-sm">Читаю плейлист…</p>
      ) : (
        <>
          <label className="hover:bg-muted/60 mb-2 flex cursor-pointer items-center gap-3 rounded-xl px-2 py-2">
            <input
              type="checkbox"
              className="accent-primary size-4"
              checked={allOn}
              onChange={toggleAll}
            />
            <span className="text-sm font-medium">Выбрать все ({entries.length})</span>
          </label>
          <div className="max-h-72 space-y-0.5 overflow-y-auto">
            {entries.map((e) => (
              <label
                key={e.url}
                className="hover:bg-muted/60 flex cursor-pointer items-start gap-3 rounded-xl px-2 py-2"
              >
                <input
                  type="checkbox"
                  className="accent-primary mt-0.5 size-4"
                  checked={selected.has(e.url)}
                  onChange={() => toggle(e.url)}
                />
                <span className="min-w-0 flex-1 truncate text-sm">{e.title || e.url}</span>
              </label>
            ))}
          </div>
        </>
      )}
    </AppModal>
  )
}

export function isPlaylistUrl(raw: string): boolean {
  try {
    const u = new URL(raw.trim())
    const host = u.hostname.replace(/^www\./, "").toLowerCase()
    if (host.includes("youtube.com") || host === "youtu.be" || host.includes("music.youtube.com")) {
      const list = u.searchParams.get("list") || ""
      if (list && !list.startsWith("RD") && !list.startsWith("UL")) return true
      if (/\/playlist/i.test(u.pathname)) return true
    }
    if (host.includes("vk.com") || host.includes("vk.ru")) {
      if (/playlist|audio_playlist|audios/i.test(u.pathname + u.search)) return true
    }
  } catch {
    /* ignore */
  }
  return false
}
