import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react"

/** Простой виртуальный список с фиксированной высотой строки (без доп. зависимостей). */
export function VirtualList<T extends { id?: string | number }>({
  items,
  rowHeight,
  maxHeight = 560,
  className,
  renderRow,
  empty,
}: {
  items: T[]
  rowHeight: number
  maxHeight?: number
  className?: string
  renderRow: (item: T, index: number) => ReactNode
  empty?: ReactNode
}) {
  const scrollerRef = useRef<HTMLDivElement | null>(null)
  const [scrollTop, setScrollTop] = useState(0)
  const [viewportH, setViewportH] = useState(maxHeight)

  const onScroll = useCallback(() => {
    const el = scrollerRef.current
    if (!el) return
    setScrollTop(el.scrollTop)
  }, [])

  useEffect(() => {
    const el = scrollerRef.current
    if (!el) return
    const measure = () => setViewportH(el.clientHeight || maxHeight)
    measure()
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null
    ro?.observe(el)
    return () => ro?.disconnect()
  }, [maxHeight, items.length])

  const total = items.length
  const overscan = 6
  const start = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan)
  const visibleCount = Math.ceil(viewportH / rowHeight) + overscan * 2
  const end = Math.min(total, start + visibleCount)
  const offsetY = start * rowHeight
  const slice = useMemo(() => items.slice(start, end), [items, start, end])

  if (!total) {
    return <>{empty}</>
  }

  return (
    <div
      ref={scrollerRef}
      onScroll={onScroll}
      className={className}
      style={{ maxHeight, overflowY: "auto", position: "relative" }}
    >
      <div style={{ height: total * rowHeight, position: "relative" }}>
        <div style={{ transform: `translateY(${offsetY}px)` }}>
          {slice.map((item, i) => {
            const index = start + i
            return (
              <div key={item.id ?? index} style={{ height: rowHeight }}>
                {renderRow(item, index)}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
