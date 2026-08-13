import type { TemplateOut } from '@/services/templates'

/**
 * Client-side stand-in for a real search endpoint, over the templates the
 * backend actually returned.
 *
 * `GET /templates` is unpaginated and small, so filtering in the browser is
 * honest and immediate. When a real `POST /search` exists this signature is
 * what it should replace.
 *
 * The invented relevance scoring that used to live here — semantic similarity,
 * team usage, recency, and a "why this matched" breakdown — is gone. Those
 * numbers were generated from a result's position in the list, so they
 * described nothing.
 *
 * Words of two characters or fewer are dropped; matching "of" against every
 * template makes the result set meaningless.
 */
export function filterTemplates(templates: TemplateOut[], query: string, format: string): TemplateOut[] {
  const q = query.trim().toLowerCase()
  const words = q ? q.split(/\s+/).filter((w) => w.length > 2) : []

  return templates.filter((t) => {
    if (format !== 'all' && t.format !== format) return false
    if (!words.length) return true
    const hay = `${t.title} ${t.original_filename} ${t.format}`.toLowerCase()
    return words.some((w) => hay.includes(w))
  })
}
