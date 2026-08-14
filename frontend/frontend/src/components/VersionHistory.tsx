import { useEffect, useState } from 'react'
import {
  getVersionHistory,
  type VersionHistory as History,
  type VersionRow,
} from '@/services/versions'
import { formatBytes } from '@/lib/utils'
import { Tag } from '@/components/ui/tag'
import { Panel, SectionLabel } from '@/components/ui/table'

/**
 * Every version of a template, newest first, with what each one changed.
 *
 * The change detail is derived from the `change_spec` the backend stored when
 * the version was compiled — which regions were written, what went into them
 * and where the value came from. It reports **what was written, not what was
 * overwritten**: specs record new values, and the previous contents of a region
 * are not stored anywhere. The wording below says "set to" rather than
 * "changed from", deliberately, so the UI never implies a before/after it
 * cannot show.
 */
export function VersionHistory({ templateId }: { templateId: string }) {
  const [history, setHistory] = useState<History | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    getVersionHistory(templateId)
      .then((result) => {
        if (!cancelled) {
          setHistory(result)
          setError(null)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Could not load history.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [templateId])

  if (loading) return <Panel><p className="text-[12.5px] opacity-55">Loading history…</p></Panel>
  if (error) return <Panel><p className="text-[12.5px] opacity-70">{error}</p></Panel>
  if (!history || !history.versions.length) return null

  return (
    <Panel>
      <SectionLabel>Version history</SectionLabel>
      <div className="flex flex-col gap-[2px] mt-[10px]">
        {history.versions.map((v) => (
          <VersionRowView
            key={v.id}
            version={v}
            expanded={open === v.id}
            onToggle={() => setOpen(open === v.id ? null : v.id)}
          />
        ))}
      </div>
    </Panel>
  )
}

function statusTag(v: VersionRow) {
  // `Current` beats `Approved`: of many approved versions exactly one is the
  // file the library hands out, and that is the fact a reader is looking for.
  if (v.is_current) return { label: 'Current', variant: 'accent' as const }
  switch (v.approval_status) {
    case 'pending':
      return { label: 'Awaiting review', variant: 'accent2' as const }
    case 'rejected':
      return { label: 'Rejected', variant: 'accent2' as const }
    default:
      return { label: 'Approved', variant: 'neutral' as const }
  }
}

function VersionRowView({
  version,
  expanded,
  onToggle,
}: {
  version: VersionRow
  expanded: boolean
  onToggle: () => void
}) {
  const tag = statusTag(version)
  const created = new Date(version.created_at).toLocaleString()

  return (
    <div className="border-b border-white/5 last:border-0 py-[10px]">
      <button
        type="button"
        onClick={onToggle}
        className="w-full flex items-center gap-3 flex-wrap text-left"
      >
        <span className="font-semibold text-[13px] whitespace-nowrap">v{version.version_number}</span>
        <Tag variant={tag.variant} className="whitespace-nowrap flex-none">
          {tag.label}
        </Tag>
        <span className="text-[12px] opacity-60 flex-[1_1_180px] min-w-[140px]">
          {version.summary}
          {version.submitted_by_name ? ` · ${version.submitted_by_name}` : ''}
        </span>
        <span className="text-[11.5px] opacity-45 whitespace-nowrap">{created}</span>
      </button>

      {/* Drift, detectable without opening either file: the document's own
          `Ver.` disagrees with the number the hub gave it. */}
      {version.claims_stale_version ? (
        <p className="text-[11.5px] opacity-70 mt-[6px]">
          This file calls itself Ver. {version.in_doc_version}, but the hub has it as v
          {version.version_number}.
        </p>
      ) : null}

      {expanded ? (
        <div className="mt-[10px] flex flex-col gap-[10px] pl-[2px]">
          {version.intent ? (
            <p className="text-[12px] opacity-70">“{version.intent}”</p>
          ) : null}

          {/* The reviewer's own words. Shown for an approval too, not just a
              rejection: "why was this published" is as much a part of the
              history as "why was this refused". */}
          {version.review_note ? (
            <p className="text-[12px]">
              <span className="opacity-50">
                {version.approval_status === 'rejected' ? 'Rejected' : 'Approved'}
                {version.reviewed_by_name ? ` by ${version.reviewed_by_name}` : ''} —{' '}
              </span>
              {version.review_note}
            </p>
          ) : null}

          {version.changed.length ? (
            <div>
              <div className="text-[11.5px] opacity-50 mb-[4px]">Regions written</div>
              <div className="flex flex-col gap-[4px]">
                {version.changed.map((c) => (
                  <div key={c.region_id} className="text-[12px] flex gap-2 flex-wrap">
                    <span className="font-semibold">{c.label || c.region_id}</span>
                    <span className="opacity-70">
                      {c.rows_written !== null
                        ? `${c.rows_written} row${c.rows_written === 1 ? '' : 's'} written`
                        : `set to “${c.value ?? ''}”`}
                    </span>
                    {c.provenance ? (
                      <Tag variant="neutral" className="whitespace-nowrap flex-none">
                        {c.provenance}
                      </Tag>
                    ) : null}
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-[12px] opacity-55">
              {version.origin === 'upload'
                ? 'Uploaded as a new document — there is no change record for an upload.'
                : 'No regions were written.'}
            </p>
          )}

          {version.dropped.length ? (
            <div>
              <div className="text-[11.5px] opacity-50 mb-[4px]">Not applied</div>
              {version.dropped.map((d, i) => (
                <div key={`${d.target}-${i}`} className="text-[12px] opacity-70">
                  {d.target}: {d.reason}
                </div>
              ))}
            </div>
          ) : null}

          {version.protected_regions.length ? (
            <p className="text-[11.5px] opacity-55">
              {version.protected_regions.length} protected region
              {version.protected_regions.length === 1 ? '' : 's'} were never written.
            </p>
          ) : null}

          <div className="flex items-center gap-3 flex-wrap text-[11.5px] opacity-55">
            <span>{formatBytes(version.size_bytes)}</span>
            {version.qa_overall ? <span>QA {version.qa_overall}</span> : null}
            {version.download_url ? (
              <a className="underline" href={version.download_url}>
                Download
              </a>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  )
}
