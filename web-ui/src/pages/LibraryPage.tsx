import {
  CheckSquare,
  Copy,
  Heart,
  LayoutGrid,
  List,
  ListMusic,
  MoreHorizontal,
  Plus,
  Search,
  Shuffle,
  Upload,
} from "lucide-react"
import { useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from "react"
import { AddToPlaylistsModal } from "@/components/library/AddToPlaylistsModal"
import { AppModal } from "@/components/ui/AppModal"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useApp } from "@/context/AppProvider"
import {
  fetchLibrary,
  libraryDuplicates,
  libraryOrganize,
  libraryPlaylistAddTracks,
  libraryPlaylistCreate,
  libraryPlaylistDelete,
  libraryPlaylistDetail,
  libraryPlaylistRemoveTrack,
  libraryPlaylists,
  libraryRemove,
  libraryRescan,
  openPath,
  type LibraryPlaylist,
} from "@/lib/api"
import { playerTrackFromLibrary } from "@/lib/media"
import { cn } from "@/lib/utils"

type LibItem = {
  path: string
  title: string
  artist?: string
  duration?: string
  kind?: string
  cover?: string
  mtime?: number
}

type ViewMode = "grid" | "list"

const COVER_GRAD = [
  "from-[#091a49] via-[#52339b] to-[#001132]",
  "from-[#001335] via-[#25267b] to-[#00283c]",
  "from-[#001917] via-[#004030] to-[#001b37]",
  "from-[#001634] via-[#00324d] to-[#005456]",
  "from-[#190f41] via-[#571c6e] to-[#001634]",
  "from-[#001e27] via-[#003672] to-[#003a28]",
]

const SORT_LABELS: Record<"recent" | "title" | "artist", string> = {
  recent: "Недавно добавленные",
  title: "По названию",
  artist: "По исполнителю",
}

const VIEW_KEY = "mediaapp.library.view"
const FAV_NAME = "★ Любимое"

function loadView(): ViewMode {
  try {
    const v = localStorage.getItem(VIEW_KEY)
    if (v === "list" || v === "grid") return v
  } catch {
    /* ignore */
  }
  return "grid"
}

function toTracks(rows: LibItem[]) {
  return rows.map((row) =>
    playerTrackFromLibrary({
      title: row.title,
      artist: row.artist,
      path: row.path,
      duration: row.duration,
      kind: row.kind,
      cover: row.cover,
    }),
  )
}

