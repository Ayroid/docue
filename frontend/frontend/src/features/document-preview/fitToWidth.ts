/**
 * Scale a fixed-width render down to the width actually available.
 *
 * Office documents lay out at a real page size — a Word page is 794px wide at
 * 96dpi, a slide 960px — so in any panel narrower than that they simply spill
 * sideways. Nothing in these libraries takes a "fit to width" option, so it is
 * done after the fact: measure what the content naturally wants, scale it, and
 * size an inserted wrapper to the *scaled* footprint. That last part matters —
 * a transform doesn't affect layout, so without it the untransformed height
 * would leave a block of dead space underneath.
 *
 * Never scales up: a document narrower than the panel is left at 1:1 rather
 * than being blown up past its real size.
 *
 * Returns a cleanup that stops the observer.
 */
export function fitToWidth(container: HTMLElement, content: HTMLElement): () => void {
  content.style.transformOrigin = 'top left'

  const scaler = document.createElement('div')
  content.replaceWith(scaler)
  scaler.appendChild(content)

  /* What the content wants when nothing constrains it. Measured rather than
     assumed — page size varies (A4 vs Letter, portrait vs landscape).
     Deliberately deferred: the caller renders into a surface that stays
     `display: none` until the render resolves, and everything measures 0 while
     it is hidden. The observer below fires again once it appears. */
  let naturalWidth = 0
  let lastWidth = -1

  const fit = () => {
    /* Clear the explicit width first so the block collapses back to the
       container's content box and we can read what's actually available. */
    scaler.style.width = ''
    const available = scaler.clientWidth
    if (!available) return

    if (!naturalWidth) {
      content.style.width = ''
      content.style.transform = ''
      content.style.width = 'max-content'
      naturalWidth = content.offsetWidth
      content.style.width = ''
      if (!naturalWidth) return
      lastWidth = -1
    }

    if (available === lastWidth) return
    lastWidth = available

    const scale = Math.min(1, available / naturalWidth)
    /* Pin the content to its natural width before scaling, or it would just be
       re-squeezed by the scaler's own (smaller) width. */
    content.style.width = `${naturalWidth}px`
    content.style.transform = scale === 1 ? '' : `scale(${scale})`
    scaler.style.width = `${naturalWidth * scale}px`
    scaler.style.height = `${content.scrollHeight * scale}px`
  }

  fit()

  /* Resizing the panel re-fits. The `lastWidth` guard keeps this from feeding
     back on itself — `fit` changes the scaler's height, which changes the
     container's, which fires the observer again. */
  const observer = new ResizeObserver(fit)
  observer.observe(container)
  return () => observer.disconnect()
}
