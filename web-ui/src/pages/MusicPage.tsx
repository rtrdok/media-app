import { Download, Heart, Link2, ListMusic, Mic2, Pause, Play, RefreshCw, Upload } from "lucide-react"
import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { ShazamResultCard } from "@/components/shazam/ShazamResultCard"
import { useApp } from "@/context/AppProvider"
import {
  fetchState,
  prepareMusicPreview,
  postJob,
  uploadShazam,
  vkDownload,
  vkPlaylistTracks,
  vkPlaylists,
  vkStatus,
  yandexDownload,
  yandexPlaylistTracks,
  yandexPlaylists,
  yandexStatus,
  type YandexPlaylist,
  type YandexTrack,
} from "@/lib/api"
import { cn } from "@/lib/utils"

type MusicSource = "yandex" | "vk"

const SOURCE_DEFAULTS: Record<
  MusicSource,
  { kind: string; uid: string; title: string; cookieHint: string }
> = {
  yandex: {
    kind: "likes",
    uid: "",
    title: "Мне нравится",
    cookieHint: "Нужны cookies music.yandex.ru — отправь через расширение",
  },
  vk: {
    kind: "my",
    uid: "",
    title: "Моя музыка",
    cookieHint: "Нужны cookies vk.ru (обычный ВК, не music.vk.com) — отправь через расширение",
  },
}

