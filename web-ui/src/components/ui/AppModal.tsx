import { X } from "lucide-react"
import { useEffect } from "react"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

type AppModalProps = {
  open: boolean
  title: string
  description?: string
  onClose: () => void
  children: React.ReactNode
  footer?: React.ReactNode
  className?: string
}

/** Центрированная модалка в стиле приложения (вместо window.prompt). */
export function AppModal({
  open,
  title,
  description,
  onClose,
  children,
  footer,
  className,
}: AppModalProps) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center p-4">
      <button
        type="button"
        aria-label="Закрыть"
        className="absolute inset-0 bg-black/40 backdrop-blur-[2px]"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="app-modal-title"
        className={cn(
          "border-border bg-card relative z-10 w-full max-w-md rounded-2xl border p-5 shadow-xl",
          className,
        )}
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 id="app-modal-title" className="text-lg font-semibold tracking-tight">
              {title}
            </h2>
            {description ? (
              <p className="text-muted-foreground mt-1 text-sm">{description}</p>
            ) : null}
          </div>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="size-8 shrink-0 p-0"
            onClick={onClose}
            aria-label="Закрыть"
          >
            <X className="size-4" />
          </Button>
        </div>
        <div>{children}</div>
        {footer ? <div className="mt-5 flex flex-wrap justify-end gap-2">{footer}</div> : null}
      </div>
    </div>
  )
}
