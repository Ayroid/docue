import { useEffect, useMemo, useRef, useState } from 'react'
import type { ChangeSpec, ParsedDocument, RenderResult, RenderStatus, WorkingCopy } from './types'
import { applySpec, specKey } from './workingCopy'
import { peekRender, requestRender } from './renderCache'

export interface LivePreview {
  /** Structural preview — available synchronously on the same tick as the answer. */
  working: WorkingCopy
  /** Milliseconds spent applying the spec and building the structural view. */
  fastPathMs: number
  /** Pixel-accurate render, once LibreOffice lands it. Null until then. */
  render: RenderResult | null
  renderStatus: RenderStatus
  /** True when the render on screen belongs to an older spec than the working copy. */
  renderStale: boolean
}

/**
 * The two-speed preview from Implementation Plan §5.
 *
 * On every answer submit the spec is applied to an in-memory working copy and
 * the structural preview is returned immediately — target ~80ms, in practice a
 * synchronous `useMemo` over a few dozen regions. The LibreOffice render is
 * fired in the background and swapped in when it arrives, typically before the
 * user finishes typing the next answer. Superseded renders are aborted so a
 * stale PNG can never overwrite a newer one.
 */
export function useLivePreview(original: ParsedDocument, spec: ChangeSpec): LivePreview {
  const key = useMemo(() => specKey(spec), [spec])

  // ── Fast path ──────────────────────────────────────────────────────────
  const { working, fastPathMs } = useMemo(() => {
    const t0 = performance.now()
    const wc = applySpec(original, spec)
    return { working: wc, fastPathMs: performance.now() - t0 }
  }, [original, spec])

  // ── Accurate path ──────────────────────────────────────────────────────
  const cached = peekRender(key) ?? null
  const [render, setRender] = useState<RenderResult | null>(cached)
  const [renderStatus, setRenderStatus] = useState<RenderStatus>(cached ? 'ready' : 'idle')
  const latestKey = useRef(key)

  useEffect(() => {
    latestKey.current = key

    const hit = peekRender(key)
    if (hit) {
      setRender(hit)
      setRenderStatus('ready')
      return
    }

    const controller = new AbortController()
    setRenderStatus('rendering')

    requestRender(key, controller.signal)
      .then((result) => {
        // Guard against an out-of-order resolve landing on a newer spec.
        if (latestKey.current !== result.key) return
        setRender(result)
        setRenderStatus('ready')
      })
      .catch((err) => {
        if (err instanceof DOMException && err.name === 'AbortError') return
        if (latestKey.current !== key) return
        setRenderStatus('failed')
      })

    return () => controller.abort()
  }, [key])

  return {
    working,
    fastPathMs,
    render,
    renderStatus,
    renderStale: render !== null && render.key !== key,
  }
}
