import { Clock, Library, ListMusic, Search } from "lucide-react"
import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react"
import { AppModal } from "@/components/ui/AppModal"
import { useApp } from "@/context/AppProvider"
import { fetchLibrary, libraryPlaylists, type LibraryPlaylist } from "@/lib/api"
import { playerTrackFromHistory, playerTrackFromLibrary } from "@/lib/media"
import type { HistoryItem, PageId } from "@/types"
import { cn } from "@/lib/utils"

type LibHit = {
  path: string
  title: string
  artist?: string
  kind?: string
  cover?: string
  duration?: string
}

type SearchHit =
  | { kind: "history"; item: HistoryItem }
  | { kind: "library"; item: LibHit }
  | { kind: "playlist"; item: LibraryPlaylist }

type GlobalSearchModalProps = {
  open: boolean
  onClose: () => void
}

export function GlobalSearchModal({ open, onClose }: GlobalSearchModalProps) {
  const { state, setPage, playWithQueue } = useApp()
  const [q, setQ] = useState("")
  const [lib, setLib] = useState<LibHit[]>([])
  const [pls, setPls] = useState<LibraryPlaylist[]>([])
  const inputRef = useRef<HTMLInputElement | null>(null)
  const deferredQ = useDeferredValue(q.trim().toLowerCase())

  useEffect(() => {
    if (!open) return
    setQ("")
    window.setTimeout(() => inputRef.current?.focus(), 40)
    void fetchLibrary("flat")
      .then((j) => setLib((j.items as LibHit[]) || []))
      .catch(() => setLib([]))
    void libraryPlaylists()
      .then((j) => setPls(j.items || []))
      .catch(() => setPls([]))
  }, [open])

  const hits = useMemo(() => {
    if (!deferredQ) return [] as SearchHit[]
    const out: SearchHit[] = []
    for (const h of state?.history ?? []) {
      const blob = `${h.title} ${h.url} ${h.platform_name || ""}`.toLowerCase()
      if (blob.includes(deferredQ)) out.push({ kind: "history", item: h })
      if (out.length >= 40) break
    }
    for (const it of lib) {
      const blob = `${it.title} ${it.artist || ""}`.toLowerCase()
      if (blob.includes(deferredQ)) out.push({ kind: "library", item: it })
      if (out.length >= 80) break
    }
    for (const p of pls) {
      if ((p.name || "").toLowerCase().includes(deferredQ)) out.push({ kind: "playlist", item: p })
    }
    return out
  }, [deferredQ, state?.history, lib, pls])

  function go(page: PageId) {
    setPage(page)
    onClose()
  }

  function playHistory(h: HistoryItem) {
    if (!h.dest) return
    playWithQueue([playerTrackFromHistory(h)], 0)
    onClose()
  }

  function playLib(it: LibHit) {
    playWithQueue(
      [
        playerTrackFromLibrary({
          title: it.title,
          artist: it.artist,
          path: it.path,
          duration: it.duration,
          kind: it.kind,
          cover: it.cover,
        }),
      ],
      0,
    )
    onClose()
  }

  return (
    <AppModal
      open={open}
      onClose={onClose}
      title="Поиск"
      description="История, библиотека и плейлисты · Ctrl+K"
      className="max-w-lg"
      footer={null}
    >
      <div className="relative mb-3">
        <Search className="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2" />
        <input
          ref={inputRef}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Название, артист, ссылка…"
          className="border-input bg-background placeholder:text-muted-foreground w-full rounded-xl border py-2.5 pr-3 pl-10 text-sm outline-none"
        />
      </div>
      <div className="max-h-80 space-y-1 overflow-y-auto">
        {!deferredQ ? (
          <p className="text-muted-foreground px-1 py-6 text-center text-sm">Начните вводить запрос</p>
        ) : hits.length === 0 ? (
          <p className="text-muted-foreground px-1 py-6 text-center text-sm">Ничего не найдено</p>
        ) : (
          hits.map((hit, i) => {
            if (hit.kind === "history") {
              const h = hit.item
              return (
                <button
                  key={`h-${h.id}-${i}`}
                  type="button"
                  className={cn(
                    "hover:bg-muted/70 flex w-full items-start gap-3 rounded-xl px-2 py-2 text-left",
                  )}
                  onClick={() => {
                    if (h.dest) playHistory(h)
                    else go("home")
                  }}
                >
                  <Clock className="text-muted-foreground mt-0.5 size-4 shrink-0" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">{h.title || h.url}</span>
                    <span className="text-muted-foreground block truncate text-xs">
                      История · {h.platform_name || h.platform || "—"}
                    </span>
                  </span>
                </button>
              )
            }
            if (hit.kind === "library") {
              const it = hit.item
              return (
                <button
                  key={`l-${it.path}-${i}`}
                  type="button"
                  className="hover:bg-muted/70 flex w-full items-start gap-3 rounded-xl px-2 py-2 text-left"
                  onClick={() => playLib(it)}
                >
                  <Library className="text-muted-foreground mt-0.5 size-4 shrink-0" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">{it.title}</span>
                    <span className="text-muted-foreground block truncate text-xs">
                      Библиотека · {it.artist || "—"}
                    </span>
                  </span>
                </button>
              )
            }
            const p = hit.item
            return (
              <button
                key={`p-${p.id}`}
                type="button"
                className="hover:bg-muted/70 flex w-full items-start gap-3 rounded-xl px-2 py-2 text-left"
                onClick={() => go("library")}
              >
                <ListMusic className="text-muted-foreground mt-0.5 size-4 shrink-0" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{p.name}</span>
                  <span className="text-muted-foreground block truncate text-xs">
                    Плейлист · {p.track_count ?? 0} треков
                  </span>
                </span>
              </button>
            )
          })
        )}
      </div>
    </AppModal>
  )
}
