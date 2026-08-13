/**
 * Seed data, lifted from the design prototype's script block. This stands in
 * for `/api/v1` — every consumer goes through `src/services/`, so swapping a
 * slice of this for real fetch calls touches one layer.
 *
 * The backend (as of this writing) only implements template upload and
 * fetch-by-id (see `src/services/templates.ts`, wired into Upload.tsx and
 * Admin.tsx's "Verify" action). Everything else this file backs — template
 * listing/search, categories, versions, generation sessions, QA, drift,
 * analytics, ACL — has no backend route yet, so it stays mocked here until
 * those endpoints exist.
 */

export type Fmt = 'DOC' | 'XLS' | 'PPT'

export interface Template {
  id: number
  name: string
  category: string
  group: string
  fmt: Fmt
  owner: string
  version: string
  uses: number
  updated: string
  desc: string
}

export interface MyDoc {
  id: string
  name: string
  template: string
  version: string
  fmt: Fmt
  ext: string
  size: string
  created: string
  status: string
  kind: string
  isDraft?: boolean
  templateId?: number
  answers?: string[]
}

export interface Region {
  n: number
  name: string
  meta: string
  status: 'Fillable' | 'Protected'
  top: string
  left: string
  width: string
  height: string
}

export const TEMPLATES: Template[] = [
  { id: 1, name: 'Minutes of Meeting — Client', category: 'Functional', group: 'MOM', fmt: 'DOC', owner: 'Delivery PMO', version: '4.2', uses: 214, updated: '2 days ago', desc: 'Agenda, attendees, decisions and action items for external meetings.' },
  { id: 2, name: 'Project Plan — Fixed Bid', category: 'Functional', group: 'Plans', fmt: 'XLS', owner: 'Delivery PMO', version: '3.0', uses: 168, updated: '1 week ago', desc: 'Phase-wise schedule with milestones, effort and dependency tracking.' },
  { id: 3, name: 'Technical Design Document (HLD)', category: 'Technical', group: 'Design', fmt: 'DOC', owner: 'Architecture', version: '6.1', uses: 143, updated: '3 days ago', desc: 'System context, component breakdown, interfaces and NFRs.' },
  { id: 4, name: 'API Specification', category: 'Technical', group: 'API', fmt: 'DOC', owner: 'Architecture', version: '2.4', uses: 131, updated: 'yesterday', desc: 'Endpoint contracts, payload schemas, error codes and auth model.' },
  { id: 5, name: 'Test Script & UAT Sign-off', category: 'Technical', group: 'Testing', fmt: 'XLS', owner: 'Quality', version: '5.3', uses: 127, updated: '5 days ago', desc: 'Test case matrix with steps, expected results and sign-off block.' },
  { id: 6, name: 'Client Proposal Deck', category: 'Functional', group: 'Proposal', fmt: 'PPT', owner: 'Pre-sales', version: '8.0', uses: 96, updated: '2 weeks ago', desc: 'Solution narrative, approach, team and commercials in YMSLI livery.' },
  { id: 7, name: 'Statement of Work', category: 'Functional', group: 'Proposal', fmt: 'DOC', owner: 'Legal & Delivery', version: '3.7', uses: 88, updated: '1 month ago', desc: 'Scope, deliverables, assumptions and acceptance criteria.' },
  { id: 8, name: 'Integration Design — SAP', category: 'Technical', group: 'Design', fmt: 'DOC', owner: 'Architecture', version: '2.2', uses: 74, updated: '4 days ago', desc: 'IDoc and OData mappings, error handling and reconciliation.' },
  { id: 9, name: 'Minutes of Meeting — Internal', category: 'Functional', group: 'MOM', fmt: 'DOC', owner: 'Delivery PMO', version: '2.9', uses: 71, updated: '6 days ago', desc: 'Lightweight format for stand-ups and internal reviews.' },
  { id: 10, name: 'Estimation Sheet', category: 'Functional', group: 'Plans', fmt: 'XLS', owner: 'Pre-sales', version: '4.4', uses: 63, updated: '3 weeks ago', desc: 'Bottom-up effort model with role mix and contingency.' },
  { id: 11, name: 'Runbook — Production Support', category: 'Technical', group: 'Design', fmt: 'DOC', owner: 'Managed Services', version: '1.8', uses: 52, updated: '1 week ago', desc: 'Escalation paths, health checks and recovery procedures.' },
  { id: 12, name: 'Steering Committee Update', category: 'Functional', group: 'MOM', fmt: 'PPT', owner: 'Delivery PMO', version: '3.1', uses: 44, updated: '2 weeks ago', desc: 'Monthly status, risks, decisions needed and next milestones.' },
]

