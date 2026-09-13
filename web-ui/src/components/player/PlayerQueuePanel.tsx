import { GripVertical, X } from "lucide-react"
import { useApp } from "@/context/AppProvider"
import { cn } from "@/lib/utils"

/** Панель очереди воспроизведения: переход, удаление, перемещение. */
export function PlayerQueuePanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { playQueue, queueMeta, jumpToQueue, removeFromQueue, moveInQueue } = useApp()
  if (!open) return null

  return (
    <div className="border-border bg-card absolute right-3 bottom-[4.5rem] z-50 flex max-h-72 w-[min(360px,calc(100vw-2rem))] flex-col overflow-hidden rounded-2xl border shadow-xl">
      <div className="border-border flex items-center justify-between border-b px-3 py-2">
        <p className="text-sm font-medium">Очередь · {playQueue.length}</p>
        <button type="button" className="text-muted-foreground hover:text-foreground rounded-lg p-1" onClick={onClose}>
          <X className="size-4" />
        </button>
      </div>
      <div className="overflow-y-auto p-1">
        {playQueue.length === 0 ? (
          <p className="text-muted-foreground px-3 py-4 text-sm">Очередь пуста</p>
        ) : (
          playQueue.map((t, i) => (
            <div
              key={`${t.src}-${i}`}
              className={cn(
                "group flex items-center gap-1 rounded-xl px-1 py-1.5",
                i === queueMeta.index ? "bg-primary/15" : "hover:bg-muted/60",
              )}
              draggable
              onDragStart={(e) => {
                e.dataTransfer.setData("text/plain", String(i))
              }}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault()
                const from = Number(e.dataTransfer.getData("text/plain"))
                if (!Number.isNaN(from)) moveInQueue(from, i)
              }}
            >
              <span className="text-muted-foreground cursor-grab px-1">
                <GripVertical className="size-3.5" />
              </span>
              <button
                type="button"
                className="min-w-0 flex-1 truncate text-left text-sm"
                onClick={() => jumpToQueue(i)}
              >
                <span className="font-medium">{t.title}</span>
                {t.artist ? <span className="text-muted-foreground"> · {t.artist}</span> : null}
              </button>
              <button
                type="button"
                className="text-muted-foreground hover:text-destructive rounded-md p-1 opacity-0 group-hover:opacity-100"
                title="Убрать из очереди"
                onClick={() => removeFromQueue(i)}
              >
                <X className="size-3.5" />
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
