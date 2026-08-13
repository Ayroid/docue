import { useNavigate, useParams } from 'react-router-dom'
import { statusClass } from '@/data/catalog'
import { VERSIONS } from '@/data/demo'
import { useHub } from '@/store/HubProvider'
import { initialsOf } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Tag } from '@/components/ui/tag'
import { Panel, SectionLabel } from '@/components/ui/table'
import { Avatar, DemoBadge, EmptyState, FormatChip, PageBody, PreviewLines } from '@/components/common'
import { DownloadIcon, GenerateIcon } from '@/components/icons'

export function GeneratedDocument() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { documents, fireToast } = useHub()

  const doc = documents.find((d) => d.id === id)

  if (!doc) {
    return (
      <PageBody>
        <EmptyState
          title="Document not found"
          body="It may have been removed, or the link is out of date."
          action={{ label: 'Go to My documents', onClick: () => navigate('/documents') }}
        />
      </PageBody>
    )
  }

  return (
    <PageBody>
      <div className="flex items-start gap-4 flex-wrap mb-[22px]">
        <div className="min-w-0">
          <Button variant="ghost" className="py-1 px-2 mb-[6px] whitespace-nowrap" onClick={() => navigate('/documents')}>
            Back to My documents
          </Button>
          <h2 className="text-[clamp(24px,2.6vw,32px)] mb-1">{doc.name}</h2>
          <p className="opacity-65 text-[14px] m-0">
            {doc.template} · v{doc.version} · {doc.size} · created {doc.created}
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2 flex-none">
          <DemoBadge />
          <span className={`${statusClass(doc.status)} whitespace-nowrap`}>{doc.status}</span>
        </div>
      </div>

      <div className="hub-results grid grid-cols-[minmax(0,1fr)_320px] gap-6 items-start">
        <Panel>
          <div className="flex items-center gap-2 mb-[14px]">
            <FormatChip size={34}>{doc.fmt}</FormatChip>
            <div className="min-w-0">
              <div className="text-[13.5px] font-semibold">{doc.name}{doc.ext}</div>
              <div className="text-[11.5px] opacity-55">{doc.kind} · {doc.size}</div>
            </div>
          </div>
          <div className="bg-neutral-100 rounded-[12px] py-[26px] px-7">
            <PreviewLines />
          </div>
        </Panel>

        <div className="flex flex-col gap-4 min-w-0">
          <Panel>
            <SectionLabel>Generated from</SectionLabel>
            <div className="flex items-center gap-[10px]">
              <Avatar initials={initialsOf(doc.template)} />
              <div className="flex-1 min-w-0">
                <div className="text-[13.5px] font-semibold truncate">{doc.template}</div>
                <div className="text-[11.5px] opacity-55">Template v{doc.version}</div>
              </div>
            </div>
          </Panel>

          <Panel>
            <SectionLabel>Version timeline</SectionLabel>
            <div className="flex flex-col gap-[10px]">
              {VERSIONS.slice(0, 2).map((v, i) => (
                <div key={v.n} className="flex items-start gap-3">
                  <Tag variant={i === 0 ? 'accent' : 'neutral'} className="whitespace-nowrap flex-none">
                    v{v.n}
                  </Tag>
                  <div className="flex-1 min-w-0">
                    <div className="text-[12.5px] opacity-55">{v.when} · {v.author}</div>
                    <div className="text-[13px]">{v.note}</div>
                  </div>
                </div>
              ))}
            </div>
          </Panel>

          <div className="flex flex-col gap-[10px]">
            <Button
              variant="primary"
              block
              className="mt-0 gap-[7px] whitespace-nowrap"
              onClick={() => fireToast(`Downloaded ${doc.name}${doc.ext}`)}
            >
              <DownloadIcon width={14} height={14} />
              Download {doc.ext}
            </Button>
            {doc.templateId ? (
              <Button
                variant="secondary"
                block
                className="mt-0 gap-[7px] whitespace-nowrap"
                onClick={() => navigate(`/templates/${doc.templateId}/generate`)}
              >
                <GenerateIcon width={14} height={14} />
                Generate another
              </Button>
            ) : null}
          </div>
        </div>
      </div>
    </PageBody>
  )
}
