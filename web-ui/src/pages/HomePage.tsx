import {
  Download,
  Link,
  Mic2,
  MoreHorizontal,
  Search,
  Star,
} from "lucide-react"
import { useCallback, useDeferredValue, useEffect, useEffectEvent, useMemo, useState } from "react"
import { InlineVideoPlayer } from "@/components/media/InlineVideoPlayer"
import { ShazamResultCard } from "@/components/shazam/ShazamResultCard"
import { HistoryThumb } from "@/components/history/HistoryThumb"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { useApp } from "@/context/AppProvider"
import {
  cancelJob,
  deleteHistory,
  getClipboard,
  openPath,
  openUrl,
  patchHistory,
  postJob,
  fetchState,
  previewUrl,
  uploadShazam,
} from "@/lib/api"
import { playerTrackFromHistory } from "@/lib/media"
import { PLATFORM_PILLS } from "@/lib/platforms"
import type { HistoryItem, PreviewQuality } from "@/types"
import { cn } from "@/lib/utils"

const DEFAULT_QUALITIES: PreviewQuality[] = [
  { value: "2160", label: "2160p" },
  { value: "1440", label: "1440p" },
  { value: "1080", label: "1080p" },
  { value: "720", label: "720p" },
  { value: "480", label: "480p" },
  { value: "360", label: "360p" },
]

