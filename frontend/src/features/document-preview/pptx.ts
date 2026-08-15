/** The deck is rendered at this width, then scaled down to whatever fits. */
const RENDER_WIDTH = 960

/**
 * `pptx-preview` renders into a fixed-size viewport with its own inner
 * scrollbar, so in any panel narrower than `RENDER_WIDTH` the deck is simply
 * clipped. Two fixes, both after the fact — the library takes no options for
 * either:
 *
 *  1. Let the slide stack lay out at its natural height and drop the library's
 *     inner scroll, since `.document-preview-surface` already scrolls.
 *  2. Scale the whole stack to the available width with a CSS transform, and
 *     size an outer wrapper to the *scaled* footprint — a transform doesn't
 *     affect layout, so without that wrapper the untransformed height would
 *     leave a block of dead space underneath.
 *
 * Slide height is deliberately measured rather than assumed: a 4:3 deck lays
 * out 960×720 here, a 16:9 one 960×540.
 *
 * Returns a cleanup that stops the resize observer.
 */
export async function renderPptx(container: HTMLElement, buf: ArrayBuffer): Promise<() => void> {
  const { init } = await import('pptx-preview')
  const viewer = init(container, { width: RENDER_WIDTH, height: 540, mode: 'list' })
  await viewer.preview(buf)

  const wrapper = container.querySelector<HTMLElement>('.pptx-preview-wrapper')
  if (!wrapper) return () => {}

  wrapper.style.height = 'auto'
  wrapper.style.overflowY = 'visible'
  wrapper.style.background = 'transparent'
  wrapper.style.margin = '0'
  wrapper.style.transformOrigin = 'top left'

  const scaler = document.createElement('div')
  wrapper.replaceWith(scaler)
  scaler.appendChild(wrapper)

  let lastWidth = -1
  const fit = () => {
    /* Clear the explicit width first so the block collapses back to the
       container's content box and we can read what's actually available. */
    scaler.style.width = ''
    const available = scaler.clientWidth
    if (!available || available === lastWidth) return
    lastWidth = available

    const scale = Math.min(1, available / RENDER_WIDTH)
    wrapper.style.transform = scale === 1 ? '' : `scale(${scale})`
    scaler.style.width = `${RENDER_WIDTH * scale}px`
    scaler.style.height = `${wrapper.scrollHeight * scale}px`
  }

  fit()

  /* Resizing the panel re-fits the deck. The `lastWidth` guard keeps this from
     feeding back on itself — `fit` changes the scaler's height, which changes
     the container's, which fires the observer again. */
  const observer = new ResizeObserver(fit)
  observer.observe(container)
  return () => observer.disconnect()
}
