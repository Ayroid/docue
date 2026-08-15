import { useCallback, useEffect, useRef, useState, type DragEvent } from 'react'

/** A drag carrying files, as opposed to selected text or a dragged link. */
const carriesFiles = (e: DragEvent) => Array.from(e.dataTransfer.types).includes('Files')

/**
 * Drop-to-pick for a file input.
 *
 * Returns the handlers to spread onto whatever should accept a drop, plus a
 * `dragging` flag for the target to show it is armed — a drop zone that looks
 * identical mid-drag gives no clue that letting go will work.
 *
 * **The depth counter is the part that is easy to get wrong.** `dragenter` and
 * `dragleave` fire for every child element the pointer crosses, not just the
 * zone itself, so clearing the flag on any `dragleave` makes the highlight
 * flicker off the moment the cursor passes over the icon or the label inside.
 * Counting enters against leaves and only clearing at zero tracks the zone as a
 * whole.
 */
export function useFileDrop(onFile: (file: File) => void) {
  const [dragging, setDragging] = useState(false)
  const depth = useRef(0)

  const onDragEnter = useCallback((e: DragEvent) => {
    if (!carriesFiles(e)) return
    e.preventDefault()
    depth.current += 1
    setDragging(true)
  }, [])

  const onDragOver = useCallback((e: DragEvent) => {
    if (!carriesFiles(e)) return
    /* Required every frame, not once: without preventDefault here the browser
       treats the element as a non-target, shows the "no drop" cursor, and then
       navigates the tab to the file when it is released. */
    e.preventDefault()
    e.dataTransfer.dropEffect = 'copy'
  }, [])

  const onDragLeave = useCallback((e: DragEvent) => {
    if (!carriesFiles(e)) return
    e.preventDefault()
    depth.current = Math.max(0, depth.current - 1)
    if (depth.current === 0) setDragging(false)
  }, [])

  const onDrop = useCallback(
    (e: DragEvent) => {
      if (!carriesFiles(e)) return
      e.preventDefault()
      depth.current = 0
      setDragging(false)
      /* First file only. The page uploads one template at a time, and silently
         taking one of several is better than rejecting the drop outright —
         the picked name is shown back immediately, so the choice is visible. */
      const file = e.dataTransfer.files?.[0]
      if (file) onFile(file)
    },
    [onFile],
  )

  return { dragging, dropProps: { onDragEnter, onDragOver, onDragLeave, onDrop } }
}

/**
 * Stop a file dropped *outside* a drop zone from replacing the page with itself.
 *
 * A near-miss is the common case — the pointer lands a few pixels off the zone —
 * and the browser default is to navigate to the dropped file, which throws away
 * the half-filled form with no warning and no way back. Swallowing strays makes
 * a miss cost nothing.
 *
 * The zones still work: these listeners are on `window`, so they run in the
 * bubble phase after the target's own handler has already taken the file.
 */
export function useBlockStrayFileDrops() {
  useEffect(() => {
    const swallow = (e: Event) => {
      const dt = (e as unknown as DragEvent).dataTransfer
      if (dt && !Array.from(dt.types).includes('Files')) return
      e.preventDefault()
    }
    window.addEventListener('dragover', swallow)
    window.addEventListener('drop', swallow)
    return () => {
      window.removeEventListener('dragover', swallow)
      window.removeEventListener('drop', swallow)
    }
  }, [])
}