export const CATS = ['All', 'Functional', 'Technical', 'MOM', 'Plans', 'Proposal', 'Design', 'Testing', 'API']

export const MYDOCS: MyDoc[] = [
  { id: '1', name: 'MOM — Dealer Portal kickoff', template: 'Minutes of Meeting — Client', version: '4.2', fmt: 'DOC', ext: '.docx', size: '86 KB', created: 'Today, 10:24', status: 'Draft', kind: 'Word' },
  { id: '2', name: 'HLD — Dealer Portal Phase 2', template: 'Technical Design Document (HLD)', version: '6.1', fmt: 'DOC', ext: '.docx', size: '412 KB', created: 'Yesterday', status: 'Final', kind: 'Word' },
  { id: '3', name: 'UAT Test Script — Payments', template: 'Test Script & UAT Sign-off', version: '5.3', fmt: 'XLS', ext: '.xlsx', size: '204 KB', created: '11 Aug 2026', status: 'In review', kind: 'Excel' },
  { id: '4', name: 'SOW — Phase 2', template: 'Statement of Work', version: '3.7', fmt: 'DOC', ext: '.docx', size: '128 KB', created: '8 Aug 2026', status: 'Approved', kind: 'Word' },
  { id: '5', name: 'Steering update — July', template: 'Steering Committee Update', version: '3.1', fmt: 'PPT', ext: '.pptx', size: '2.4 MB', created: '2 Aug 2026', status: 'Final', kind: 'PowerPoint' },
  { id: '6', name: 'Estimation — Dealer Portal', template: 'Estimation Sheet', version: '4.4', fmt: 'XLS', ext: '.xlsx', size: '96 KB', created: '28 Jul 2026', status: 'Draft', kind: 'Excel' },
  { id: '7', name: 'API spec — Payments v1', template: 'API Specification', version: '2.4', fmt: 'DOC', ext: '.docx', size: '173 KB', created: '21 Jul 2026', status: 'Approved', kind: 'Word' },
]

export const SUBMISSIONS = [
  { id: 1, name: 'Vendor Assessment Checklist', fmt: 'DOC' as Fmt, meta: '.docx · 148 KB · submitted today', note: 'Waiting on doc control', status: 'In process', kind: 'In process' },
  { id: 2, name: 'Sprint Retrospective Notes', fmt: 'DOC' as Fmt, meta: '.docx · 92 KB · submitted 9 Aug 2026', note: 'Approved by Chahat N. · published as v1.0', status: 'Approved', kind: 'Approved' },
  { id: 3, name: 'Migration Cutover Plan', fmt: 'XLS' as Fmt, meta: '.xlsx · 316 KB · submitted 5 Aug 2026', note: 'Sent back: add rollback section', status: 'Rejected', kind: 'Rejected' },
  { id: 4, name: 'Client Onboarding Deck', fmt: 'PPT' as Fmt, meta: '.pptx · 4.1 MB · submitted 1 Aug 2026', note: 'Approved by Gaurav K. · published as v1.0', status: 'Approved', kind: 'Approved' },
  { id: 5, name: 'Data Migration Test Log', fmt: 'XLS' as Fmt, meta: '.xlsx · 88 KB · submitted 28 Jul 2026', note: 'In review with Quality', status: 'In process', kind: 'In process' },
]

export const QUEUE = [
  { id: 1, name: 'Vendor Assessment Checklist', fmt: 'DOC' as Fmt, meta: '.docx · 148 KB · submitted today', note: 'Queued for parsing', status: 'Uploaded', kind: 'In process' },
  { id: 6, name: 'Change Request Form', fmt: 'DOC' as Fmt, meta: '.docx · 112 KB · submitted today', note: 'Text and tables extracted', status: 'Parsed', kind: 'In process' },
  { id: 7, name: 'Release Checklist', fmt: 'XLS' as Fmt, meta: '.xlsx · 74 KB · submitted today', note: '22 fillable, 5 protected regions found', status: 'Regions detected', kind: 'In process' },
  { id: 5, name: 'Data Migration Test Log', fmt: 'XLS' as Fmt, meta: '.xlsx · 88 KB · submitted 28 Jul 2026', note: 'Ready for doc control sign-off', status: 'Awaiting review', kind: 'In process' },
  { id: 2, name: 'Sprint Retrospective Notes', fmt: 'DOC' as Fmt, meta: '.docx · 92 KB · submitted 9 Aug 2026', note: 'Published as v1.0 by Chahat N.', status: 'Published', kind: 'Approved' },
  { id: 3, name: 'Migration Cutover Plan', fmt: 'XLS' as Fmt, meta: '.xlsx · 316 KB · submitted 5 Aug 2026', note: 'Parser could not read 4 merged ranges', status: 'Failed', kind: 'Rejected' },
]

