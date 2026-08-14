import type { RenderResult } from './types'

/**
 * Cache of pixel-accurate renders, keyed on `hash(base_version_id + change_spec)`.
 *
 * Two things matter here. First, the key is content-addressed, so revisiting an
 * earlier answer — or a second user generating the same document from the same
 * base version — is a cache hit, not another LibreOffice invocation. Second,
 * in-flight renders are deduped: a second request for a key already rendering
 * awaits the first promise rather than starting a competing subprocess.
 */

const cache = new Map<string, RenderResult>()
const inflight = new Map<string, Promise<RenderResult>>()

export const peekRender = (key: string) => cache.get(key)

export function clearRenderCache() {
  cache.clear()
  inflight.clear()
}

/**
 * Backend contract, once it exists:
 *   GET /api/v1/render/{key}  →  { pngUrl, renderedInMs }
 *
 * The backend would run `soffice --headless --convert-to pdf` with a
 * per-invocation `-env:UserInstallation` and a timeout (Implementation Plan
 * §11), then rasterise page 1.
 *
 * **There is no such endpoint yet.** This used to stand in with a simulated
 * 1–3s latency that resolved to a `render://` URL with no bytes behind it, and
 * the preview pane then reported "Exact layout · rendered in 1400ms" — a
 * measured-sounding claim about a render that never happened. It now rejects,
 * so the pane says it is showing structure only, which is true. The cache and
 * the in-flight dedupe below are kept because they are the parts that will
 * matter the moment the endpoint lands.
 */
export class RendererUnavailable extends Error {
  constructor() {
    super('The exact renderer is not wired up yet.')
    this.name = 'RendererUnavailable'
  }
}

export function requestRender(key: string, _signal?: AbortSignal): Promise<RenderResult> {
  const hit = cache.get(key)
  if (hit) return Promise.resolve(hit)

  const pending = inflight.get(key)
  if (pending) return pending

  return Promise.reject(new RendererUnavailable())
}
