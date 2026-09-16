import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useApp } from "@/context/AppProvider"
import { cancelJob, getClipboard, queueClear, queuePause, queueResume } from "@/lib/api"
import { cn } from "@/lib/utils"

export function DownloadsPage() {
  const { state, refresh } = useApp()
  const p = state?.progress
  const queue = state?.queue ?? []
  const files = state?.files ?? []
  const paused = !!state?.paused
  const runningCount = state?.running_count ?? queue.filter((q) => q.status === "running").length
  const maxConcurrent = state?.max_concurrent ?? state?.settings?.max_concurrent_downloads ?? 3

  return (
    <div className="w-full pt-8 pr-8 pb-32 pl-8">
      <div className="mb-8">
        <h1 className="mb-2 text-3xl font-semibold tracking-tight">Загрузки</h1>
        <p className="text-muted-foreground text-sm">Очередь, прогресс и недавние файлы в папке загрузок.</p>
      </div>

      <Card className="mb-6 rounded-2xl">
        <CardHeader>
          <CardTitle className="text-lg">
            Активные загрузки
            {runningCount > 0 ? (
              <span className="text-muted-foreground ml-2 text-sm font-normal">
                · {runningCount}/{maxConcurrent}
              </span>
            ) : null}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-muted-foreground text-sm">
            {paused
              ? "Очередь на паузе"
              : state?.busy
                ? [p?.stage, p?.percent, p?.speed, p?.eta].filter(Boolean).join(" · ") || "Загрузка…"
                : "Нет активной загрузки"}
          </p>
          <div className="bg-muted h-2 overflow-hidden rounded-full">
            <div
              className={cn("bg-primary h-full transition-all", paused && "opacity-40")}
              style={{
                width: p?.indeterminate ? "40%" : `${Math.min(100, Number(p?.percent) || 0)}%`,
              }}
            />
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {paused ? (
              <Button
                size="sm"
                onClick={() => void queueResume().then(() => refresh(true))}
              >
                Продолжить очередь
              </Button>
            ) : (
              <Button
                variant="outline"
                size="sm"
                onClick={() => void queuePause().then(() => refresh(true))}
              >
                Пауза очереди
              </Button>
            )}
            <Button variant="ghost" size="sm" onClick={() => void queueClear().then(() => refresh(true))}>
              Очистить очередь
            </Button>
            <Button variant="ghost" size="sm" className="text-destructive" onClick={() => void cancelJob()}>
              Отмена активных
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                void getClipboard().then((j) => {
                  if (j.text) void navigator.clipboard?.writeText(j.text)
                })
              }}
            >
              Вставить из буфера
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card className="mb-6 rounded-2xl">
        <CardHeader>
          <CardTitle className="text-lg">
            Очередь ({queue.length})
            {paused ? <span className="text-muted-foreground ml-2 text-sm font-normal">· пауза</span> : null}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {queue.length === 0 ? (
            <p className="text-muted-foreground text-sm">Очередь пуста</p>
          ) : (
            queue.map((q) => (
              <div key={q.id} className="border-border space-y-1 border-b py-2 text-sm last:border-0">
                <div className="flex justify-between gap-4">
                  <span className="truncate">{q.title || q.url}</span>
                  <span
                    className={
                      q.status === "error"
                        ? "text-destructive shrink-0"
                        : "text-muted-foreground shrink-0"
                    }
                  >
                    {q.status === "error" ? "ошибка" : q.status}
                  </span>
                </div>
                {q.status === "running" && q.progress ? (
                  <p className="text-muted-foreground text-xs">
                    {[q.progress.stage, q.progress.percent, q.progress.speed, q.progress.eta]
                      .filter(Boolean)
                      .join(" · ") || "Загрузка…"}
                  </p>
                ) : null}
                {q.status === "error" && q.error ? (
                  <p className="text-destructive/90 text-xs whitespace-pre-wrap break-words">{q.error}</p>
                ) : null}
              </div>
            ))
          )}
          {state?.last?.error ? (
            <p className="text-muted-foreground pt-2 text-xs">Последняя ошибка: {state.last.error}</p>
          ) : null}
        </CardContent>
      </Card>

      <Card className="rounded-2xl">
        <CardHeader>
          <CardTitle className="text-lg">Файлы в папке</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {files.length === 0 ? (
            <p className="text-muted-foreground text-sm">Нет файлов или обновите страницу</p>
          ) : (
            files.slice(0, 30).map((f) => (
              <div key={f.path} className="truncate text-sm">
                {f.name}
              </div>
            ))
          )}
        </CardContent>
      </Card>
    </div>
  )
}
