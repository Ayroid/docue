import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useHub } from '@/store/HubProvider'
import { preservationClaims, toChangeSpec, toParsedDocument } from '@/features/generate/adapters'
import { applySpec } from '@/features/preview/workingCopy'
import type { ChangeSpec, ParsedDocument, ProvenanceKind } from '@/features/preview/types'
import {
  commitSession,
  compileSession,
  getSession,
  getSpec,
  type CompileResponse,
  type DerivedValue,
  type SessionOut,
  type SpecOut,
} from '@/services/sessions'
import { getTemplate, getTemplateRegions, type TemplateOut } from '@/services/templates'
import { Button } from '@/components/ui/button'
import { Tag } from '@/components/ui/tag'
import { Panel, SectionLabel } from '@/components/ui/table'
import { EmptyState, PageBody, PageHeading } from '@/components/common'
import { CheckIcon } from '@/components/icons'

const PROV_LABEL: Record<ProvenanceKind, string> = {
  typed: 'Typed',
  context: 'From your notes',
  derived: 'Derived',
  ai: 'AI-drafted',
  unchanged: 'Unchanged',
  system: 'System',
}

const PROV_TAG_CLASS: Record<ProvenanceKind, string> = {
  typed: '',
  /* Solid, like `typed`. The dashed border means "nobody wrote this", and
     somebody did write this — just in a document they pasted rather than in
     answer to a question. */
  context: 'border border-accent2-900/35',
  derived: 'border border-dashed border-accent bg-transparent',
  ai: 'border border-dashed border-accent bg-accent-100 text-accent-900',
  unchanged: 'opacity-45',
  system: 'opacity-45',
}

const FMT_LABEL: Record<string, string> = { xlsx: 'XLS', docx: 'DOC', pptx: 'PPT' }

/**
 * Review & commit. Implementation Plan §5.
 *
 * Every number on this page is measured. The QA panel is the dry-run compile's
 * own structural and functional verdict; "Declined changes" is the compiler's
 * `dropped[]` with its real reasons; the preservation list is counted from the
 * structural report rather than asserted. All four used to be fixtures.
 *
 * The dry run happens on load, deliberately: the user should see the QA verdict
 * on the actual bytes *before* deciding to commit, not after. It keeps nothing.
 */