export const REGIONS: Region[] = [
  { n: 1, name: 'Document header', meta: 'Client, project, document number', status: 'Fillable', top: '62px', left: '26px', width: '46%', height: '30px' },
  { n: 2, name: 'Attendees table', meta: 'Names, roles and organisation', status: 'Fillable', top: '104px', left: '26px', width: '88%', height: '44px' },
  { n: 3, name: 'Confidentiality notice', meta: 'Locked by doc control', status: 'Protected', top: '158px', left: '26px', width: '62%', height: '26px' },
  { n: 4, name: 'Decisions and actions', meta: 'One row per action, with owner and date', status: 'Fillable', top: '194px', left: '26px', width: '88%', height: '52px' },
  { n: 5, name: 'Approval block', meta: 'Signature grid, fixed layout', status: 'Protected', top: '258px', left: '26px', width: '54%', height: '30px' },
]

export const VERSIONS = [
  { n: '4.2', when: '2 days ago', author: 'Chahat N.', note: 'Added decision owner column to the actions table.' },
  { n: '4.1', when: '12 Jun 2026', author: 'Chahat N.', note: 'Confidentiality notice reworded for external sharing.' },
  { n: '4.0', when: '3 Mar 2026', author: 'Delivery PMO', note: 'Restructured around decisions rather than discussion notes.' },
  { n: '3.4', when: '18 Nov 2025', author: 'R. Mehta', note: 'Minor formatting fixes to the header block.' },
]

export const SEED_DRAFTS = [
  { id: 'd1', title: 'MOM — Weekly delivery sync', templateId: 9, fmt: 'DOC' as Fmt, answers: ['MOM — Weekly delivery sync', 'Yamaha India — Dealer Portal Phase 2'], saved: 'Saved yesterday' },
  { id: 'd2', title: 'API spec — Notifications service', templateId: 4, fmt: 'DOC' as Fmt, answers: ['API spec — Notifications service'], saved: 'Saved 9 Aug 2026' },
]

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

export const SCHEMA_ROWS = [
  { name: 'Document header', type: 'Text block', behaviour: 'Fillable', def: '{{ client }} — {{ project }}', auto: true },
  { name: 'Attendees table', type: 'Table', behaviour: 'Fillable', def: 'Empty, 4 rows', auto: true },
  { name: 'Confidentiality notice', type: 'Text block', behaviour: 'Protected', def: 'Standard YMSLI notice', auto: false },
  { name: 'Decisions and actions', type: 'Table', behaviour: 'Fillable', def: 'Empty, 6 rows', auto: true },
  { name: 'Approval block', type: 'Signature grid', behaviour: 'Protected', def: 'Two signatories', auto: false },
  { name: 'Footer', type: 'Text', behaviour: 'Protected', def: 'Page number and version', auto: true },
]

export const ACCESS_GROUPS = [
  { name: 'All employees', view: true, gen: false, admin: false, members: '2,140' },
  { name: 'Delivery', view: true, gen: true, admin: false, members: '318' },
  { name: 'Architecture', view: true, gen: true, admin: false, members: '64' },
  { name: 'Quality', view: true, gen: true, admin: false, members: '87' },
  { name: 'Doc control', view: true, gen: true, admin: true, members: '6' },
  { name: 'Contractors', view: true, gen: false, admin: false, members: '52' },
]

export const SUB_FILTERS = ['All', 'In process', 'Approved', 'Rejected']
export const DOC_FILTERS = ['All', 'Word', 'Excel', 'PowerPoint', 'Draft', 'Approved']

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

export const NOTIFICATIONS = [
  { text: 'Technical Design Document (HLD) updated to v6.1 by Architecture.', time: '10 minutes ago' },
  { text: 'Your draft "MOM — Dealer Portal kickoff" is ready to review.', time: '1 hour ago' },
  { text: 'Approval requested: Estimation Sheet v4.5 from Pre-sales.', time: '3 hours ago' },
  { text: 'New template published: Runbook — Production Support.', time: 'Yesterday' },
  { text: 'Your document "SOW — Phase 2" was approved by Legal.', time: '2 days ago' },
]

export const SEARCH_EXAMPLES = [
  'test script for a payment API',
  'client kickoff meeting notes',
  'high-level design for an integration',
]

