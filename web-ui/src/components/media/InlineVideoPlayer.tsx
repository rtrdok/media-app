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
  if (!src) return null
  return (
    <video
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
