/**
 * Word rendering, via docx-preview.
 *
 * Only the options that actually change the output are listed — checked
 * against docx-preview 0.4's own `defaultOptions`, where `breakPages`,
 * `inWrapper`, `renderHeaders`, `renderFooters`, `renderFootnotes` and
 * `renderEndnotes` are already `true`. Passing those would just be noise.
 *
 * `className` is left at its default `"docx"`, so the wrapper is the
 * conventional `.docx-wrapper` and the library's own page chrome (grey
 * backdrop, white A4 sheets, drop shadow) applies unchanged.
 *
 * Returns a cleanup that stops the fit-to-width observer.
 */
export async function renderDocx(container: HTMLElement, buf: ArrayBuffer): Promise<() => void> {
  const { renderAsync } = await import('docx-preview')
  const { fitToWidth } = await import('./fitToWidth')

  await renderAsync(buf, container, container, {
    /* Word records where it actually paginated (`w:lastRenderedPageBreak`).
       Honouring it puts the page breaks where Word put them instead of
       re-deriving them from content height. */
    ignoreLastRenderedPageBreak: false,
    /* Embedded images default to object URLs, which are revoked when this
       render is torn down and would blank out a long-lived viewer tab. */
    useBase64URL: true,
    /* Enables tab-stop handling, which is what holds form-style templates
       (label ....... value) in alignment. */
    experimental: true,
  })

  /* A Word page is a fixed 794px (A4 at 96dpi) and overflows any panel
     narrower than that — the Upload form's column, for one. Scale it to fit
     instead, which is a no-op in the full-width viewer tab. */
  const wrapper = container.querySelector<HTMLElement>('.docx-wrapper')
  return wrapper ? fitToWidth(container, wrapper) : () => {}
}