export const ROLE_PACKS = [
  { name: 'Delivery PMO', fmt: 'PMO', when: '18 templates', q: 'Delivery PMO' },
  { name: 'Architect', fmt: 'ARC', when: '31 templates', q: 'Architecture' },
  { name: 'QA Lead', fmt: 'QA', when: '24 templates', q: 'Quality' },
  { name: 'Pre-sales', fmt: 'PRE', when: '19 templates', q: 'Pre-sales' },
  { name: 'New joiner', fmt: 'NEW', when: '12 templates', q: 'Minutes' },
]

/* ── Analytics ─────────────────────────────────────────────────────────── */

const mkSeries = (pts: number[]) => {
  const n = pts.length
  const max = Math.max(...pts)
  const xy = pts.map((p, i) => [(i / (n - 1)) * 600, 170 - (p / max) * 150])
  const line = xy.map(([x, y], i) => (i ? 'L' : 'M') + x.toFixed(1) + ' ' + y.toFixed(1)).join(' ')
  return { line, area: line + ' L600 180 L0 180 Z' }
}

export const SERIES: Record<string, { line: string; area: string }> = {
  '30d': mkSeries([22, 26, 24, 31, 29, 35, 33, 40, 38, 44, 47, 43, 52, 55, 51, 58]),
  '90d': mkSeries([14, 18, 17, 24, 22, 29, 33, 31, 38, 42, 40, 47, 52, 49, 56, 58, 55, 61]),
  '12m': mkSeries([6, 9, 12, 11, 17, 21, 26, 24, 33, 39, 44, 52]),
}

export const STAT_TILES = [
  { value: '1,482', label: 'Documents generated', delta: '+18% vs last month' },
  { value: '128', label: 'Templates published', delta: '9 added this quarter' },
  { value: '341', label: 'Active users', delta: '62% of eligible staff' },
  { value: '4m 12s', label: 'Median time to document', delta: 'was 46m before the hub' },
]

export const STALE_TEMPLATES = [
  { name: 'Client Proposal Deck', owner: 'Pre-sales', updated: '2 weeks ago', uses: 96 },
  { name: 'Statement of Work', owner: 'Legal & Delivery', updated: '1 month ago', uses: 88 },
  { name: 'Estimation Sheet', owner: 'Pre-sales', updated: '3 weeks ago', uses: 63 },
  { name: 'Steering Committee Update', owner: 'Delivery PMO', updated: '2 weeks ago', uses: 44 },
  { name: 'Runbook — Production Support', owner: 'Managed Services', updated: '1 week ago', uses: 52 },
]

export const NEVER_USED = [
  { name: 'Legacy Handover Note', meta: 'Published Mar 2025 · Managed Services' },
  { name: 'Vendor Scorecard (old)', meta: 'Published Nov 2024 · Procurement' },
  { name: 'Weekly Status — long form', meta: 'Published Jan 2025 · Delivery PMO' },
  { name: 'Risk Register v1', meta: 'Published Sep 2024 · Quality' },
]

export const SEARCH_GAPS = [
  { query: 'data privacy impact assessment', searches: 84, people: 41 },
  { query: 'cloud migration runbook', searches: 62, people: 33 },
  { query: 'vendor security questionnaire', searches: 55, people: 29 },
  { query: 'incident postmortem template', searches: 47, people: 26 },
  { query: 'API deprecation notice', searches: 31, people: 18 },
  { query: 'training handover checklist', searches: 24, people: 15 },
]

export const LATENCY_STATS = [
  { label: 'Median generation time', value: '11.4s' },
  { label: 'p95 generation time', value: '38.2s' },
  { label: 'Average cost per document', value: '₹6.20' },
  { label: 'Total this month', value: '₹9,188' },
]

export const QA_CHECKS = [
  { name: 'Placeholder sweep', detail: 'No unfilled {{ }} tokens remain.', state: 'Pass' },
  { name: 'Merged ranges intact', detail: '27 of 27 preserved.', state: 'Pass' },
  { name: 'Date consistency', detail: 'Header date differs from the action-item due dates.', state: 'Warn' },
  { name: 'Formula integrity', detail: '0 formulas touched.', state: 'Pass' },
  { name: 'Heading structure', detail: 'Matches template v4.2 outline.', state: 'Pass' },
]

export const RANGE_LABELS: Record<string, [string, string]> = {
  '30d': ['15 Jul 2026', '13 Aug 2026'],
  '90d': ['15 May 2026', '13 Aug 2026'],
  '12m': ['Aug 2025', 'Aug 2026'],
}

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

export const statusClass = (st: string) =>
  st === 'Approved' || st === 'Final'
    ? 'tag tag-accent'
    : st === 'Rejected'
      ? 'tag tag-accent-2'
      : 'tag tag-neutral'
