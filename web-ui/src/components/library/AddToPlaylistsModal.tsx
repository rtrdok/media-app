import { useCallback, useEffect, useState } from "react"
import { AppModal } from "@/components/ui/AppModal"
import { Button } from "@/components/ui/button"
import {
  libraryPlaylistAddTracks,
  libraryPlaylistCreate,
  libraryPlaylists,
  type LibraryPlaylist,
} from "@/lib/api"
import { cn } from "@/lib/utils"

type Props = {
  open: boolean
  path: string | null
  trackTitle?: string
  onClose: () => void
  onSaved?: () => void
}

/** Выбор одного или нескольких плейлистов для добавления трека. */
export function AddToPlaylistsModal({ open, path, trackTitle, onClose, onSaved }: Props) {
  const [playlists, setPlaylists] = useState<LibraryPlaylist[]>([])
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState("Новый плейлист")
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState("")

  const reload = useCallback(async () => {
    const j = await libraryPlaylists()
    if (j.ok) setPlaylists(j.items || [])
  }, [])

  useEffect(() => {
    if (!open) return
    setSelected(new Set())
    setCreating(false)
    setNewName("Новый плейлист")
    setMsg("")
    void reload()
  }, [open, reload])

  function toggle(id: number) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function createAndSelect() {
    const name = newName.trim()
    if (!name) return
    setBusy(true)
    try {
      const j = await libraryPlaylistCreate(name)
      if (j.ok && j.playlist) {
        await reload()
        setSelected((prev) => new Set(prev).add(j.playlist!.id))
        setCreating(false)
      }
    } finally {
      setBusy(false)
    }
  }

  async function save() {
    if (!path || !selected.size) return
    setBusy(true)
    setMsg("")
    try {
      let added = 0
      for (const id of selected) {
        const j = await libraryPlaylistAddTracks(id, [path])
        if (j.ok) added += j.added || 0
      }
      setMsg(added ? `Добавлено в ${selected.size} плейлист(ов)` : "Уже было в выбранных")
      onSaved?.()
      window.setTimeout(onClose, 500)
    } catch (e) {
      setMsg(String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AppModal
      open={open}
      title="Добавить в плейлист"
      description={trackTitle ? `«${trackTitle}»` : undefined}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Отмена
          </Button>
          <Button onClick={() => void save()} disabled={busy || !path || !selected.size}>
            Добавить
          </Button>
        </>
      }
    >
      <div className="max-h-64 space-y-1 overflow-y-auto pr-1">
        {playlists.length === 0 && !creating ? (
          <p className="text-muted-foreground text-sm">Плейлистов пока нет — создай первый.</p>
        ) : null}
        {playlists.map((pl) => {
          const on = selected.has(pl.id)
          return (
            <label
              key={pl.id}
              className={cn(
                "hover:bg-muted/60 flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2.5",
                on && "bg-muted",
              )}
            >
              <input
                type="checkbox"
                className="accent-primary size-4"
                checked={on}
                onChange={() => toggle(pl.id)}
              />
              <span className="min-w-0 flex-1 truncate text-sm font-medium">{pl.name}</span>
              <span className="text-muted-foreground text-xs">{pl.track_count ?? 0}</span>
            </label>
          )
        })}
      </div>
      {creating ? (
        <div className="mt-3 flex gap-2">
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            className="border-input bg-background h-9 min-w-0 flex-1 rounded-lg border px-3 text-sm outline-none"
            autoFocus
            onKeyDown={(e) => {
              if (e.key === "Enter") void createAndSelect()
            }}
          />
          <Button size="sm" className="h-9" disabled={busy} onClick={() => void createAndSelect()}>
            Создать
          </Button>
        </div>
      ) : (
        <Button
          variant="outline"
          size="sm"
          className="mt-3"
          onClick={() => setCreating(true)}
        >
          + Новый плейлист
        </Button>
      )}
      {msg ? <p className="text-muted-foreground mt-2 text-xs">{msg}</p> : null}
    </AppModal>
  )
}
