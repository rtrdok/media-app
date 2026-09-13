import { useEffect, useState } from "react"
import { AppModal } from "@/components/ui/AppModal"
import { Button } from "@/components/ui/button"
import { fetchLyrics } from "@/lib/api"

type Props = {
  open: boolean
  title: string
  artist: string
  onClose: () => void
}

export function LyricsModal({ open, title, artist, onClose }: Props) {
  const [text, setText] = useState("")
  const [msg, setMsg] = useState("Загрузка…")
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open) return
    setBusy(true)
    setMsg("Ищем текст…")
    setText("")
    void fetchLyrics(title, artist)
      .then((j) => {
        if (j.ok && j.lyrics) {
          setText(j.lyrics)
          setMsg("")
        } else setMsg(j.error || "Текст не найден")
      })
      .catch((e) => setMsg(String(e)))
      .finally(() => setBusy(false))
  }, [open, title, artist])

  return (
    <AppModal
      open={open}
      title="Текст песни"
      description={artist ? `${title} — ${artist}` : title}
      onClose={onClose}
      className="max-w-lg"
      footer={
        <Button variant="ghost" onClick={onClose}>
          Закрыть
        </Button>
      }
    >
      {busy || msg ? (
        <p className="text-muted-foreground text-sm">{msg || "Загрузка…"}</p>
      ) : (
        <pre className="max-h-[50vh] overflow-y-auto whitespace-pre-wrap font-sans text-sm leading-relaxed">
          {text}
        </pre>
      )}
    </AppModal>
  )
}
