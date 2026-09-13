import { Download } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { openUrl, postJob } from "@/lib/api"
import type { ShazamResult } from "@/types"

export function ShazamResultCard({
  result,
  onDownloaded,
}: {
  result: ShazamResult
  onDownloaded?: () => void
}) {
  if (!result.track) return null

  async function downloadTrack() {
    await postJob({
      url: "",
      kind: "track",
      track: result.track,
      quality: "720",
      fmt: "MP3",
      start: "",
      end: "",
    })
    onDownloaded?.()
  }

  return (
    <Card className="border-border bg-card mb-8 gap-0 rounded-2xl border p-4 shadow-sm">
      <div className="flex flex-wrap gap-4">
        {result.cover ? (
          <img src={result.cover} alt="" className="size-24 shrink-0 rounded-xl object-cover" />
        ) : null}
        <div className="min-w-0 flex-1">
          <p className="text-lg font-semibold">{result.track}</p>
          {result.artist ? <p className="text-muted-foreground text-sm">{result.artist}</p> : null}
          {result.preview ? (
            <audio controls src={result.preview} className="mt-3 h-9 w-full max-w-md" preload="metadata" />
          ) : null}
        </div>
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        <Button className="gap-2" onClick={() => void downloadTrack()}>
          <Download className="size-4" />
          Скачать трек
        </Button>
        {result.links?.map((l) => (
          <Button key={l.url} variant="secondary" size="sm" onClick={() => void openUrl(l.url)}>
            {l.name}
          </Button>
        ))}
      </div>
    </Card>
  )
}
