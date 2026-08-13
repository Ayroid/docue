/**
 * The Change Specification contract (Implementation Plan §3.2).
 *
 * The agent emits operations; deterministic code applies them. Nothing here
 * carries markup, file paths or formulas — only enumerated ops over region ids
 * that already exist in the parsed document schema.
 */

export type OpKind = 'set_value' | 'replace_region_rows' | 'clone_table_rows' | 'clear_region' | 'protect'

export type ProvenanceKind = 'typed' | 'derived' | 'ai' | 'unchanged' | 'system'

export interface ChangeOperation {
  op: OpKind
  /** Must reference a region present in the parsed schema; unknown ids are dropped. */
  regionId: string
  value?: string
  rows?: Record<string, string>[]
  provenance: ProvenanceKind
  reason?: string
}

export interface ChangeSpec {
  specVersion: '1.0'
  baseVersionId: string
  tier: 'T1' | 'T2' | 'T3'
  operations: ChangeOperation[]
}

export type RegionKind = 'field' | 'table_loop' | 'table_data' | 'branding' | 'immutable'

export interface ParsedRegion {
  regionId: string
  label: string
  kind: RegionKind
  /** Sheet/cell locator, kept opaque to the UI — it round-trips to the compiler. */
  locator: { sheet?: string; ref?: string }
  /** Current content of the stored original. Never mutated. */
  content: string
  columns?: string[]
  rows?: Record<string, string>[]
  editable: boolean
  protected: boolean
}

export interface ParsedDocument {
  versionId: string
  title: string
  subtitle: string
  regions: ParsedRegion[]
}

/** A region after the spec has been applied, carrying what changed and why. */
export interface WorkingRegion extends ParsedRegion {
  changed: boolean
  provenance: ProvenanceKind
}

export interface WorkingCopy {
  baseVersionId: string
  specHash: string
  regions: WorkingRegion[]
  /** Ops the compiler refused because they targeted a protected region. */
  refused: { regionId: string; reason: string }[]
}

export type RenderStatus = 'idle' | 'rendering' | 'ready' | 'failed'

export interface RenderResult {
  key: string
  pngUrl: string
  renderedInMs: number
}
