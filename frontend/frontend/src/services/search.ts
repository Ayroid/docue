import type { Template } from '@/data/mock'

/**
 * Client-side stand-in for `POST /search`. The real endpoint fuses BM25 and
 * vector scores with RRF and applies the ACL filter post-retrieval; this keeps
 * the same signature so the swap is a one-file change.
 *
 * Words of two characters or fewer are dropped — matching "of" against every
 * template makes the result set meaningless.
 */
export function filterTemplates(templates: Template[], query: string, cat: string): Template[] {
  const q = query.trim().toLowerCase()
  const words = q ? q.split(/\s+/).filter((w) => w.length > 2) : []

  return templates.filter((t) => {
    if (cat !== 'All' && t.category !== cat && t.group !== cat) return false
    if (!words.length) return true
    const hay = `${t.name} ${t.desc} ${t.category} ${t.group} ${t.owner}`.toLowerCase()
    return words.some((w) => hay.includes(w))
  })
}

/** Per-signal breakdown behind a result's score — the "why this matched" panel. */
export function scoreSignals(rank: number) {
  return [
    { name: 'Semantic similarity', raw: 0.92 - rank * 0.05, weight: 40 },
    { name: 'Title match', raw: 0.8 - rank * 0.08, weight: 20 },
    { name: 'Team usage', raw: 0.88 - rank * 0.06, weight: 20 },
    { name: 'Recency', raw: 0.75 - rank * 0.05, weight: 10 },
    { name: 'Format match', raw: 1.0 - rank * 0.1, weight: 10 },
  ].map((s) => ({
    ...s,
    rawLabel: s.raw.toFixed(2),
    weightLabel: `${s.weight}%`,
    contribution: Math.round(s.raw * s.weight),
  }))
}

export const RANK_SCORES = [94, 88, 81, 76, 70]
