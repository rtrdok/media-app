import { cn } from "@/lib/utils"

const GRADIENTS = [
  "from-[#003789] via-[#6875f6] to-[#003044]",
  "from-[#004217] via-[#00a381] to-[#002a28]",
  "from-[#00233f] via-[#007a97] to-[#e28b63]",
  "from-[#562380] via-[#c454b0] to-[#261d57]",
  "from-[#091a49] via-[#52339b] to-[#001132]",
  "from-[#001335] via-[#25267b] to-[#00283c]",
]

export function HistoryThumb({
  index,
  thumb,
  className,
}: {
  index: number
  thumb?: string
  className?: string
}) {
  if (thumb) {
    return (
      <img
        src={thumb}
        alt=""
        className={cn("size-14 shrink-0 rounded-lg object-cover", className)}
      />
    )
  }
  const g = GRADIENTS[index % GRADIENTS.length]
  return (
    <div
      className={cn("size-14 shrink-0 rounded-lg bg-gradient-to-br", g, className)}
      aria-hidden
    />
  )
}