export function MusicPage() {
  const { state, refresh, setPage, setPlayer, setPlaying, player, playing } = useApp()
  const inputRef = useRef<HTMLInputElement>(null)
  const [tab, setTab] = useState<"shazam" | MusicSource>("yandex")
  const [url, setUrl] = useState("")
  const [result, setResult] = useState("")
  const [loading, setLoading] = useState(false)
  const [previewId, setPreviewId] = useState<string | null>(null)
  const [previewErr, setPreviewErr] = useState("")

  const [login, setLogin] = useState("")
  const [libError, setLibError] = useState("")
  const [playlists, setPlaylists] = useState<YandexPlaylist[]>([])
  const [activeKind, setActiveKind] = useState(SOURCE_DEFAULTS.yandex.kind)
  const [activeUid, setActiveUid] = useState(SOURCE_DEFAULTS.yandex.uid)
  const [activeAccessHash, setActiveAccessHash] = useState("")
  const [playlistTitle, setPlaylistTitle] = useState(SOURCE_DEFAULTS.yandex.title)
  const [tracks, setTracks] = useState<YandexTrack[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [libLoading, setLibLoading] = useState(false)
  const [libMsg, setLibMsg] = useState("")

  const shazam = state?.last?.shazam
  const source: MusicSource | null = tab === "shazam" ? null : tab

  const loadPlaylists = useCallback(async (src: MusicSource) => {
    setLibLoading(true)
    setLibError("")
    try {
      const st = src === "vk" ? await vkStatus() : await yandexStatus()
      if (!st.ok) {
        setLogin("")
        setLibError(st.error || SOURCE_DEFAULTS[src].cookieHint)
        setPlaylists([])
        return
      }
      setLogin(st.login || "аккаунт")
      const pl = src === "vk" ? await vkPlaylists() : await yandexPlaylists()
      if (!pl.ok) {
        setLibError(pl.error || "Не удалось загрузить плейлисты")
        setPlaylists([])
        return
      }
      setPlaylists(pl.items || [])
    } catch (e) {
      setLibError(String(e))
    } finally {
      setLibLoading(false)
    }
  }, [])

  const loadTracks = useCallback(async (src: MusicSource, kind: string, uid: string, titleHint?: string, accessHash = "") => {
    setLibLoading(true)
    setLibError("")
    setSelected(new Set())
    try {
      const j =
        src === "vk"
          ? await vkPlaylistTracks(kind, uid, accessHash)
          : await yandexPlaylistTracks(kind, uid)
      if (!j.ok) {
        setLibError(j.error || "Не удалось загрузить треки")
        setTracks([])
        return
      }
      setPlaylistTitle(titleHint || j.title || kind)
      setTracks(j.tracks || [])
    } catch (e) {
      setLibError(String(e))
      setTracks([])
    } finally {
      setLibLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!source) return
    const d = SOURCE_DEFAULTS[source]
    setActiveKind(d.kind)
    setActiveUid(d.uid)
    setActiveAccessHash("")
    setPlaylistTitle(d.title)
    setTracks([])
    setPlaylists([])
    setLogin("")
    setLibMsg("")
    setLibError("")
    void loadPlaylists(source).then(() => loadTracks(source, d.kind, d.uid, d.title))
  }, [source, loadPlaylists, loadTracks])

  async function openPlaylist(pl: YandexPlaylist) {
    if (!source) return
    setActiveKind(pl.kind)
    setActiveUid(pl.uid)
    setActiveAccessHash(pl.access_hash || "")
    await loadTracks(source, pl.kind, pl.uid, pl.title, pl.access_hash || "")
  }

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function selectAll() {
    setSelected(new Set(tracks.map((t) => t.id)))
  }

  function clearSel() {
    setSelected(new Set())
  }

  const selectedUrls = useMemo(
    () => tracks.filter((t) => selected.has(t.id)).map((t) => t.url),
    [tracks, selected],
  )

  async function downloadSelected() {
    if (!selectedUrls.length || !source) return
    setLibMsg("")
    setLibLoading(true)
    try {
      const j = source === "vk" ? await vkDownload(selectedUrls) : await yandexDownload(selectedUrls)
      if (!j.ok) {
        setLibMsg(j.error || "Ошибка постановки в очередь")
        return
      }
      setLibMsg(`В очередь: ${j.count} трек(ов)`)
      void refresh(true)
      setPage("downloads")
    } catch (e) {
      setLibMsg(String(e))
    } finally {
      setLibLoading(false)
    }
  }

  async function previewTrack(t: YandexTrack) {
    setPreviewErr("")
    // повторный клик по тому же треку — пауза/продолжить
    if (player?.title === t.title && player?.artist === (t.artist || "") && player?.src) {
      if (playing) {
        setPlaying(false)
        return
      }
      if (player.src.startsWith("/api/file?")) {
        setPlaying(true)
        return
      }
    }
    setPreviewId(t.id)
    try {
      const j = await prepareMusicPreview(t.url)
      if (!j.ok || !j.stream) {
        setPreviewErr(j.error || "Не удалось открыть превью")
        return
      }
      setPlayer({
        title: j.title || t.title,
        artist: j.artist || t.artist || "",
        src: j.stream,
        durationLabel: t.duration_label || undefined,
        kind: "audio",
        thumb: j.cover || t.cover || undefined,
      })
      setPlaying(true)
    } catch (e) {
      setPreviewErr(String(e))
    } finally {
      setPreviewId(null)
    }
  }

  async function onFile(file: File) {
    setLoading(true)
    setResult("")
    try {
      const j = await uploadShazam(file)
      if (j.ok) setResult(`${j.artist ?? "?"} — ${j.title ?? "?"}`)
      else setResult(j.error || "Не распознано")
    } catch (e) {
      setResult(String(e))
    } finally {
      setLoading(false)
    }
  }

  async function onUrlShazam() {
    const u = url.trim()
    if (!u) return
    setLoading(true)
    setResult("")
    try {
      await postJob({ url: u, kind: "shazam", quality: "720", fmt: "MP3", start: "", end: "" })
      for (let i = 0; i < 80; i++) {
        await new Promise((r) => setTimeout(r, 400))
        const s = await fetchState()
        void refresh()
        const t = s.last?.shazam?.track
        if (t || s.last?.error) {
          setResult(t || s.last.error || "Трек не найден")
          break
        }
        if (!s.busy && i > 2) break
      }
    } catch (e) {
      setResult(String(e))
    } finally {
      setLoading(false)
    }
  }

  const display =
    result ||
    (shazam?.track ? `${shazam.artist ? `${shazam.artist} — ` : ""}${shazam.track}` : "")

  return (
    <div className="w-full pt-8 pr-8 pb-32 pl-8">
      <div className="mb-6">
        <h1 className="mb-2 text-3xl font-semibold tracking-tight">Музыка</h1>
        <p className="text-muted-foreground text-sm">
          Яндекс Музыка, аудио из ВКонтакте (vk.ru) и Shazam: плейлисты, прослушивание и скачивание.
        </p>
      </div>

      <Tabs
        value={tab}
        onValueChange={(v) => setTab(v as "shazam" | MusicSource)}
        className="mb-6"
      >
        <TabsList className="h-10 p-1">
          <TabsTrigger value="yandex" className="rounded-lg px-5">
            Яндекс Музыка
          </TabsTrigger>
          <TabsTrigger value="vk" className="rounded-lg px-5">
            ВКонтакте
          </TabsTrigger>
          <TabsTrigger value="shazam" className="rounded-lg px-5">
            Shazam
          </TabsTrigger>
        </TabsList>
      </Tabs>

      {source ? (
        <div className="space-y-4">
          <Card className="rounded-2xl">
            <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3 space-y-0">
              <div>
                <CardTitle className="text-lg">Аккаунт</CardTitle>
                <p className="text-muted-foreground mt-1 text-sm">
                  {login ? `Вошли как ${login}` : SOURCE_DEFAULTS[source].cookieHint}
                </p>
              </div>
              <Button
                variant="secondary"
                className="gap-2"
                disabled={libLoading}
                onClick={() =>
                  void loadPlaylists(source).then(() =>
                    loadTracks(source, activeKind, activeUid, playlistTitle, activeAccessHash),
                  )
                }
              >
                <RefreshCw className={cn("size-4", libLoading && "animate-spin")} />
                Обновить
              </Button>
            </CardHeader>
            {libError ? (
              <CardContent>
                <p className="text-destructive text-sm">{libError}</p>
              </CardContent>
            ) : null}
          </Card>

          <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
            <Card className="rounded-2xl">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <ListMusic className="size-4" />
                  Плейлисты
                </CardTitle>
              </CardHeader>
              <CardContent className="max-h-[520px] space-y-1 overflow-y-auto p-3 pt-0">
                {playlists.length === 0 ? (
                  <p className="text-muted-foreground px-2 text-sm">Список пуст</p>
                ) : (
                  playlists.map((pl) => (
                    <button
                      key={pl.id}
                      type="button"
                      onClick={() => void openPlaylist(pl)}
                      className={cn(
                        "hover:bg-muted/60 flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm",
                        activeKind === pl.kind && activeUid === pl.uid && "bg-muted",
                      )}
                    >
                      {pl.is_likes ? <Heart className="text-primary size-4 shrink-0" /> : null}
                      <span className="min-w-0 flex-1 truncate font-medium">{pl.title}</span>
                      {pl.track_count != null ? (
                        <span className="text-muted-foreground shrink-0 text-xs">{pl.track_count}</span>
                      ) : null}
                    </button>
                  ))
                )}
              </CardContent>
            </Card>

            <Card className="rounded-2xl">
              <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-3 space-y-0">
                <div>
                  <CardTitle className="text-lg">{playlistTitle}</CardTitle>
                  <p className="text-muted-foreground mt-1 text-sm">
                    {tracks.length} трек(ов)
                    {selected.size ? ` · выбрано ${selected.size}` : ""}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button variant="outline" size="sm" onClick={selectAll} disabled={!tracks.length}>
                    Все
                  </Button>
                  <Button variant="ghost" size="sm" onClick={clearSel} disabled={!selected.size}>
                    Снять
                  </Button>
                  <Button
                    size="sm"
                    className="gap-2"
                    disabled={!selectedUrls.length || libLoading}
                    onClick={() => void downloadSelected()}
                  >
                    <Download className="size-4" />
                    Скачать выбранные
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="max-h-[520px] space-y-1 overflow-y-auto pt-0">
                {libMsg ? <p className="text-muted-foreground mb-2 text-sm">{libMsg}</p> : null}
                {previewErr ? <p className="text-destructive mb-2 text-sm">{previewErr}</p> : null}
                {libLoading && !tracks.length ? (
                  <p className="text-muted-foreground text-sm">Загрузка…</p>
                ) : null}
                {tracks.map((t) => {
                  const isThis =
                    Boolean(player?.src) &&
                    player?.title === t.title &&
                    (player?.artist || "") === (t.artist || "")
                  const isPlayingThis = Boolean(isThis && playing)
                  const preparing = previewId === t.id
                  return (
                    <div
                      key={t.id}
                      className="hover:bg-muted/50 flex items-center gap-2 rounded-lg px-2 py-2"
                    >
                      <input
                        type="checkbox"
                        className="accent-primary size-4 shrink-0"
                        checked={selected.has(t.id)}
                        onChange={() => toggle(t.id)}
                        aria-label={`Выбрать ${t.title}`}
                      />
                      <button
                        type="button"
                        aria-label={isPlayingThis ? "Пауза" : "Слушать"}
                        title={preparing ? "Готовим превью…" : "Прослушать до скачивания"}
                        disabled={preparing}
                        onClick={() => void previewTrack(t)}
                        className={cn(
                          "flex size-9 shrink-0 items-center justify-center rounded-full",
                          isPlayingThis
                            ? "bg-primary text-primary-foreground"
                            : "bg-muted text-foreground hover:bg-muted/80",
                          preparing && "opacity-60",
                        )}
                      >
                        {isPlayingThis ? <Pause className="size-3.5" /> : <Play className="size-3.5" />}
                      </button>
                      {t.cover ? (
                        <img src={t.cover} alt="" className="bg-muted size-10 rounded object-cover" />
                      ) : (
                        <div className="bg-muted size-10 shrink-0 rounded" />
                      )}
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium">{t.title}</p>
                        <p className="text-muted-foreground truncate text-xs">
                          {t.artist}
                          {t.album ? ` · ${t.album}` : ""}
                        </p>
                      </div>
                      <span className="text-muted-foreground shrink-0 text-xs tabular-nums">
                        {t.duration_label || ""}
                      </span>
                    </div>
                  )
                })}
              </CardContent>
            </Card>
          </div>
        </div>
      ) : (
        <>
          <Card className="mb-6 rounded-2xl">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Link2 className="text-primary size-5" />
                По ссылке на видео
              </CardTitle>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-3">
              <Input
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="https://…"
                className="max-w-md flex-1"
              />
              <Button className="gap-2" disabled={loading} onClick={() => void onUrlShazam()}>
                <Mic2 className="size-4" />
                Распознать
              </Button>
            </CardContent>
          </Card>

          <Card className="rounded-2xl">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <Mic2 className="text-primary size-5" />
                По файлу
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <input
                ref={inputRef}
                type="file"
                accept="audio/*,video/*"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  if (f) void onFile(f)
                }}
              />
              <Button className="gap-2" onClick={() => inputRef.current?.click()} disabled={loading}>
                <Upload className="size-4" />
                {loading ? "Распознаю…" : "Выбрать файл"}
              </Button>
              {display && !shazam?.track ? (
                <p className="text-foreground text-sm font-medium">{display}</p>
              ) : null}
              {shazam?.track ? <ShazamResultCard result={shazam} onDownloaded={() => void refresh()} /> : null}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}
