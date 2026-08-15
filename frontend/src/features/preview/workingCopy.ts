import { hash } from '@/lib/utils'
import type { ChangeSpec, ParsedDocument, ParsedRegion, WorkingCopy, WorkingRegion } from './types'

/**
 * Key for the render cache: `hash(base_version_id + change_spec)`.
 *
 * The spec is serialised with its operations sorted by region id so that two
 * conversations that arrive at the same document state — in a different answer
 * order — hit the same cached render instead of paying for it twice.
 */
export function specKey(spec: ChangeSpec): string {
  const canonical = JSON.stringify({
    base: spec.baseVersionId,
    tier: spec.tier,
    ops: [...spec.operations]
      .sort((a, b) => a.regionId.localeCompare(b.regionId))
      .map((o) => [o.op, o.regionId, o.value ?? '', o.rows ?? []]),
  })
  return hash(spec.baseVersionId + '|' + canonical)
}

/**
 * Applies a Change Spec to an **in-memory** copy of the parsed original.
 *
 * `original` is treated as frozen: every region is cloned before a write lands
 * on it, so the stored version the rest of the app reads from is never touched
 * no matter how many times the user revises an answer. Operations targeting a
 * protected region are refused rather than applied, and surface in
 * `refused` so the review screen can show what the compiler declined to do.
 */
export function applySpec(original: ParsedDocument, spec: ChangeSpec): WorkingCopy {
  const byId = new Map<string, ParsedRegion>(original.regions.map((r) => [r.regionId, r]))
  const regions: WorkingRegion[] = original.regions.map((r) => ({
    ...r,
    rows: r.rows ? r.rows.map((row) => ({ ...row })) : undefined,
    changed: false,
    provenance: 'unchanged',
  }))
  const index = new Map(regions.map((r, i) => [r.regionId, i]))
  const refused: WorkingCopy['refused'] = []

  for (const op of spec.operations) {
    // Hard rule: the planner may only target regions present in the schema.
    if (!byId.has(op.regionId)) continue

    const i = index.get(op.regionId)!
    const region = regions[i]

    if (region.protected || !region.editable) {
      refused.push({
        regionId: op.regionId,
        reason: region.protected ? 'Region is protected' : 'Region is not editable',
      })
      continue
    }

    switch (op.op) {
      case 'set_value':
        if (op.value === undefined) break
        regions[i] = { ...region, content: op.value, changed: true, provenance: op.provenance }
        break
      case 'replace_region_rows':
        regions[i] = { ...region, rows: (op.rows ?? []).map((r) => ({ ...r })), changed: true, provenance: op.provenance }
        break
      case 'clone_table_rows':
        regions[i] = {
          ...region,
          rows: [...(region.rows ?? []), ...(op.rows ?? []).map((r) => ({ ...r }))],
          changed: true,
          provenance: op.provenance,
        }
        break
      case 'clear_region':
        regions[i] = { ...region, content: '', rows: [], changed: true, provenance: op.provenance }
        break
      case 'protect':
        // No-op against the working copy; recorded for the protected-regions report.
        break
    }
  }

  return { baseVersionId: spec.baseVersionId, specHash: specKey(spec), regions, refused }
}
