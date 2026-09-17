import { useMediaRef } from "@/hooks/useMediaRef"

/** Превью/плеер для локального файла или /api/file (видео). */
export function InlineVideoPlayer({
  src,
  className,
  onTimeUpdate,
}: {
  src: string
  className?: string
  onTimeUpdate?: (current: number, duration: number) => void
}) {
  const { attachMedia } = useMediaRef<HTMLVideoElement>(src)
  if (!src) return null
  return (
    <video
      ref={attachMedia}
      src={src}
      controls
      className={className}
      onTimeUpdate={(e) => {
        const el = e.currentTarget
        onTimeUpdate?.(el.currentTime, el.duration || 0)
      }}
    />
  )
}