export function Review() {
  const { sessionId } = useParams()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  /* Carried from "Update Document" through Generate. See the buttons below. */
  const updatingTemplate = searchParams.get('mode') === 'version'
  const { commitSession: recordDocument, fireToast } = useHub()

  const [session, setSession] = useState<SessionOut | null>(null)
  const [template, setTemplate] = useState<TemplateOut | null>(null)
  const [original, setOriginal] = useState<ParsedDocument | null>(null)
  const [specBody, setSpecBody] = useState<SpecOut | null>(null)
  const [qa, setQa] = useState<CompileResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [committing, setCommitting] = useState(false)

  useEffect(() => {
    if (!sessionId) return
    let cancelled = false

    async function load() {
      setLoading(true)
      try {
        const live = await getSession(sessionId!)
        if (cancelled) return
        setSession(live)

        const [record, schema, spec] = await Promise.all([
          getTemplate(live.template_id),
          getTemplateRegions(live.template_id, live.base_version_id),
          getSpec(live.session_id),
        ])
        if (cancelled) return

        setTemplate(record)
        setOriginal(
          toParsedDocument(schema, {
            title: record.title,
            subtitle: record.form_id ?? record.format.toUpperCase(),
          }),
        )
        setSpecBody(spec)

        // The dry run. Keeps nothing; this is the verdict the user commits on.
        try {
          const dry = await compileSession(live.session_id)
          if (!cancelled) setQa(dry)
        } catch (err) {
          // A compile that cannot run at all is worth showing rather than
          // hiding behind a spinner — it means there is nothing to commit.
          if (!cancelled) setError(err instanceof Error ? err.message : 'The dry run failed.')
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Could not load this session.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void load()
    return () => {
      cancelled = true
    }
  }, [sessionId])

  const spec: ChangeSpec | null = useMemo(
    () => (specBody ? toChangeSpec(specBody.spec) : null),
    [specBody],
  )
  const working = useMemo(
    () => (original && spec ? applySpec(original, spec) : null),
    [original, spec],
  )

  if (loading) {
    return (
      <PageBody>
        <PageHeading title="Review & commit" subtitle="Compiling a dry run to check the output…" />
      </PageBody>
    )
  }

  if (!session || !working || !template) {
    return (
      <PageBody>
        <EmptyState
          title="Nothing to review yet"
          body={error ?? 'Start a document from a template and answer the agent’s questions first.'}
          action={{ label: 'Go to Discovery', onClick: () => navigate('/discovery') }}
        />
      </PageBody>
    )
  }

  const fields = working.regions.filter((r) => !r.protected && r.kind !== 'branding')
  const changed = fields.filter((r) => r.changed)
  const derived: Record<string, DerivedValue> = session.derived_values ?? {}
  const claims = qa ? preservationClaims(qa.structural, qa.protected_regions) : []
  const lostParts = (qa?.structural.lost_parts as string[] | undefined) ?? []

  /**
   * Commit, and optionally put the result forward as the template's next version.
   *
   * The two produce genuinely different things, so the response is read
   * differently: a plain commit answers with `result_document_id` — the
   * caller's own file, no version number, nobody's to approve — and a
   * submission answers with `result_version_id` and goes to doc control.
   * Checking only for a version id here would have reported "QA failed" on
   * every successful document.
   */
  const handleCommit = async (submitAsVersion: boolean) => {
    setCommitting(true)
    setError(null)
    try {
      const result = await commitSession(session.session_id, { submitAsVersion })
      const produced = result.result_document_id ?? result.result_version_id
      if (result.overall !== 'pass' || !produced) {
        setError('QA failed on the real compile — nothing was saved.')
        return
      }

      recordDocument(
        session.session_id,
        template.title,
        String(result.result_version_number ?? ''),
        (FMT_LABEL[template.format] ?? 'DOC') as never,
      )

      if (submitAsVersion) {
        fireToast(`v${result.result_version_number} sent to doc control for approval`)
        navigate(`/templates/${session.template_id}`)
      } else {
        fireToast('Document created')
        // My Documents lists it for real now, so there is somewhere to land.
        navigate('/documents')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The commit failed.')
    } finally {
      setCommitting(false)
    }
  }

  return (
    <PageBody>
      <PageHeading
        title={updatingTemplate ? 'Review & submit' : 'Review & commit'}
        subtitle={
          updatingTemplate
            ? 'Check what changed and where it came from before submitting this as the next version.'
            : 'Check what changed and where it came from before the document is created.'
        }
      />

      {error ? (
        <div className="mb-4 rounded-card border border-dashed border-accent bg-accent-100 text-accent-900 py-[11px] px-[14px] text-[12.5px]">
          {error}
        </div>
      ) : null}

      <div className="hub-results grid grid-cols-[minmax(0,1fr)_320px] gap-6 items-start">
        <div className="flex flex-col gap-5 min-w-0">
          <Panel>
            <div className="flex items-center gap-2 mb-[14px] flex-wrap">
              <Tag variant="accent" className="whitespace-nowrap">
                {changed.length} of {fields.length} regions changed
              </Tag>
              <span className="text-[11.5px] opacity-50">
                {template.title} · {session.tier}
              </span>
            </div>

            <table className="w-full border-collapse">
              <tbody>
                {fields.map((region) => {
                  const info = derived[region.regionId]
                  const rowCount = region.rows?.length ?? 0
                  return (
                    <tr key={region.regionId} className="border-b border-divider">
                      <th className="w-[160px] text-left align-top font-normal text-[12px] opacity-55 py-[11px] px-2">
                        {region.label}
                      </th>
                      <td className="py-[11px] px-2">
                        <div className="flex items-center gap-2 flex-wrap">
                          <div
                            className={`text-[13.5px] py-[2px] px-[6px] rounded-[6px] ${
                              !region.changed ? 'opacity-35' : ''
                            }`}
                          >
                            {rowCount
                              ? `${rowCount} row${rowCount === 1 ? '' : 's'}`
                              : region.content || 'Unchanged from template'}
                          </div>
                          <Tag
                            variant="neutral"
                            className={`whitespace-nowrap ${PROV_TAG_CLASS[region.provenance]}`}
                          >
                            {PROV_LABEL[region.provenance]}
                          </Tag>
                          {/* The deriver's own justification. A value that could
                              not name one was dropped server-side, so anything
                              shown here has a source. */}
                          {info?.basis ? (
                            <span className="text-[11px] opacity-50">from {info.basis}</span>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </Panel>

          {qa?.dropped.length ? (
            <Panel>
              <SectionLabel>Declined changes</SectionLabel>
              <p className="text-[11.5px] opacity-55 mb-[10px]">
                These regions were left exactly as the template had them.
              </p>
              <div className="flex flex-col gap-[10px]">
                {qa.dropped.map((d) => (
                  <div key={`${d.index}-${d.target}`} className="text-[13px] opacity-75">
                    <span className="font-semibold">{d.target}</span> — {d.reason}
                  </div>
                ))}
              </div>
            </Panel>
          ) : null}

          {specBody?.skipped.length ? (
            <Panel>
              <SectionLabel>Values with nowhere to go</SectionLabel>
              <div className="flex flex-col gap-[10px]">
                {specBody.skipped.map((s) => (
                  <div key={s.region_id} className="text-[13px] opacity-75">
                    <span className="font-semibold">{s.region_id}</span> — {s.reason}
                  </div>
                ))}
              </div>
            </Panel>
          ) : null}
        </div>

        <div className="flex flex-col gap-4 min-w-0">
          <Panel>
            <SectionLabel>Preserved on commit</SectionLabel>
            {claims.length ? (
              <div className="flex flex-col gap-[9px]">
                {claims.map((claim) => (
                  <div key={claim} className="flex items-center gap-[9px]">
                    <CheckIcon width={14} height={14} className="text-accent flex-none" />
                    <span className="text-[13px]">{claim}</span>
                  </div>
                ))}
                {qa?.packaging === 'surgical' ? (
                  <p className="text-[11.5px] opacity-55 mt-[4px]">
                    Rebuilt from the original package, part for part — every part not written is
                    byte-identical.
                  </p>
                ) : null}
              </div>
            ) : (
              <p className="text-[12.5px] opacity-55">No dry run yet.</p>
            )}
          </Panel>

          <Panel>
            <SectionLabel>QA checks</SectionLabel>
            {qa ? (
              <div className="flex flex-col gap-[10px]">
                <QaRow
                  name="Structural"
                  pass={!lostParts.length && Boolean(qa.structural.passed ?? true)}
                  detail={
                    lostParts.length
                      ? `${lostParts.length} package part(s) lost`
                      : 'No package part lost'
                  }
                />
                <QaRow
                  name="Functional"
                  pass={Boolean(qa.functional.passed ?? true)}
                  detail={`${qa.operations_applied} of ${qa.operations_submitted} operations applied`}
                />
                <QaRow
                  name="Assertions"
                  pass={qa.assertions.every((a) => a.passed)}
                  detail={`${qa.assertions.filter((a) => a.passed).length} of ${qa.assertions.length} passed`}
                />
                <div className="text-[11px] opacity-45">Dry run in {qa.duration_ms}ms</div>
              </div>
            ) : (
              <p className="text-[12.5px] opacity-55">The dry run did not complete.</p>
            )}
          </Panel>

          {/* Which action leads depends on why this conversation was started.
              Arriving from "Update Document" means the intent was declared
              before any work happened, so submitting is the primary action and
              keeping a private copy is the aside. Arriving from Generate means
              the opposite. Same two calls either way -- only the emphasis
              moves, because guessing this wrong is how a filled-in form ends up
              published as the blank one. */}
          <div className="flex flex-col gap-[10px]">
            {updatingTemplate ? (
              <>
                <Button
                  variant="primary"
                  block
                  className="mt-0 whitespace-nowrap"
                  disabled={committing || !qa || qa.overall !== 'pass'}
                  onClick={() => void handleCommit(true)}
                >
                  {committing ? 'Submitting…' : 'Submit for approval'}
                </Button>
                <p className="text-[11.5px] opacity-60">
                  This becomes v{(template.current_version?.version_number ?? 1) + 1} once doc
                  control approves it. Until then the library keeps serving the current version.
                </p>
                <Button
                  variant="ghost"
                  block
                  className="mt-0 whitespace-nowrap"
                  disabled={committing || !qa || qa.overall !== 'pass'}
                  onClick={() => void handleCommit(false)}
                >
                  Just keep it as my document
                </Button>
              </>
            ) : (
              <>
                <Button
                  variant="primary"
                  block
                  className="mt-0 whitespace-nowrap"
                  disabled={committing || !qa || qa.overall !== 'pass'}
                  onClick={() => void handleCommit(false)}
                >
                  {committing ? 'Compiling…' : 'Create document'}
                </Button>

                <div className="bg-surface rounded-card p-[14px] flex flex-col gap-[10px]">
                  <div>
                    <div className="text-[13px] font-semibold">Make this the template</div>
                    <p className="text-[11.5px] opacity-60 mt-[2px]">
                      Sends it to doc control as the next version. They decide whether it replaces
                      the current one — until then the library keeps serving the old version.
                    </p>
                  </div>
                  <Button
                    variant="secondary"
                    block
                    className="mt-0 whitespace-nowrap"
                    disabled={committing || !qa || qa.overall !== 'pass'}
                    onClick={() => void handleCommit(true)}
                  >
                    Create &amp; submit as new version
                  </Button>
                </div>
              </>
            )}

            {qa && qa.overall !== 'pass' ? (
              <p className="text-[11.5px] opacity-60">
                QA did not pass, so there is nothing safe to commit. Go back and adjust an answer.
              </p>
            ) : null}
            <Button
              variant="secondary"
              block
              className="mt-0 whitespace-nowrap"
              onClick={() =>
                navigate(`/templates/${session.template_id}/generate?session=${session.session_id}`)
              }
            >
              Back to edit
            </Button>
          </div>
        </div>
      </div>
    </PageBody>
  )
}

function QaRow({ name, pass, detail }: { name: string; pass: boolean; detail: string }) {
  return (
    <div className="flex items-start gap-[10px]">
      <Tag variant={pass ? 'accent' : 'accent2'} className="whitespace-nowrap flex-none mt-[1px]">
        {pass ? 'Pass' : 'Fail'}
      </Tag>
      <div className="min-w-0">
        <div className="text-[13px] font-semibold">{name}</div>
        <div className="text-[12px] opacity-55">{detail}</div>
      </div>
    </div>
  )
}
