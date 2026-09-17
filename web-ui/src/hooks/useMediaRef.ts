import { useCallback, useRef } from "react"

/** Removing a media element from the DOM does not unload its resource. */
export function useMediaRef<T extends HTMLMediaElement>(src: string | undefined) {
  const mediaRef = useRef<T | null>(null)
  const attachMedia = useCallback((element: T | null) => {
    const previous = mediaRef.current
    if (previous && previous !== element) {
      previous.pause()
      previous.removeAttribute("src")
      // Abort buffering and release the resource, including on hidden tabs.
      previous.load()
    }
    mediaRef.current = element
    // StrictMode may detach and reattach the same DOM node without resetting props.
    if (element && src && element.getAttribute("src") !== src) {
      element.setAttribute("src", src)
    }
  }, [src])
  return { mediaRef, attachMedia }
}
