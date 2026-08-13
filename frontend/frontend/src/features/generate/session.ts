import { AGENT_QS, FIELD_MAP, type Template } from '@/data/mock'
import type { ChangeOperation, ChangeSpec, ParsedDocument, ProvenanceKind } from '@/features/preview/types'
import { extOf } from '@/lib/utils'

/** Region ids are stable and schema-owned — the planner may target nothing else. */
export const REGION_ID: Record<string, string> = {
  Title: 'doc.title',
  'Client & project': 'doc.client_project',
  Venue: 'doc.venue',
  Attendees: 'doc.attendees',
  Date: 'doc.date',
  'Purpose statement': 'doc.purpose',
  'Distribution list': 'doc.distribution',
  Confidentiality: 'doc.confidentiality',
}

/**
 * The parsed schema of the stored original. In production this arrives from
 * `GET /templates/{id}/regions`; the shape is identical either way, so nothing
 * downstream changes when the ingestion pipeline replaces this.
 */
export function parseTemplate(template: Template): ParsedDocument {
  // `Confidentiality` is defined below as a protected region instead — doc
  // control owns its wording, so it is never a fillable field.
  const fields = FIELD_MAP.filter((f) => f.label !== 'Confidentiality').map((f) => ({
    regionId: REGION_ID[f.label],
    label: f.label,
    kind: (f.label === 'Attendees' ? 'table_loop' : 'field') as 'table_loop' | 'field',
    locator: { sheet: 'Sheet1', ref: '' },
    content: f.fallback ?? '',
    editable: f.kind !== 'unchanged',
    protected: false,
  }))

  return {
    versionId: `tpl-${template.id}-v${template.version}`,
    title: `${template.name} — untitled`,
    subtitle: `${template.name} v${template.version} · Yamaha Motor Solutions India`,
    regions: [
      {
        regionId: 'doc.branding',
        label: 'Branding block',
        kind: 'branding',
        locator: { sheet: 'Sheet1', ref: 'A1:G2' },
        content: 'YMSLI logo · sensitivity label',
        editable: false,
        protected: true,
      },
      ...fields,
      {
        regionId: 'doc.confidentiality',
        label: 'Confidentiality notice',
        kind: 'immutable',
        locator: { sheet: 'Sheet1', ref: '' },
        content: 'Standard YMSLI notice',
        editable: false,
        protected: true,
      },
    ],
  }
}

const PROVENANCE: Record<string, ProvenanceKind> = {
  typed: 'typed',
  derived: 'derived',
  ai: 'ai',
  unchanged: 'unchanged',
}

/**
 * The Change Planner's output, built deterministically from the answers so far.
 *
 * `liveInput` is the text currently in the composer — it feeds the preview so
 * the document updates as the user types, without being committed as an answer.
 */
export function buildChangeSpec(
  template: Template,
  answers: string[],
  tier: 'T1' | 'T2' | 'T3',
  qIndex: number,
  liveInput = '',
): ChangeSpec {
  const operations: ChangeOperation[] = []

  for (const f of FIELD_MAP) {
    const answered = answers[f.q] !== undefined
    const live = f.q === qIndex ? liveInput.trim() : ''
    const source = answered ? answers[f.q] : live
    if (!source) continue

    // T1 fills only what the user typed; inference is off by contract.
    if (tier === 'T1' && f.kind !== 'typed') continue

    const value = f.kind === 'typed' ? source : f.derive ? f.derive(source) : source

    operations.push({
      op: 'set_value',
      regionId: REGION_ID[f.label],
      value,
      provenance: PROVENANCE[f.kind] ?? 'system',
    })
  }

  operations.push({
    op: 'protect',
    regionId: 'doc.branding',
    provenance: 'system',
    reason: 'branding_richvalue',
  })

  return {
    specVersion: '1.0',
    baseVersionId: `tpl-${template.id}-v${template.version}`,
    tier,
    operations,
  }
}

export const totalQuestions = AGENT_QS.length

/** The headline derivation metric: few answers, many filled regions. */
export const fieldsFilled = (answerCount: number) => 18 + answerCount * 2
export const FIELDS_TOTAL = 31

export const draftFileName = (title: string, fmt: Template['fmt']) => title + extOf(fmt)
