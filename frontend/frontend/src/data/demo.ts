/**
 * Fixtures for the **generation walkthrough only** — the Generate → Review →
 * Document flow reachable from a template's Generate button.
 *
 * That flow is a demonstration, not a working feature: there is no
 * region-detection or document-compiler service behind it, so the questions
 * below, the values the agent "extracts", the confidence percentages and the
 * QA results are all scripted. Every screen that uses this module is marked
 * with a Demo badge so nobody mistakes the output for a real document.
 *
 * Nothing else in the app imports this. Discovery, search, the library, the
 * viewer, template detail and Admin all read real records from the backend.
 * Keep it that way — if you need data on one of those pages, add the field to
 * the API rather than inventing it here.
 */

import type { Fmt } from '@/data/catalog'

/** The shape the walkthrough needs from a template. A real backend record is
    adapted into this by `features/generate/useDemoTemplate`. */
export interface DemoTemplate {
  id: string
  name: string
  version: string
  fmt: Fmt
}

/** Used only when the walkthrough is opened without a resolvable template. */
export const FALLBACK_TEMPLATE: DemoTemplate = {
  id: 'demo',
  name: 'Minutes of Meeting',
  version: '1',
  fmt: 'DOC',
}

export type Provenance = 'Typed' | 'Derived' | 'AI-drafted' | 'Unchanged'

export const REVIEW_ROWS: { label: string; value: string; prov: Provenance; conf: number | null }[] = [
  { label: 'Title', value: 'MOM — Dealer Portal kickoff', prov: 'Typed', conf: null },
  { label: 'Client & project', value: 'Yamaha India — Dealer Portal Phase 2', prov: 'Typed', conf: null },
  { label: 'Venue', value: 'YMSLI Faridabad', prov: 'Derived', conf: 92 },
  { label: 'Attendees', value: 'R. Mehta, C. Nihalani, G. Kumar, A. Sharma', prov: 'Typed', conf: null },
  { label: 'Date', value: '14 Aug 2026', prov: 'Derived', conf: 76 },
  { label: 'Purpose statement', value: 'Kickoff for Dealer Portal Phase 2 delivery scope.', prov: 'AI-drafted', conf: 71 },
  { label: 'Decisions summary', value: 'Three decisions recorded; two actions assigned.', prov: 'AI-drafted', conf: 84 },
  { label: 'Distribution list', value: 'Unchanged from template', prov: 'Unchanged', conf: null },
  { label: 'Confidentiality', value: 'Unchanged from template', prov: 'Unchanged', conf: null },
]

/**
 * Maps a document region onto the agent question that supplies it. `q: 9` is a
 * question index no conversation reaches — those regions stay `Unchanged`,
 * which is the fail-safe the region taxonomy calls for.
 */

/**
 * Maps a document region onto the agent question that supplies it. `q: 9` is a
 * question index no conversation reaches — those regions stay `Unchanged`,
 * which is the fail-safe the region taxonomy calls for.
 */
export const FIELD_MAP: {
  label: string
  q: number
  kind: 'typed' | 'derived' | 'ai' | 'unchanged'
  derive?: (v: string) => string
  fallback?: string
}[] = [
  { label: 'Title', q: 0, kind: 'typed' },
  { label: 'Client & project', q: 1, kind: 'typed' },
  { label: 'Venue', q: 1, kind: 'derived', derive: () => 'YMSLI Faridabad' },
  { label: 'Attendees', q: 2, kind: 'typed' },
  { label: 'Date', q: 3, kind: 'typed' },
  { label: 'Purpose statement', q: 1, kind: 'ai', derive: () => 'Kickoff for Dealer Portal Phase 2 delivery scope.' },
  { label: 'Distribution list', q: 9, kind: 'unchanged', fallback: 'Unchanged from template' },
  { label: 'Confidentiality', q: 9, kind: 'unchanged', fallback: 'Unchanged from template' },
]

export const EXTRACTED: { key: string; value: string }[][] = [
  [{ key: 'type', value: 'Minutes of Meeting' }, { key: 'phase', value: 'Kickoff' }],
  [{ key: 'client', value: 'Yamaha India' }, { key: 'project', value: 'Dealer Portal P2' }, { key: 'venue', value: 'YMSLI Faridabad' }],
  [{ key: 'attendees', value: '4' }, { key: 'chair', value: 'R. Mehta' }],
  [{ key: 'date', value: '14 Aug 2026' }, { key: 'period', value: 'Sprint 6' }],
]

export const AGENT_QS = [
  { label: 'Title', ask: 'What should we call this document?', placeholder: 'e.g. MOM — Dealer Portal kickoff' },
  { label: 'Client & project', ask: 'Which client and project is this for?', placeholder: 'e.g. Yamaha India — Dealer Portal Phase 2' },
  { label: 'Attendees', ask: 'Who attended, or who owns this document?', placeholder: 'e.g. R. Mehta, C. Nihalani, G. Kumar' },
  { label: 'Date', ask: 'What date or period does it cover?', placeholder: 'e.g. 12 August 2026' },
]

export const VERSIONS = [
  { n: '4.2', when: '2 days ago', author: 'Chahat N.', note: 'Added decision owner column to the actions table.' },
  { n: '4.1', when: '12 Jun 2026', author: 'Chahat N.', note: 'Confidentiality notice reworded for external sharing.' },
  { n: '4.0', when: '3 Mar 2026', author: 'Delivery PMO', note: 'Restructured around decisions rather than discussion notes.' },
  { n: '3.4', when: '18 Nov 2025', author: 'R. Mehta', note: 'Minor formatting fixes to the header block.' },
]

export const PREVIEW_LINES = [
  { h: '11px', w: '42%', mb: '18px' },
  { h: '9px', w: '100%', mb: '9px' },
  { h: '9px', w: '96%', mb: '9px' },
  { h: '9px', w: '88%', mb: '22px' },
  { h: '11px', w: '34%', mb: '18px' },
  { h: '9px', w: '100%', mb: '9px' },
  { h: '9px', w: '92%', mb: '9px' },
  { h: '9px', w: '76%', mb: '22px' },
  { h: '9px', w: '100%', mb: '9px' },
  { h: '9px', w: '64%', mb: '0' },
]

export const QA_CHECKS = [
  { name: 'Placeholder sweep', detail: 'No unfilled {{ }} tokens remain.', state: 'Pass' },
  { name: 'Merged ranges intact', detail: '27 of 27 preserved.', state: 'Pass' },
  { name: 'Date consistency', detail: 'Header date differs from the action-item due dates.', state: 'Warn' },
  { name: 'Formula integrity', detail: '0 formulas touched.', state: 'Pass' },
  { name: 'Heading structure', detail: 'Matches template v4.2 outline.', state: 'Pass' },
]

export const TIER_NOTES: Record<string, string> = {
  T1: 'T1 — fills only what you type, no inference.',
  T2: 'T2 — infers project context from your answers.',
  T3: 'T3 — pulls from past documents and project data.',
}

export const TIER_SUMMARY: Record<string, string> = {
  T1: 'no inference',
  T2: 'context inference',
  T3: 'past documents and project data',
}
