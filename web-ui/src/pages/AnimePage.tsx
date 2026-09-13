import { useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { openUrl, uploadAnime } from "@/lib/api"
import type { AnimeCandidate } from "@/types"
import { cn } from "@/lib/utils"

type AnimeResponse = {
  ok?: boolean
  text?: string
  error?: string
  meta?: Record<string, unknown>
  candidates?: AnimeCandidate[]
}

function candidateImage(c: AnimeCandidate): string | undefined {
  if (c.thumb) return c.thumb
  const p = c.preview_url || c.video_url
  if (p && /^https?:\/\//i.test(p)) return p
  return undefined
}

export function AnimePage() {
  const inputRef = useRef<HTMLInputElement>(null)
  const [msg, setMsg] = useState("")
  const [ok, setOk] = useState<boolean | null>(null)
  const [candidates, setCandidates] = useState<AnimeCandidate[]>([])
  const [loading, setLoading] = useState(false)

  async function onFile(file: File) {
    setLoading(true)
    setMsg("")
    setCandidates([])
    setOk(null)
    try {
      const r = await uploadAnime(file)
      const j = (await r.json()) as AnimeResponse
      setOk(Boolean(j.ok))
      setMsg(j.text || j.error || (j.ok ? "Найдено" : "Не распознано"))
      setCandidates(j.candidates ?? [])
    } catch (e) {
      setMsg(String(e))
      setOk(false)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="w-full pt-8 pr-8 pb-32 pl-8">
      <div className="mb-8">
        <h1 className="mb-2 text-3xl font-semibold tracking-tight">Аниме</h1>
        <p className="text-muted-foreground text-sm">Поиск аниме по кадру или клипу (Trace.moe).</p>
      </div>
      <Card className="rounded-2xl">
        <CardHeader>
          <CardTitle>Распознавание</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <input
            ref={inputRef}
            type="file"
            accept="image/*,video/*"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0]
              if (f) void onFile(f)
            }}
          />
          <Button onClick={() => inputRef.current?.click()} disabled={loading}>
            {loading ? "Ищу…" : "Загрузить кадр или видео"}
          </Button>

          {msg ? (
            <p
              className={cn(
                "text-sm whitespace-pre-line",
                ok === false ? "text-muted-foreground" : "text-foreground",
              )}
            >
              {msg}
            </p>
          ) : null}

          {candidates.length > 0 ? (
            <div className="space-y-4 pt-2">
              <p className="text-muted-foreground text-xs font-medium uppercase tracking-wide">
                Возможные совпадения ({candidates.length})
              </p>
              <ul className="space-y-4">
                {candidates.map((c, i) => {
                  const img = candidateImage(c)
                  const pct =
                    c.similarity != null ? `${(c.similarity * 100).toFixed(1)}%` : null
                  return (
                    <li
                      key={`${c.title}-${i}`}
                      className="border-border bg-card/50 flex flex-col gap-4 rounded-xl border p-4 sm:flex-row"
                    >
                      {img ? (
                        <a
                          href={img}
                          target="_blank"
                          rel="noreferrer"
                          className="block shrink-0"
                          onClick={(e) => {
                            e.preventDefault()
                            void openUrl(img.startsWith("/") ? `${window.location.origin}${img}` : img)
                          }}
                        >
                          <img
                            src={img}
                            alt=""
                            className="bg-muted size-36 rounded-lg object-cover sm:size-40"
                          />
                        </a>
                      ) : (
                        <div className="bg-muted size-36 shrink-0 rounded-lg sm:size-40" />
                      )}
                      <div className="min-w-0 flex-1">
                        <div className="mb-1 flex flex-wrap items-center gap-2">
                          <p className="text-base font-semibold">{c.title || "—"}</p>
                          {pct ? (
                            <Badge variant={i === 0 && ok ? "default" : "secondary"}>{pct}</Badge>
                          ) : null}
                        </div>
                        <p className="text-muted-foreground text-sm">
                          {c.episode != null ? `Серия ${c.episode}` : "Серия —"}
                          {c.moment ? ` · ${c.moment}` : ""}
                        </p>
                        <div className="mt-3 flex flex-wrap gap-2">
                          {c.anilist_url ? (
                            <Button size="sm" variant="secondary" onClick={() => void openUrl(c.anilist_url!)}>
                              AniList
                            </Button>
                          ) : null}
                          {c.shikimori_url ? (
                            <Button size="sm" variant="secondary" onClick={() => void openUrl(c.shikimori_url!)}>
                              Shikimori
                            </Button>
                          ) : null}
                          {c.mal_url ? (
                            <Button size="sm" variant="secondary" onClick={() => void openUrl(c.mal_url!)}>
                              MAL
                            </Button>
                          ) : null}
                          {c.video_url ? (
                            <Button size="sm" variant="outline" onClick={() => void openUrl(c.video_url!)}>
                              Клип trace.moe
                            </Button>
                          ) : null}
                        </div>
                      </div>
                    </li>
                  )
                })}
              </ul>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}
