/**
 * UI vocabulary — the fixed words the interface is built from.
 *
 * This file replaces the old `mock.ts`, which seeded the whole app with
 * invented templates, documents, submissions, approval queues, version
 * histories and analytics. All of that is gone: every template and document
 * the app shows now comes from the backend (`services/templates.ts`), and
 * anything the backend can't answer for yet shows an empty state rather than
 * a fabricated one.
 *
 * What's left here is genuinely static: format labels, filter options and the
 * status-pill mapping. Nothing in this file claims a document exists.
 */

export type Fmt = 'DOC' | 'XLS' | 'PPT'

/** Categories offered when submitting a template. */
export const CATS = ['All', 'Functional', 'Technical', 'MOM', 'Plans', 'Proposal', 'Design', 'Testing', 'API']

/** Prompts under the Discovery search box — phrasing hints, not results. */
export const SEARCH_EXAMPLES = [
  'minutes of meeting for a client kickoff',
  'test script for a payment API',
  'high level design for an integration',
  'statement of work for a fixed-bid project',
]

export const statusClass = (st: string) =>
  st === 'Approved' || st === 'Final' || st === 'Published'
    ? 'pill pill-ok'
    : st === 'Rejected'
      ? 'pill pill-bad'
      : 'pill pill-warn'