export function LibraryPage() {
  const { playWithQueue, state, player, closePlayer } = useApp()
  const [kind, setKind] = useState<"all" | "audio" | "video">("all")
  const [sort, setSort] = useState<"recent" | "title" | "artist">("recent")
  const [view, setView] = useState<ViewMode>(() => loadView())
  const [query, setQuery] = useState("")
  const [items, setItems] = useState<LibItem[]>([])
  const [playlists, setPlaylists] = useState<LibraryPlaylist[]>([])
  const [activePl, setActivePl] = useState<number | null>(null)
  const [favId, setFavId] = useState<number | null>(null)
  const [scanning, setScanning] = useState(false)
  const [createOpen, setCreateOpen] = useState(false)
  const [createName, setCreateName] = useState("Новый плейлист")
  const [createBusy, setCreateBusy] = useState(false)
  const [deleteId, setDeleteId] = useState<number | null>(null)
  const [deleteBusy, setDeleteBusy] = useState(false)
  const [removePath, setRemovePath] = useState<string | null>(null)
  const [removeTitle, setRemoveTitle] = useState<string | undefined>()
  const [removeBusy, setRemoveBusy] = useState(false)
  const [addPath, setAddPath] = useState<string | null>(null)
  const [addTitle, setAddTitle] = useState<string | undefined>()
  const [addBatchPaths, setAddBatchPaths] = useState<string[] | null>(null)
  const [selectMode, setSelectMode] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(() => new Set())
  const [batchRemoveOpen, setBatchRemoveOpen] = useState(false)
  const [batchRemoveBusy, setBatchRemoveBusy] = useState(false)
  const [organizeBusy, setOrganizeBusy] = useState(false)
  const [dupOpen, setDupOpen] = useState(false)
  const [dupBusy, setDupBusy] = useState(false)
  const [dupGroups, setDupGroups] = useState<
    { key: string; count: number; items: LibItem[] }[]
  >([])
  const lastDoneRef = useRef("")

  const loadPlaylists = useCallback(async () => {
    const j = await libraryPlaylists()
    if (!j.ok) return
    let list = j.items || []
    let fav = list.find((p) => p.name === FAV_NAME)
    if (!fav) {
      const created = await libraryPlaylistCreate(FAV_NAME)
      if (created.ok && created.playlist) {
        fav = created.playlist
        const again = await libraryPlaylists()
        if (again.ok) list = again.items || []
      }
    }
    setFavId(fav?.id ?? null)
    setPlaylists(list)
  }, [])

  const load = useCallback(async () => {
    if (activePl != null) {
      const j = await libraryPlaylistDetail(activePl)
      if (!j.ok) {
        setItems([])
        return
      }
      let list = (j.tracks as LibItem[]) || []
      if (kind !== "all") list = list.filter((t) => (t.kind || "audio") === kind)
      if (sort === "title") {
        list = [...list].sort((a, b) => (a.title || "").localeCompare(b.title || "", "ru"))
      } else if (sort === "artist") {
        list = [...list].sort((a, b) => (a.artist || "").localeCompare(b.artist || "", "ru"))
      }
      setItems(list)
      return
    }
    const j = await fetchLibrary("flat", `&kind=${kind}`)
    let list = (j.items as LibItem[]) || []
    if (sort === "title") {
      list = [...list].sort((a, b) => (a.title || "").localeCompare(b.title || "", "ru"))
    } else if (sort === "artist") {
      list = [...list].sort((a, b) => (a.artist || "").localeCompare(b.artist || "", "ru"))
    } else {
      list = [...list].sort((a, b) => (b.mtime || 0) - (a.mtime || 0))
    }
    setItems(list)
  }, [kind, sort, activePl])

  useEffect(() => {
    void load()
    void loadPlaylists()
  }, [load, loadPlaylists])

  useEffect(() => {
    let alive = true
    const tick = async () => {
      if (!alive || document.hidden) return
      await load()
      await loadPlaylists()
    }
    const id = window.setInterval(() => void tick(), 8000)
    const onFocus = () => void tick()
    window.addEventListener("focus", onFocus)
    document.addEventListener("visibilitychange", onFocus)
    return () => {
      alive = false
      window.clearInterval(id)
      window.removeEventListener("focus", onFocus)
      document.removeEventListener("visibilitychange", onFocus)
    }
  }, [load, loadPlaylists])

  useEffect(() => {
    const done = (state?.queue || [])
      .filter((q) => q.status === "done")
      .map((q) => `${q.id}:${q.status}`)
      .join("|")
    if (done && done !== lastDoneRef.current) {
      lastDoneRef.current = done
      void load()
      void loadPlaylists()
    }
  }, [state?.queue, load, loadPlaylists])

  useEffect(() => {
    try {
      localStorage.setItem(VIEW_KEY, view)
    } catch {
      /* ignore */
    }
  }, [view])

  const deferredItems = useDeferredValue(items)

  const filteredItems = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return deferredItems
    return deferredItems.filter(
      (it) =>
        (it.title || "").toLowerCase().includes(q) ||
        (it.artist || "").toLowerCase().includes(q),
    )
  }, [deferredItems, query])

  const activePlaylist = useMemo(
    () => playlists.find((p) => p.id === activePl) || null,
    [playlists, activePl],
  )

  const audioOnly = useMemo(
    () => filteredItems.filter((t) => (t.kind || "audio") !== "video"),
    [filteredItems],
  )

  function play(it: LibItem, shuffle = false) {
    const tracks = toTracks(filteredItems)
    const idx = filteredItems.findIndex((row) => row.path === it.path)
    playWithQueue(tracks, idx >= 0 ? idx : 0, { shuffle })
  }

  function playVisible(shuffle: boolean) {
    const list = kind === "video" ? filteredItems : audioOnly.length ? audioOnly : filteredItems
    if (!list.length) return
    playWithQueue(toTracks(list), 0, { shuffle })
  }

  async function toggleFavorite(path: string) {
    if (favId == null) return
    await libraryPlaylistAddTracks(favId, [path])
    await loadPlaylists()
    if (activePl === favId) await load()
  }

  async function playAllPlaylistsShuffled() {
    if (!playlists.length) return
    const seen = new Set<string>()
    const merged: LibItem[] = []
    for (const pl of playlists) {
      const j = await libraryPlaylistDetail(pl.id)
      if (!j.ok) continue
      for (const t of (j.tracks as LibItem[]) || []) {
        if (!t.path || seen.has(t.path)) continue
        if (kind === "audio" && t.kind === "video") continue
        if (kind === "video" && t.kind !== "video") continue
        seen.add(t.path)
        merged.push(t)
      }
    }
    if (!merged.length) return
    playWithQueue(toTracks(merged), 0, { shuffle: true })
  }

  async function forceScan() {
    setScanning(true)
    try {
      await libraryRescan()
      await load()
      await loadPlaylists()
    } finally {
      setScanning(false)
    }
  }

  function openCreate() {
    setCreateName("Новый плейлист")
    setCreateOpen(true)
  }

  async function submitCreate() {
    const name = createName.trim()
    if (!name) return
    setCreateBusy(true)
    try {
      const j = await libraryPlaylistCreate(name)
      if (j.ok && j.playlist) {
        await loadPlaylists()
        setActivePl(j.playlist.id)
        setCreateOpen(false)
      }
    } finally {
      setCreateBusy(false)
    }
  }

  async function addToPlaylist(playlistId: number, path: string) {
    await libraryPlaylistAddTracks(playlistId, [path])
    await loadPlaylists()
    if (activePl === playlistId) await load()
  }

  async function removeFromActive(path: string) {
    if (activePl == null) return
    await libraryPlaylistRemoveTrack(activePl, path)
    await load()
    await loadPlaylists()
  }

  async function confirmRemoveFile() {
    if (!removePath) return
    setRemoveBusy(true)
    try {
      // файл занят плеером — сначала остановить
      const playingPath = player?.path || ""
      const norm = (s: string) => s.replace(/\//g, "\\").toLowerCase()
      if (playingPath && norm(playingPath) === norm(removePath)) {
        closePlayer()
        await new Promise((r) => window.setTimeout(r, 350))
      }
      const j = await libraryRemove(removePath, true)
      if (!j.ok || j.error) {
        window.alert(j.error || "Не удалось удалить файл (возможно, он открыт в другом приложении).")
        return
      }
      setRemovePath(null)
      setRemoveTitle(undefined)
      await load()
      await loadPlaylists()
    } catch (e) {
      window.alert(e instanceof Error ? e.message : String(e))
    } finally {
      setRemoveBusy(false)
    }
  }

  function toggleSelectMode() {
    setSelectMode((on) => {
      if (on) setSelected(new Set())
      return !on
    })
  }

  function toggleSelected(path: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(path)) next.delete(path)
      else next.add(path)
      return next
    })
  }

  function clearSelection() {
    setSelected(new Set())
  }

  async function stopPlayerIfPlaying(paths: string[]) {
    const playingPath = player?.path || ""
    const norm = (s: string) => s.replace(/\//g, "\\").toLowerCase()
    if (!playingPath) return
    if (paths.some((p) => norm(p) === norm(playingPath))) {
      closePlayer()
      await new Promise((r) => window.setTimeout(r, 350))
    }
  }

  async function removePathsFromLibrary(paths: string[]) {
    await stopPlayerIfPlaying(paths)
    for (const p of paths) {
      const j = await libraryRemove(p, true)
      if (!j.ok || j.error) {
        window.alert(j.error || "Не удалось удалить файл (возможно, он открыт в другом приложении).")
        return false
      }
    }
    return true
  }

  async function confirmBatchRemove() {
    const paths = [...selected]
    if (!paths.length) return
    setBatchRemoveBusy(true)
    try {
      const ok = await removePathsFromLibrary(paths)
      if (ok) {
        setBatchRemoveOpen(false)
        setSelected(new Set())
        await load()
        await loadPlaylists()
      }
    } catch (e) {
      window.alert(e instanceof Error ? e.message : String(e))
    } finally {
      setBatchRemoveBusy(false)
    }
  }

  async function organizeSelected() {
    const paths = [...selected]
    if (!paths.length) return
    if (!window.confirm(`Разложить ${paths.length} файл(ов) по папкам артистов?`)) return
    setOrganizeBusy(true)
    try {
      const j = await libraryOrganize(paths)
      if (!j.ok) {
        window.alert("Не удалось разложить файлы.")
        return
      }
      setSelected(new Set())
      await load()
      await loadPlaylists()
    } finally {
      setOrganizeBusy(false)
    }
  }

  async function openDuplicates() {
    setDupBusy(true)
    try {
      const j = await libraryDuplicates()
      if (!j.ok) {
        window.alert("Не удалось загрузить дубликаты.")
        return
      }
      const groups = (j.groups || []).map((g) => ({
        key: g.key,
        count: g.count,
        items: (g.items || []).map((row) => row as LibItem),
      }))
      setDupGroups(groups)
      setDupOpen(true)
    } finally {
      setDupBusy(false)
    }
  }

  async function removeDupItem(it: LibItem) {
    const ok = await removePathsFromLibrary([it.path])
    if (!ok) return
    setDupGroups((prev) =>
      prev
        .map((g) => ({
          ...g,
          items: g.items.filter((x) => x.path !== it.path),
          count: g.items.filter((x) => x.path !== it.path).length,
        }))
        .filter((g) => g.items.length > 1),
    )
    await load()
    await loadPlaylists()
  }

  async function confirmDelete() {
    if (deleteId == null) return
    setDeleteBusy(true)
    try {
      await libraryPlaylistDelete(deleteId)
      if (activePl === deleteId) setActivePl(null)
      setDeleteId(null)
      await loadPlaylists()
    } finally {
      setDeleteBusy(false)
    }
  }

  function selectionCheckbox(it: LibItem) {
    if (!selectMode) return null
    const checked = selected.has(it.path)
    return (
      <button
        type="button"
        aria-label={checked ? "Снять выбор" : "Выбрать"}
        className="bg-background/80 hover:bg-background absolute top-3 right-3 flex size-8 items-center justify-center rounded-lg border shadow-sm backdrop-blur-sm"
        onClick={(e) => {
          e.stopPropagation()
          toggleSelected(it.path)
        }}
      >
        <CheckSquare className={cn("size-4", checked ? "text-primary" : "text-muted-foreground")} />
      </button>
    )
  }

  function itemCard(it: LibItem, i: number) {
    const isVideo = it.kind === "video"
    return (
      <Card key={it.path} className="overflow-hidden rounded-xl pt-0 pb-0 pl-0 pr-0">
        <button
          type="button"
          className="block w-full text-left"
          onClick={() => (selectMode ? toggleSelected(it.path) : play(it))}
        >
          <div
            className={cn(
              "relative aspect-[8/5] overflow-hidden bg-gradient-to-br",
              !it.cover && COVER_GRAD[i % COVER_GRAD.length],
              selectMode && selected.has(it.path) && "ring-primary ring-2 ring-inset",
            )}
            style={it.cover ? { backgroundImage: `url(${it.cover})`, backgroundSize: "cover" } : undefined}
          >
            <Badge className="absolute top-3 left-3 bg-background/70 backdrop-blur-sm">
              {isVideo ? "Video" : "Audio"}
            </Badge>
            {selectionCheckbox(it)}
          </div>
        </button>
        <CardContent className="flex items-start justify-between gap-3 pt-4 pr-4 pb-4 pl-4">
          <div className="min-w-0">
            <h3 className="mb-1 truncate text-sm font-medium">{it.title}</h3>
            <p className="text-muted-foreground mb-1 truncate text-xs">{it.artist || "—"}</p>
            {it.duration ? <p className="text-muted-foreground pt-1 text-xs">{it.duration}</p> : null}
          </div>
          {itemMenu(it)}
        </CardContent>
      </Card>
    )
  }

  function itemRow(it: LibItem, i: number) {
    const isVideo = it.kind === "video"
    return (
      <div
        key={it.path}
        className={cn(
          "hover:bg-muted/50 flex items-center gap-3 rounded-xl px-2 py-2",
          selectMode && selected.has(it.path) && "bg-muted/40 ring-primary ring-1",
        )}
      >
        {selectMode ? (
          <button
            type="button"
            aria-label={selected.has(it.path) ? "Снять выбор" : "Выбрать"}
            className="text-muted-foreground hover:text-foreground flex size-8 shrink-0 items-center justify-center rounded-lg"
            onClick={() => toggleSelected(it.path)}
          >
            <CheckSquare
              className={cn("size-4", selected.has(it.path) ? "text-primary" : "text-muted-foreground")}
            />
          </button>
        ) : null}
        <button
          type="button"
          className="flex min-w-0 flex-1 items-center gap-3 text-left"
          onClick={() => (selectMode ? toggleSelected(it.path) : play(it))}
        >
          <div
            className={cn(
              "size-12 shrink-0 rounded-lg bg-gradient-to-br",
              !it.cover && COVER_GRAD[i % COVER_GRAD.length],
            )}
            style={
              it.cover
                ? { backgroundImage: `url(${it.cover})`, backgroundSize: "cover", backgroundPosition: "center" }
                : undefined
            }
          />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{it.title}</p>
            <p className="text-muted-foreground truncate text-xs">
              {it.artist || "—"}
              {isVideo ? " · Видео" : " · Аудио"}
            </p>
          </div>
          <span className="text-muted-foreground shrink-0 text-xs tabular-nums">{it.duration || ""}</span>
        </button>
        {itemMenu(it)}
      </div>
    )
  }

  function itemMenu(it: LibItem) {
    return (
      <DropdownMenu>
        <DropdownMenuTrigger
          aria-label="Дополнительные действия"
          className="text-muted-foreground hover:text-foreground flex size-8 shrink-0 items-center justify-center rounded-lg"
          onClick={(e) => e.stopPropagation()}
        >
          <MoreHorizontal className="size-4" />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="min-w-56">
          <DropdownMenuItem onClick={() => play(it)}>Воспроизвести</DropdownMenuItem>
          <DropdownMenuItem onClick={() => play(it, true)}>Вперемешку с этого</DropdownMenuItem>
          <DropdownMenuItem onClick={() => void openPath(it.path)}>Открыть файл</DropdownMenuItem>
          <DropdownMenuItem
            onClick={() => {
              const folder = it.path.replace(/[\\/][^\\/]+$/, "")
              void openPath(folder || it.path)
            }}
          >
            Открыть папку
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={() => {
              setAddPath(it.path)
              setAddTitle(it.title)
            }}
          >
            В плейлист…
          </DropdownMenuItem>
          {favId != null ? (
            <DropdownMenuItem onClick={() => void toggleFavorite(it.path)}>
              <Heart className="mr-2 size-3.5" />В любимое
            </DropdownMenuItem>
          ) : null}
          {activePl != null ? (
            <DropdownMenuItem onClick={() => void removeFromActive(it.path)}>
              Убрать из плейлиста
            </DropdownMenuItem>
          ) : null}
          <DropdownMenuItem
            className="text-destructive focus:text-destructive"
            onClick={() => {
              setRemovePath(it.path)
              setRemoveTitle(it.title)
            }}
          >
            Удалить из библиотеки
          </DropdownMenuItem>
          {playlists.length ? (
            <>
              <DropdownMenuSeparator />
              {playlists.slice(0, 6).map((pl) => (
                <DropdownMenuItem key={pl.id} onClick={() => void addToPlaylist(pl.id, it.path)}>
                  В «{pl.name}»
                </DropdownMenuItem>
              ))}
            </>
          ) : null}
        </DropdownMenuContent>
      </DropdownMenu>
    )
  }

  const deleteName = playlists.find((p) => p.id === deleteId)?.name

  return (
    <section className="w-full pt-8 pr-8 pb-32 pl-8">
      <div className="mb-8">
        <h1 className="mb-2 text-3xl font-semibold tracking-tight">Библиотека</h1>
        <p className="text-muted-foreground text-sm">
          Обновляется автоматически. Плейлисты и вид отображения — на этой странице.
        </p>
      </div>

      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <Tabs value={kind} onValueChange={(v) => setKind(v as typeof kind)}>
          <TabsList className="h-10 p-1">
            <TabsTrigger value="all" className="rounded-lg px-5">
              Все
            </TabsTrigger>
            <TabsTrigger value="audio" className="rounded-lg px-5">
              Аудио
            </TabsTrigger>
            <TabsTrigger value="video" className="rounded-lg px-5">
              Видео
            </TabsTrigger>
          </TabsList>
        </Tabs>
        <div className="flex flex-wrap items-center gap-2">
          <div className="border-border flex h-10 items-center rounded-lg border p-0.5">
            <button
              type="button"
              title="Плитки"
              aria-label="Плитки"
              className={cn(
                "flex size-9 items-center justify-center rounded-md",
                view === "grid" ? "bg-muted text-foreground" : "text-muted-foreground",
              )}
              onClick={() => setView("grid")}
            >
              <LayoutGrid className="size-4" />
            </button>
            <button
              type="button"
              title="Список"
              aria-label="Список"
              className={cn(
                "flex size-9 items-center justify-center rounded-md",
                view === "list" ? "bg-muted text-foreground" : "text-muted-foreground",
              )}
              onClick={() => setView("list")}
            >
              <List className="size-4" />
            </button>
          </div>
          <Select value={sort} onValueChange={(v) => v && setSort(v as typeof sort)}>
            <SelectTrigger className="h-10 w-[220px]">
              <SelectValue placeholder="Сортировка">{SORT_LABELS[sort]}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="recent">{SORT_LABELS.recent}</SelectItem>
              <SelectItem value="title">{SORT_LABELS.title}</SelectItem>
              <SelectItem value="artist">{SORT_LABELS.artist}</SelectItem>
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            className="h-10 gap-2 rounded-lg"
            onClick={() => void openPath(state?.download_dir || "")}
          >
            <Upload className="size-4" />
            Импорт
          </Button>
          <Button variant="secondary" className="h-10" disabled={scanning} onClick={() => void forceScan()}>
            {scanning ? "Скан…" : "Сканировать"}
          </Button>
          <Button
            variant={selectMode ? "default" : "outline"}
            className="h-10 gap-2 rounded-lg"
            onClick={toggleSelectMode}
          >
            <CheckSquare className="size-4" />
            {selectMode ? "Готово" : "Выбрать"}
          </Button>
          <Button
            variant="outline"
            className="h-10 gap-2 rounded-lg"
            disabled={dupBusy}
            onClick={() => void openDuplicates()}
          >
            <Copy className="size-4" />
            {dupBusy ? "…" : "Дубликаты"}
          </Button>
        </div>
      </div>

      {selected.size > 0 ? (
        <div className="bg-background/95 border-border sticky top-0 z-20 mb-4 flex flex-wrap items-center gap-2 rounded-xl border px-3 py-2 shadow-sm backdrop-blur-sm">
          <span className="text-muted-foreground mr-1 text-sm tabular-nums">Выбрано: {selected.size}</span>
          <Button
            size="sm"
            className="h-8 rounded-lg"
            onClick={() => setAddBatchPaths([...selected])}
          >
            В плейлист
          </Button>
          <Button
            size="sm"
            variant="destructive"
            className="h-8 rounded-lg"
            onClick={() => setBatchRemoveOpen(true)}
          >
            Удалить
          </Button>
          <Button
            size="sm"
            variant="secondary"
            className="h-8 rounded-lg"
            disabled={organizeBusy}
            onClick={() => void organizeSelected()}
          >
            {organizeBusy ? "…" : "По артистам"}
          </Button>
          <Button size="sm" variant="ghost" className="h-8 rounded-lg" onClick={clearSelection}>
            Снять
          </Button>
        </div>
      ) : null}

      <div className="mb-5 flex flex-wrap items-center gap-3">
        <div className="border-input bg-background relative min-w-[220px] flex-1 rounded-xl border">
          <Search className="text-muted-foreground absolute top-1/2 left-3 size-4 -translate-y-1/2" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Поиск по названию или артисту…"
            className="h-10 w-full rounded-xl bg-transparent pr-3 pl-10 text-sm outline-none"
          />
        </div>
      </div>

      <div className="mb-5 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-muted-foreground mr-1 flex items-center gap-1.5 text-sm font-medium">
            <ListMusic className="size-4" />
            Плейлисты
          </p>
          <button
            type="button"
            onClick={() => setActivePl(null)}
            className={cn(
              "rounded-full px-3.5 py-1.5 text-sm transition-colors",
              activePl == null
                ? "bg-primary text-primary-foreground"
                : "bg-muted/70 text-foreground hover:bg-muted",
            )}
          >
            Вся библиотека
          </button>
          {playlists.map((pl) => (
            <div key={pl.id} className="group relative">
              <button
                type="button"
                onClick={() => setActivePl(pl.id)}
                className={cn(
                  "max-w-[200px] truncate rounded-full px-3.5 py-1.5 text-sm transition-colors",
                  activePl === pl.id
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted/70 text-foreground hover:bg-muted",
                )}
                title={`${pl.name} · ${pl.track_count ?? 0}`}
              >
                {pl.name}
                <span
                  className={cn(
                    "ml-1.5 text-xs",
                    activePl === pl.id ? "text-primary-foreground/80" : "text-muted-foreground",
                  )}
                >
                  {pl.track_count ?? 0}
                </span>
              </button>
              <button
                type="button"
                className="bg-background text-muted-foreground hover:text-destructive absolute -top-1.5 -right-1.5 flex size-5 items-center justify-center rounded-full border text-xs opacity-0 shadow-sm group-hover:opacity-100"
                title="Удалить плейлист"
                onClick={() => setDeleteId(pl.id)}
              >
                ×
              </button>
            </div>
          ))}
          <Button variant="outline" size="sm" className="h-8 gap-1 rounded-full px-3" onClick={openCreate}>
            <Plus className="size-3.5" />
            Новый
          </Button>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            className="h-9 gap-2 rounded-lg"
            disabled={!filteredItems.length}
            onClick={() => playVisible(true)}
            title={
              activePl != null
                ? "Перемешать текущий плейлист без повторов до конца"
                : "Перемешать видимые треки библиотеки"
            }
          >
            <Shuffle className="size-3.5" />
            {activePl != null ? "Плейлист вперемешку" : "Библиотека вперемешку"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="h-9 gap-2 rounded-lg"
            disabled={!playlists.length}
            onClick={() => void playAllPlaylistsShuffled()}
            title="Все треки из всех плейлистов, без повторов путей"
          >
            <Shuffle className="size-3.5" />
            Все плейлисты вперемешку
          </Button>
          {activePlaylist ? (
            <p className="text-muted-foreground text-sm">
              «{activePlaylist.name}» · {filteredItems.length} трек(ов)
            </p>
          ) : !playlists.length ? (
            <p className="text-muted-foreground text-sm">Пока пусто — создай плейлист.</p>
          ) : null}
        </div>
      </div>

      <div>
        {view === "grid" ? (
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
            {filteredItems.map((it, i) => itemCard(it, i))}
          </div>
        ) : (
          <div className="space-y-1">{filteredItems.map((it, i) => itemRow(it, i))}</div>
        )}
        {filteredItems.length === 0 ? (
          <p className="text-muted-foreground mt-8 text-sm">
            {query.trim()
              ? "Ничего не найдено по запросу."
              : activePl != null
                ? "В плейлисте пока нет треков. Добавь через меню ⋯ у файла или кнопку в плеере."
                : "Библиотека пуста. Скачайте медиа — список обновится сам, или нажмите «Сканировать»."}
          </p>
        ) : null}
      </div>

      <AppModal
        open={createOpen}
        title="Новый плейлист"
        description="Название можно изменить позже, удалив и создав заново."
        onClose={() => !createBusy && setCreateOpen(false)}
        footer={
          <>
            <Button variant="ghost" disabled={createBusy} onClick={() => setCreateOpen(false)}>
              Отмена
            </Button>
            <Button disabled={createBusy || !createName.trim()} onClick={() => void submitCreate()}>
              Создать
            </Button>
          </>
        }
      >
        <label className="text-muted-foreground mb-1.5 block text-sm">Название плейлиста</label>
        <input
          value={createName}
          onChange={(e) => setCreateName(e.target.value)}
          className="border-input bg-background focus:ring-primary/30 h-10 w-full rounded-xl border px-3 text-sm outline-none focus:ring-2"
          autoFocus
          onKeyDown={(e) => {
            if (e.key === "Enter") void submitCreate()
          }}
        />
      </AppModal>

      <AppModal
        open={deleteId != null}
        title="Удалить плейлист?"
        description={
          deleteName
            ? `«${deleteName}» будет удалён. Треки в библиотеке останутся.`
            : "Плейлист будет удалён. Треки в библиотеке останутся."
        }
        onClose={() => !deleteBusy && setDeleteId(null)}
        footer={
          <>
            <Button variant="ghost" disabled={deleteBusy} onClick={() => setDeleteId(null)}>
              Отмена
            </Button>
            <Button variant="destructive" disabled={deleteBusy} onClick={() => void confirmDelete()}>
              Удалить
            </Button>
          </>
        }
      >
        <p className="text-muted-foreground text-sm">Это действие нельзя отменить.</p>
      </AppModal>

      <AppModal
        open={Boolean(removePath)}
        title="Удалить из библиотеки?"
        description={
          removeTitle
            ? `«${removeTitle}» будет удалён с диска и из всех плейлистов.`
            : "Файл будет удалён с диска и из всех плейлистов."
        }
        onClose={() => !removeBusy && setRemovePath(null)}
        footer={
          <>
            <Button variant="ghost" disabled={removeBusy} onClick={() => setRemovePath(null)}>
              Отмена
            </Button>
            <Button variant="destructive" disabled={removeBusy} onClick={() => void confirmRemoveFile()}>
              Удалить
            </Button>
          </>
        }
      >
        <p className="text-muted-foreground text-sm">Действие нельзя отменить.</p>
      </AppModal>

      <AppModal
        open={batchRemoveOpen}
        title="Удалить выбранные?"
        description={`Будет удалено файлов: ${selected.size}. Они исчезнут с диска и из всех плейлистов.`}
        onClose={() => !batchRemoveBusy && setBatchRemoveOpen(false)}
        footer={
          <>
            <Button variant="ghost" disabled={batchRemoveBusy} onClick={() => setBatchRemoveOpen(false)}>
              Отмена
            </Button>
            <Button variant="destructive" disabled={batchRemoveBusy} onClick={() => void confirmBatchRemove()}>
              Удалить
            </Button>
          </>
        }
      >
        <p className="text-muted-foreground text-sm">Действие нельзя отменить.</p>
      </AppModal>

      <AppModal
        open={dupOpen}
        title="Дубликаты"
        description="Группы с одинаковыми названием и исполнителем."
        onClose={() => !dupBusy && setDupOpen(false)}
        footer={
          <Button variant="ghost" onClick={() => setDupOpen(false)}>
            Закрыть
          </Button>
        }
        className="max-w-2xl"
      >
        {dupGroups.length === 0 ? (
          <p className="text-muted-foreground text-sm">Дубликатов не найдено.</p>
        ) : (
          <div className="max-h-[min(60vh,28rem)] space-y-4 overflow-y-auto pr-1">
            {dupGroups.map((g) => (
              <div key={g.key} className="border-border rounded-xl border p-3">
                <p className="mb-2 text-sm font-medium">
                  {g.key}{" "}
                  <span className="text-muted-foreground font-normal">· {g.count}</span>
                </p>
                <ul className="space-y-2">
                  {g.items.map((it) => (
                    <li
                      key={it.path}
                      className="bg-muted/40 flex flex-wrap items-center justify-between gap-2 rounded-lg px-2 py-1.5 text-sm"
                    >
                      <span className="min-w-0 flex-1 truncate" title={it.path}>
                        {it.title || it.path}
                      </span>
                      <div className="flex shrink-0 gap-1">
                        <Button
                          size="sm"
                          variant="outline"
                          className="h-7 rounded-lg px-2 text-xs"
                          onClick={() => {
                            const folder = it.path.replace(/[\\/][^\\/]+$/, "")
                            void openPath(folder || it.path)
                          }}
                        >
                          Папка
                        </Button>
                        <Button
                          size="sm"
                          variant="destructive"
                          className="h-7 rounded-lg px-2 text-xs"
                          onClick={() => void removeDupItem(it)}
                        >
                          Удалить
                        </Button>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
      </AppModal>

      <AddToPlaylistsModal
        open={Boolean(addPath) || Boolean(addBatchPaths?.length)}
        path={addPath}
        paths={addBatchPaths ?? undefined}
        trackTitle={addTitle}
        onClose={() => {
          setAddPath(null)
          setAddTitle(undefined)
          setAddBatchPaths(null)
        }}
        onSaved={() => {
          void loadPlaylists()
          if (activePl != null) void load()
        }}
      />
    </section>
  )
}