function firstUrl(raw: string): string {
  const parts = raw
    .replace(/\r/g, "\n")
    .split("\n")
    .map((p) => p.trim())
    .filter(Boolean)
  const http = parts.filter((p) => /^https?:\/\//i.test(p))
  return http[0] || parts[0] || ""
}

function fmtClipTime(sec: number) {
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${m}:${String(s).padStart(2, "0")}`
}

function historyMeta(it: HistoryItem): string {
  const plat = it.platform_name || it.platform || "—"
  const fmtUp = (it.format || "").toUpperCase()
  const audio =
    fmtUp === "MP3" ||
    fmtUp === "M4A" ||
    fmtUp === "FLAC" ||
    fmtUp === "OPUS" ||
    /\.(mp3|m4a|flac|opus|wav|ogg|aac)$/i.test(it.dest || "")
  const kind = audio ? "Аудио" : "Видео"
  const mid = audio
    ? fmtUp || "MP3"
    : it.quality
      ? String(it.quality).endsWith("p")
        ? it.quality
        : `${it.quality}p`
      : ""
  const dur = it.duration || ""
  return [plat, kind, mid, dur].filter(Boolean).join(" · ")
}

export function HomePage() {
  const { state, refresh, historySearchRef, playWithQueue } = useApp()
  const [url, setUrl] = useState("")
  const [platform, setPlatform] = useState("youtube")
  const [quality, setQuality] = useState("1080")
  const [qualities, setQualities] = useState<PreviewQuality[]>(DEFAULT_QUALITIES)
  const [fmt, setFmt] = useState("MP4")
  const [clip, setClip] = useState(false)
  const [clipStart, setClipStart] = useState("")
  const [clipEnd, setClipEnd] = useState("")
  const [audioOnly, setAudioOnly] = useState(false)
  const [favOnly, setFavOnly] = useState(false)
  const [histQ, setHistQ] = useState("")
  const [previewTitle, setPreviewTitle] = useState("")
  const [previewThumb, setPreviewThumb] = useState("")
  const [previewMeta, setPreviewMeta] = useState("")
  const [previewError, setPreviewError] = useState("")
  const [localVideo, setLocalVideo] = useState<string | null>(null)
  const [clipPos, setClipPos] = useState(0)

  const shazam = state?.last?.shazam

  const runPreview = useCallback(async (raw: string) => {
    const u = firstUrl(raw)
    if (!u) {
      setPreviewTitle("")
      setPreviewThumb("")
      setPreviewMeta("")
      setPreviewError("")
      return
    }
    try {
      const j = await previewUrl(u)
      if (!j.ok) {
        setPreviewTitle(j.platform_name || j.platform || "")
        setPreviewThumb("")
        setPreviewMeta("")
        setPreviewError(j.error || "Не удалось загрузить превью")
        return
      }
      setPreviewError("")
      if (j.platform) setPlatform(j.platform)
      setPreviewTitle(j.title || j.platform_name || "")
      setPreviewThumb(j.thumb || "")
      const meta = [j.uploader, j.duration].filter(Boolean).join(" · ")
      setPreviewMeta(meta)
      const qs = j.qualities || []
      if (qs.length) {
        setQualities(qs)
        const first = qs[0]?.value
        if (first) setQuality(first === "best" ? "best" : first.replace(/\D/g, "") || first)
      }
    } catch (e) {
      setPreviewError(String(e))
    }
  }, [])

  useEffect(() => {
    const u = firstUrl(url)
    if (!u) return
    const t = window.setTimeout(() => void runPreview(url), 450)
    return () => clearTimeout(t)
  }, [url, runPreview])

  const onDrop = useEffectEvent((ev: Event) => {
    const { files, text } = (ev as CustomEvent<{ files: File[]; text: string }>).detail
    if (text?.trim()) {
      const urls = text.match(/https?:\/\/[^\s<>"']+/gi)
      if (urls?.length) {
        setUrl((prev) => {
          const merged = [...(prev.trim() ? prev.trim().split("\n") : []), ...urls].join("\n")
          return merged
        })
        void runPreview(urls[0]!)
      }
    }
    const file = files?.[0]
    if (!file) return
    if (/^video\//i.test(file.type) || /\.(mp4|webm|mkv|mov|avi)$/i.test(file.name)) {
      setLocalVideo((prev) => {
        if (prev) URL.revokeObjectURL(prev)
        return URL.createObjectURL(file)
      })
      setClip(true)
    }
  })

  useEffect(() => {
    window.addEventListener("media-app-drop", onDrop)
    return () => window.removeEventListener("media-app-drop", onDrop)
  }, [])

  const deferredHistQ = useDeferredValue(histQ)
  const history = useMemo(() => {
    let list = state?.history ?? []
    if (platform) {
      list = list.filter((h) => (h.platform || "").toLowerCase() === platform.toLowerCase())
    }
    if (favOnly) list = list.filter((h) => h.favorite)
    if (deferredHistQ.trim()) {
      const q = deferredHistQ.toLowerCase()
      list = list.filter(
        (h) =>
          h.title.toLowerCase().includes(q) ||
          h.url.toLowerCase().includes(q) ||
          (h.platform_name || "").toLowerCase().includes(q),
      )
    }
    return list
  }, [state?.history, platform, favOnly, deferredHistQ])
  const deferredHistory = useDeferredValue(history)

  async function download() {
    const raw = url.trim()
    if (!raw) return
    const audio = audioOnly || fmt.toUpperCase() === "MP3"
    await postJob({
      url: raw,
      kind: audio ? "audio" : "video",
      quality,
      fmt,
      start: clip ? clipStart : "",
      end: clip ? clipEnd : "",
    })
    void refresh()
  }

  async function recognizeMusic() {
    const u = firstUrl(url)
    if (!u) return
    await postJob({
      url: u,
      kind: "shazam",
      quality,
      fmt,
      start: clip ? clipStart : "",
      end: clip ? clipEnd : "",
    })
    for (let i = 0; i < 120; i++) {
      await new Promise((r) => setTimeout(r, 400))
      const s = await fetchState()
      void refresh()
      if (s.last?.shazam?.track || s.last?.error) break
      if (!s.busy && i > 2) break
    }
  }

  async function pasteFromClipboard() {
    const j = await getClipboard()
    const text = j.text?.trim()
    if (!text) return
    setUrl((prev) => (prev.trim() ? `${prev.trim()}\n${text}` : text))
  }

  async function toggleFav(it: HistoryItem) {
    await patchHistory(it.id, { favorite: !it.favorite })
    void refresh()
  }

  function playItem(it: HistoryItem) {
    if (!it.dest) return
    const playable = (state?.history ?? []).filter((h) => h.dest)
    const tracks = playable.map((h) => playerTrackFromHistory(h))
    const idx = playable.findIndex((h) => h.id === it.id)
    playWithQueue(tracks, idx >= 0 ? idx : 0)
  }

  const qualityOptions =
    qualities.length > 0
      ? qualities
      : DEFAULT_QUALITIES.map((q) => ({ value: q.value, label: q.label }))

  return (
    <div className="w-full pt-8 pr-8 pb-32 pl-8">
      <div className="mb-8">
        <h1 className="mb-2 text-3xl font-semibold tracking-tight">Скачивайте медиа без лишнего</h1>
        <p className="text-muted-foreground max-w-2xl text-base">
          Вставьте одну или несколько ссылок (каждая с новой строки) — видео, плейлист или аудио.
        </p>
      </div>

      <Card className="border-border bg-card mb-4 gap-0 rounded-2xl border pt-4 pr-4 pb-4 pl-4 shadow-sm">
        <div className="flex items-start gap-3">
          <Link className="text-muted-foreground mt-2.5 size-5 shrink-0" />
          <textarea
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onBlur={() => url.trim() && void runPreview(url)}
            placeholder={"Вставьте ссылку на видео, плейлист или аудио\nНесколько URL — по одному на строку"}
            rows={url.includes("\n") ? 4 : 2}
            className="placeholder:text-muted-foreground min-h-[44px] flex-1 resize-y border-0 bg-transparent text-sm outline-none"
          />
          <Button className="mt-0.5 h-11 shrink-0 gap-2 rounded-xl pr-5 pl-5" onClick={() => void download()}>
            <Download className="size-4" />
            Скачать
          </Button>
        </div>
      </Card>

      {previewTitle || previewThumb || previewError ? (
        <Card className="border-border bg-card mb-4 flex gap-4 rounded-2xl border p-4 shadow-sm">
          {previewThumb ? (
            <img src={previewThumb} alt="" className="size-20 rounded-lg object-cover" />
          ) : null}
          <div>
            <p className="text-sm font-medium">{previewTitle || "Превью"}</p>
            {previewMeta ? <p className="text-muted-foreground text-xs">{previewMeta}</p> : null}
            {previewError ? (
              <p className="text-destructive text-xs">{previewError}</p>
            ) : (
              <p className="text-muted-foreground text-xs">Проверьте ссылку перед скачиванием</p>
            )}
          </div>
        </Card>
      ) : null}

      {localVideo ? (
        <Card className="border-border bg-card mb-4 space-y-3 rounded-2xl border p-4 shadow-sm">
          <p className="text-sm font-medium">Локальное видео — выберите отрезок для Shazam</p>
          <InlineVideoPlayer
            src={localVideo}
            className="bg-black max-h-64 w-full rounded-lg"
            onTimeUpdate={(cur) => setClipPos(cur)}
          />
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => setClipStart(fmtClipTime(clipPos))}
            >
              Начало = текущий кадр
            </Button>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => setClipEnd(fmtClipTime(clipPos))}
            >
              Конец = текущий кадр
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => {
                void fetch(localVideo)
                  .then((r) => r.blob())
                  .then((b) => uploadShazam(new File([b], "clip.mp4", { type: b.type })))
                  .then(() => void refresh())
              }}
            >
              Shazam этого файла
            </Button>
          </div>
        </Card>
      ) : null}

      <div className="mb-6 flex flex-wrap items-center gap-2">
        <Button variant="outline" size="sm" className="gap-2 rounded-full" onClick={() => void recognizeMusic()}>
          <Mic2 className="size-4" />
          Узнать музыку в ролике
        </Button>
        <span className="text-muted-foreground text-xs">Shazam по ссылке; для отрывка включите «Клип» и укажите время</span>
      </div>

      {shazam?.track ? <ShazamResultCard result={shazam} onDownloaded={() => void refresh()} /> : null}

      <div className="mb-8 flex flex-wrap items-center gap-2">
        {PLATFORM_PILLS.map((p) => (
          <button
            key={p.id}
            type="button"
            onClick={() => setPlatform(p.id)}
            className={cn(
              "rounded-full pt-2 pr-4 pb-2 pl-4 text-sm font-medium transition-colors",
              platform === p.id
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground hover:text-foreground",
            )}
          >
            {p.label}
          </button>
        ))}
      </div>

      <div className="border-border mb-8 flex flex-wrap items-center gap-6 border-b pb-6">
        <Select value={quality} onValueChange={(v) => v && setQuality(v)}>
          <SelectTrigger className="h-9 min-w-[14rem] max-w-[min(100%,28rem)]" aria-label="Качество">
            <SelectValue>
              {(v) => {
                const q = qualityOptions.find((x) => x.value === String(v))
                return q ? `Качество: ${q.label}` : `Качество: ${String(v)}`
              }}
            </SelectValue>
          </SelectTrigger>
          <SelectContent className="bg-popover text-popover-foreground">
            {qualityOptions.map((q) => (
              <SelectItem key={q.value} value={q.value}>
                Качество: {q.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={fmt} onValueChange={(v) => v && setFmt(v)}>
          <SelectTrigger className="h-9 w-[9.5rem]" aria-label="Формат">
            <SelectValue>{(v) => `Формат: ${String(v)}`}</SelectValue>
          </SelectTrigger>
          <SelectContent className="bg-popover text-popover-foreground">
            {["MP4", "WEBM", "MKV", "MOV", "AVI", "MP3"].map((f) => (
              <SelectItem key={f} value={f}>
                Формат: {f}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="text-muted-foreground flex items-center gap-2 text-sm">
          <Switch checked={clip} onCheckedChange={setClip} id="clip" />
          <label htmlFor="clip">Клип</label>
        </div>
        {clip ? (
          <div className="flex items-center gap-2">
            <Input
              value={clipStart}
              onChange={(e) => setClipStart(e.target.value)}
              placeholder="0:00"
              className="h-9 w-20 text-sm"
            />
            <span className="text-muted-foreground text-sm">—</span>
            <Input
              value={clipEnd}
              onChange={(e) => setClipEnd(e.target.value)}
              placeholder="конец"
              className="h-9 w-20 text-sm"
            />
          </div>
        ) : null}
        <div className="text-muted-foreground flex items-center gap-2 text-sm">
          <Switch checked={audioOnly} onCheckedChange={setAudioOnly} id="audio-only" />
          <label htmlFor="audio-only">Только аудио</label>
        </div>
        <Button variant="ghost" size="sm" className="text-destructive" onClick={() => void cancelJob()}>
          Отмена
        </Button>
        <Button variant="ghost" size="sm" onClick={() => void pasteFromClipboard()}>
          Вставить
        </Button>
      </div>

      <div className="mb-8 flex flex-wrap items-center justify-between gap-4">
        <h2 className="text-xl font-semibold">История загрузок</h2>
        <div className="flex flex-wrap items-center gap-3">
          <div className="border-input bg-card flex h-10 w-64 items-center gap-2 rounded-lg border pr-3 pl-3">
            <Search className="text-muted-foreground size-4 shrink-0" />
            <Input
              ref={historySearchRef}
              value={histQ}
              onChange={(e) => setHistQ(e.target.value)}
              placeholder="Поиск по истории"
              className="h-8 border-0 bg-transparent p-0 text-sm shadow-none focus-visible:ring-0"
            />
          </div>
          <label className="border-border text-muted-foreground flex h-10 cursor-pointer items-center gap-2 rounded-lg border pr-3 pl-3 text-sm">
            <Star className="size-4" />
            <span>Только избранное</span>
            <Switch checked={favOnly} onCheckedChange={setFavOnly} />
          </label>
        </div>
      </div>

      <Card className="border-border bg-card overflow-hidden rounded-2xl border pt-0 pr-0 pb-0 pl-0 shadow-sm">
        {deferredHistory.length === 0 ? (
          <p className="text-muted-foreground py-16 text-center text-sm">
            {favOnly || histQ.trim()
              ? "Ничего не найдено"
              : `Нет загрузок для ${PLATFORM_PILLS.find((p) => p.id === platform)?.label || platform}`}
          </p>
        ) : (
          deferredHistory.map((it, i) => (
            <div
              key={it.id}
              className="border-border flex items-center gap-4 border-b pt-4 pr-5 pb-4 pl-5 last:border-b-0"
            >
              <HistoryThumb index={i} thumb={it.thumb} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{it.title}</p>
                <p className="text-muted-foreground mt-1 text-xs">{historyMeta(it)}</p>
              </div>
              <span className="shrink-0 text-sm text-emerald-400">{it.status || "Готово"}</span>
              <button
                type="button"
                aria-label="Избранное"
                onClick={() => void toggleFav(it)}
                className="text-muted-foreground hover:text-foreground shrink-0"
              >
                <Star className={cn("size-4", it.favorite && "fill-primary text-primary")} />
              </button>
              <DropdownMenu>
                <DropdownMenuTrigger
                  aria-label="Дополнительные действия"
                  className="text-muted-foreground flex size-8 shrink-0 items-center justify-center rounded-lg"
                >
                  <MoreHorizontal className="size-4" />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  {it.dest ? (
                    <DropdownMenuItem onClick={() => playItem(it)}>Воспроизвести</DropdownMenuItem>
                  ) : null}
                  {it.dest ? (
                    <DropdownMenuItem onClick={() => void openPath(it.dest)}>Открыть файл</DropdownMenuItem>
                  ) : null}
                  <DropdownMenuItem onClick={() => void openUrl(it.url)}>Открыть ссылку</DropdownMenuItem>
                  <DropdownMenuItem
                    className="text-destructive"
                    onClick={() => {
                      void deleteHistory(it.id).then(() => refresh())
                    }}
                  >
                    Удалить из истории
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          ))
        )}
      </Card>
    </div>
  )
}
