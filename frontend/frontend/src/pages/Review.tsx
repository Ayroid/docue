import { useMemo } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { QA_CHECKS, REVIEW_ROWS } from '@/data/demo'
import { useHub } from '@/store/HubProvider'
import { buildChangeSpec, parseTemplate } from '@/features/generate/session'
import { useDemoTemplate } from '@/features/generate/useDemoTemplate'
import { applySpec } from '@/features/preview/workingCopy'
import type { ProvenanceKind } from '@/features/preview/types'
import { Button } from '@/components/ui/button'
import { Tag } from '@/components/ui/tag'
import { Panel, SectionLabel } from '@/components/ui/table'
import { DemoBadge, EmptyState, PageBody, PageHeading } from '@/components/common'
import { CheckIcon } from '@/components/icons'

const PROV_LABEL: Record<ProvenanceKind, string> = {
  typed: 'Typed',
  derived: 'Derived',
  ai: 'AI-drafted',
  unchanged: 'Unchanged',
  system: 'System',
}

const PROV_TAG_CLASS: Record<ProvenanceKind, string> = {
  typed: '',
  derived: 'border border-dashed border-accent bg-transparent',
  ai: 'border border-dashed border-accent bg-accent-100 text-accent-900',
  unchanged: 'opacity-45',
  system: 'opacity-45',
}

/** Static confidence figures the prototype ships per field label — there is no
    confidence score in the Change Spec, so this is display-only context. */
const confidenceFor = (label: string) => REVIEW_ROWS.find((r) => r.label === label)?.conf ?? null

export function Review() {
  const { sessionId } = useParams()
  const navigate = useNavigate()
  const { getSession, commitSession } = useHub()

  const session = sessionId ? getSession(sessionId) : undefined
  const template = useDemoTemplate(session?.templateId)

  const original = useMemo(() => parseTemplate(template), [template])
  const spec = useMemo(
    () => (session ? buildChangeSpec(template, session.answers, session.tier, session.qIndex) : null),
    [template, session],
  )
  const working = useMemo(() => (original && spec ? applySpec(original, spec) : null), [original, spec])

  if (!session || !working) {
    return (
      <PageBody>
        <EmptyState
          title="Nothing to review yet"
          body="Start a document from a template, answer the agent's questions, then come back here to commit."
          action={{ label: 'Go to Discovery', onClick: () => navigate('/discovery') }}
        />
      </PageBody>
    )
  }

  /* The compiler's `protect` op against the branding region always lands in
     `refused` — that is the guarantee working, not a failure to surface. */
  const refused = working.refused.filter((r) => r.regionId !== 'doc.branding')
  const fields = working.regions.filter((r) => r.kind !== 'branding' && r.regionId !== 'doc.confidentiality')
  const changedCount = fields.filter((r) => r.changed).length

  const handleCommit = () => {
    const docId = commitSession(sessionId!, template.name, template.version, template.fmt)
    navigate(`/documents/${docId}`)
  }

  return (
    <PageBody>
      <div className="flex items-start gap-3 flex-wrap mb-[22px]">
        <PageHeading
          title="Review & commit"
          subtitle="Check what changed and where it came from before the document is created."
          className="mb-0"
        />
        <DemoBadge className="mt-[10px]" />
      </div>

      <div className="hub-results grid grid-cols-[minmax(0,1fr)_320px] gap-6 items-start">
        <div className="flex flex-col gap-5 min-w-0">
          <Panel>
            <div className="flex items-center gap-2 mb-[14px]">
              <Tag variant="accent" className="whitespace-nowrap">
                {changedCount} of {fields.length} fields changed
              </Tag>
              <span className="text-[11.5px] opacity-50">{template.name} · v{template.version}</span>
            </div>

            <table className="w-full border-collapse">
              <tbody>
                {fields.map((region) => {
                  const conf = confidenceFor(region.label)
                  return (
                    <tr key={region.regionId} className="border-b border-divider">
                      <th className="w-[160px] text-left align-top font-normal text-[12px] opacity-55 py-[11px] px-2">
                        {region.label}
                      </th>
                      <td className="py-[11px] px-2">
                        <div className="flex items-center gap-2 flex-wrap">
                          <div className={`text-[13.5px] py-[2px] px-[6px] rounded-[6px] ${!region.content ? 'opacity-35' : ''}`}>
                            {region.content || 'Unchanged from template'}
                          </div>
                          <Tag variant="neutral" className={`whitespace-nowrap ${PROV_TAG_CLASS[region.provenance]}`}>
                            {PROV_LABEL[region.provenance]}
                          </Tag>
                          {conf !== null ? (
                            <span className="text-[11px] opacity-50 whitespace-nowrap">{conf}% confidence</span>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </Panel>

          {refused.length ? (
            <Panel>
              <SectionLabel>Declined changes</SectionLabel>
              <div className="flex flex-col gap-[10px]">
                {refused.map((r) => (
                  <div key={r.regionId} className="text-[13px] opacity-75">
                    <span className="font-semibold">{r.regionId}</span> — {r.reason}
                  </div>
                ))}
              </div>
            </Panel>
          ) : null}
        </div>

        <div className="flex flex-col gap-4 min-w-0">
          <Panel>
            <SectionLabel>Preserved on commit</SectionLabel>
            <div className="flex flex-col gap-[9px]">
              {['Logo & sensitivity label', '27 merged ranges', '0 formulas touched', 'Confidentiality notice wording'].map((g) => (
                <div key={g} className="flex items-center gap-[9px]">
                  <CheckIcon width={14} height={14} className="text-accent flex-none" />
                  <span className="text-[13px]">{g}</span>
                </div>
              ))}
            </div>
          </Panel>

          <Panel>
            <SectionLabel>QA checks</SectionLabel>
            <div className="flex flex-col gap-[10px]">
              {QA_CHECKS.map((c) => (
                <div key={c.name} className="flex items-start gap-[10px]">
                  <Tag
                    variant={c.state === 'Pass' ? 'accent' : 'accent2'}
                    className="whitespace-nowrap flex-none mt-[1px]"
                  >
                    {c.state}
                  </Tag>
                  <div className="min-w-0">
                    <div className="text-[13px] font-semibold">{c.name}</div>
                    <div className="text-[12px] opacity-55">{c.detail}</div>
                  </div>
                </div>
              ))}
            </div>
          </Panel>

          <div className="flex flex-col gap-[10px]">
            <Button variant="primary" block className="mt-0 whitespace-nowrap" onClick={handleCommit}>
              Create document
            </Button>
            <Button
              variant="secondary"
              block
              className="mt-0 whitespace-nowrap"
              onClick={() => navigate(`/templates/${template.id}/generate?session=${sessionId}`)}
            >
              Back to edit
            </Button>
          </div>
        </div>
      </div>
    </PageBody>
  )
}
