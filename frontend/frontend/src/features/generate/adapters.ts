/**
 * The one translation point between the API and the preview types.
 *
 * The backend speaks contract C1 in snake_case with `target.region_id`; the
 * preview layer (`features/preview/types.ts`) speaks camelCase with a bare
 * `regionId`. Both are right for where they live, and the conversion is kept
 * here rather than sprinkled through the pages so a renamed field is one edit.
 *
 * This file replaces `parseTemplate()` and `buildChangeSpec()` from the old
 * `session.ts`. Those built a document and a spec out of fixtures; these read
 * the real ones. Everything downstream — `applySpec`, `useLivePreview`,
 * `LivePreviewPanel` — is unchanged, which is why the fast client-side preview
 * (Implementation Plan §5's ~80ms path) still works exactly as before.
 */

import type { ChangeOperation, ChangeSpec, OpKind, ParsedDocument, ParsedRegion, ProvenanceKind, RegionKind } from '@/features/preview/types'
import type { DocumentSchemaOut, RegionOut } from '@/services/templates'
import type { ServerChangeSpec, ServerOperation } from '@/services/sessions'

/* The detector's eleven kinds (Implementation Plan Appendix A) collapsed onto
   the five the preview draws differently. Anything unrecognised becomes
   `immutable`, which is the taxonomy's own fail-safe: an unclassified region is
   never written and never shown as fillable. */
const KIND_MAP: Record<string, RegionKind> = {
  field: 'field',
  field_empty: 'field',
  title: 'field',
  table_loop: 'table_loop',
  table_data: 'table_data',
  repeating_block: 'table_data',
  branding: 'branding',
  derived: 'immutable',
  history: 'immutable',
  instruction: 'immutable',
  immutable: 'immutable',
}

export function toRegionKind(kind: string): RegionKind {
  return KIND_MAP[kind] ?? 'immutable'
}

/**
 * `user_answer:q2` → `typed`, `llm_derived` → `derived`, and so on.
 *
 * The suffix after the colon names which question supplied the value; it is
 * dropped here because the badge is about *who* wrote a value, not which turn.
 */
export function toProvenance(provenance: string): ProvenanceKind {
  const root = provenance.split(':')[0]
  switch (root) {
    case 'user_answer':
      return 'typed'
    case 'llm_derived':
      return 'derived'
    case 'llm_generated':
      return 'ai'
    case 'system':
      return 'system'
    default:
      return 'unchanged'
  }
}

/** Column-keyed rows for the preview, from whatever the server sent. */
function toRows(op: ServerOperation): Record<string, string>[] | undefined {
  if (op.items) return op.items.map((item) => ({ content: item }))
  if (!op.rows) return undefined
  return op.rows.map((row) =>
    typeof row === 'string'
      ? { content: row }
      : Object.fromEntries(Object.entries(row).map(([k, v]) => [k, v == null ? '' : String(v)])),
  )
}

/* `set_text` is `set_value` under another name (the two formats spell it
   differently); `set_bullets` and `set_notes` are pptx-only and both land as
   row replacements in the preview, which draws a bullet list and a rewritten
   block the same way. */
const OP_MAP: Record<ServerOperation['op'], OpKind> = {
  set_value: 'set_value',
  set_text: 'set_value',
  clear_region: 'clear_region',
  clone_table_rows: 'clone_table_rows',
  replace_region_rows: 'replace_region_rows',
  set_bullets: 'replace_region_rows',
  set_notes: 'set_value',
  protect: 'protect',
}

export function toParsedRegion(region: RegionOut): ParsedRegion {
  const locator = region.locator as { sheet?: string; ref?: string }
  const columns = (region.notes?.columns as { name?: string }[] | undefined)
    ?.map((c) => c.name)
    .filter((n): n is string => Boolean(n))

  return {
    regionId: region.region_id,
    // The classifier's `semantic_role` is what a region is *for* and reads far
    // better than the detector's structural label; fall back through the label
    // to the id so a region is never nameless.
    label: region.label || region.semantic_role || region.region_id,
    kind: toRegionKind(region.kind),
    locator: { sheet: locator.sheet, ref: locator.ref },
    content: region.current_content ?? '',
    columns,
    editable: region.editable,
    protected: region.protected,
  }
}

/**
 * `GET /templates/{id}/regions` → the parsed document the preview renders.
 *
 * Regions come back in `sequence` order and are kept that way: `ordinal` is the
 * detector's own numbering and restarts at 0 per sheet, so sorting by it would
 * interleave a workbook's sheets.
 */
export function toParsedDocument(
  schema: DocumentSchemaOut,
  meta: { title: string; subtitle: string },
): ParsedDocument {
  return {
    versionId: schema.version_id,
    title: meta.title,
    subtitle: meta.subtitle,
    regions: schema.regions.map(toParsedRegion),
  }
}

/** `GET /sessions/{id}/spec` → the spec `applySpec` understands. */
export function toChangeSpec(spec: ServerChangeSpec): ChangeSpec {
  const operations: ChangeOperation[] = []

  for (const op of spec.operations) {
    const regionId = op.target.region_id
    // A ref-only target is legal in the contract but the preview keys
    // everything by region id, so it has nothing to attach to.
    if (!regionId) continue

    operations.push({
      op: OP_MAP[op.op] ?? 'set_value',
      regionId,
      value: op.text ?? (op.value == null ? undefined : String(op.value)),
      rows: toRows(op),
      provenance: toProvenance(op.provenance),
      reason: op.reason,
    })
  }

  return {
    specVersion: '1.0',
    baseVersionId: spec.base_version_id ?? '',
    tier: spec.tier,
    operations,
  }
}

/**
 * The preservation guarantees, from the compile response's structural report.
 *
 * Replaces a hardcoded string that read `logo · sensitivity label · 27 merged
 * ranges · 0 formulas touched` for every document regardless of what was in it.
 * Those were the MOM's numbers; on any other file they were decoration.
 */
export function preservationClaims(
  structural: Record<string, unknown>,
  protectedRegions: string[],
): string[] {
  const claims: string[] = []
  const lost = (structural.lost_parts as string[] | undefined) ?? []

  if (!lost.length) claims.push('0 package parts lost')
  else claims.push(`${lost.length} package part(s) LOST`)

  const before = structural.merged_ranges_before as number | undefined
  const after = structural.merged_ranges_after as number | undefined
  if (typeof before === 'number' && typeof after === 'number') {
    claims.push(before === after ? `${before} merged ranges intact` : `merged ranges ${before} → ${after}`)
  }

  if (protectedRegions.length) claims.push(`${protectedRegions.length} protected region(s) untouched`)
  return claims
}
