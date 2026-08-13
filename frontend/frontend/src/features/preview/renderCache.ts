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
 * Backend contract:
 *   GET /api/v1/render/{key}  →  { pngUrl, renderedInMs }
 *
 * The backend runs `soffice --headless --convert-to pdf` with a per-invocation
 * `-env:UserInstallation` and a timeout (Implementation Plan §11), then rasterises
 * page 1. Until that endpoint exists, `simulateRender` stands in with the same
 * shape and a representative 1–3s latency, so the swap-in behaviour on the
 * fill screen is exercised for real.
 */
async function simulateRender(key: string, signal?: AbortSignal): Promise<RenderResult> {
  const started = performance.now()
  const latency = 1100 + (parseInt(key.slice(0, 2), 16) / 255) * 900

  await new Promise<void>((resolve, reject) => {
    const t = setTimeout(resolve, latency)
    signal?.addEventListener('abort', () => {
      clearTimeout(t)
      reject(new DOMException('Render superseded', 'AbortError'))
    })
  })

  return { key, pngUrl: `render://${key}`, renderedInMs: Math.round(performance.now() - started) }
}

export function requestRender(key: string, signal?: AbortSignal): Promise<RenderResult> {
  const hit = cache.get(key)
  if (hit) return Promise.resolve(hit)

  const pending = inflight.get(key)
  if (pending) return pending

  const p = simulateRender(key, signal)
    .then((result) => {
      cache.set(key, result)
      inflight.delete(key)
      return result
    })
    .catch((err) => {
      inflight.delete(key)
      throw err
    })

  inflight.set(key, p)
  return p
}
