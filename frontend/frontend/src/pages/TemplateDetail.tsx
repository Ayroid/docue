import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { REGIONS, VERSIONS } from '@/data/mock'
import { useHub } from '@/store/HubProvider'
import { initialsOf } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Tag } from '@/components/ui/tag'
import { Panel, SectionLabel } from '@/components/ui/table'
import { Avatar, PageBody, PreviewLines } from '@/components/common'
import { GenerateIcon } from '@/components/icons'

const TOTAL_PAGES = 4

export function TemplateDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { templates, fireToast } = useHub()
  const [page, setPage] = useState(1)

  const template = templates.find((t) => String(t.id) === id) ?? templates[0]

  const fillable = REGIONS.filter((r) => r.status === 'Fillable').length
  const protectedCount = REGIONS.length - fillable

  return (
    <PageBody>
      <div className="flex items-start gap-4 flex-wrap mb-[22px]">
        <div className="min-w-0">
          <Button
            variant="ghost"
            className="py-1 px-2 mb-[6px] whitespace-nowrap"
            onClick={() => navigate('/')}
          >
            Back to Discovery
          </Button>
          <h2 className="text-[clamp(24px,2.6vw,32px)] mb-1">{template.name}</h2>
          <p className="opacity-65 text-[14px] m-0">
            {template.owner} · {template.category} · used {template.uses} times · updated {template.updated}
          </p>
        </div>
      </div>

      <div className="hub-results grid grid-cols-[minmax(0,1fr)_320px] gap-6 items-start">
        <div className="flex flex-col gap-5 min-w-0">
          <Panel>
            <div className="flex items-center gap-2 mb-[14px]">
              <Tag variant="accent" className="whitespace-nowrap">
                Region map
              </Tag>
              <span className="text-[11.5px] opacity-50">
                {fillable} fillable · {protectedCount} protected
              </span>
            </div>

            <div className="relative bg-neutral-100 rounded-[12px] py-[26px] px-7">
              <div className="font-heading text-[18px] mb-1">{template.name}</div>
              <div className="text-[11.5px] opacity-55 mb-5">
                v{template.version} · page {page} of {TOTAL_PAGES}
              </div>
              <PreviewLines />

              {REGIONS.map((r) => (
                <div
                  key={r.n}
                  className="absolute rounded-[8px] pointer-events-none opacity-[.72]"
                  style={{
                    top: r.top,
                    left: r.left,
                    width: r.width,
                    height: r.height,
                    background:
                      r.status === 'Fillable' ? 'var(--color-accent-200)' : 'var(--color-accent-2-200)',
                    border: `1px solid ${r.status === 'Fillable' ? 'var(--color-accent-400)' : 'var(--color-accent-2-400)'}`,
                  }}
                >
                  <span
                    className="absolute -top-[9px] -left-[9px] w-5 h-5 rounded-pill grid place-items-center text-[11px] font-bold text-bg"
                    style={{
                      background: r.status === 'Fillable' ? 'var(--color-accent)' : 'var(--color-accent-2)',
                    }}
                  >
                    {r.n}
                  </span>
                </div>
              ))}
            </div>

            <div className="flex items-center justify-center gap-2 mt-[14px]">
              <Button
                variant="ghost"
                className="whitespace-nowrap"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                Previous page
              </Button>
              <span className="text-[12.5px] opacity-55">
                Page {page} of {TOTAL_PAGES}
              </span>
              <Button
                variant="ghost"
                className="whitespace-nowrap"
                onClick={() => setPage((p) => Math.min(TOTAL_PAGES, p + 1))}
              >
                Next page
              </Button>
            </div>
          </Panel>

          <div className="flex flex-col gap-3">
            {REGIONS.map((r) => (
              <div
                key={r.n}
                className="bg-surface rounded-card py-4 px-[18px] flex items-center gap-4 flex-wrap"
              >
                <div
                  className="w-[38px] h-[38px] flex-none rounded-pill grid place-items-center text-[13px] font-bold"
                  style={{
                    background:
                      r.status === 'Fillable' ? 'var(--color-accent-200)' : 'var(--color-accent-2-200)',
                    color: r.status === 'Fillable' ? 'var(--color-accent-800)' : 'var(--color-accent-2-900)',
                  }}
                >
                  {r.n}
                </div>
                <div className="flex-[1_1_200px] min-w-[170px]">
                  <div className="font-semibold">{r.name}</div>
                  <div className="text-[12px] opacity-55">{r.meta}</div>
                </div>
                <div className="flex items-center gap-3 ml-auto flex-none">
                  <Tag variant={r.status === 'Fillable' ? 'accent' : 'accent2'} className="whitespace-nowrap">
                    {r.status}
                  </Tag>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-4 min-w-0">
          <Panel>
            <SectionLabel>Owner</SectionLabel>
            <div className="flex items-center gap-[10px]">
              <Avatar initials={initialsOf(template.owner)} />
              <div className="flex-1 min-w-0">
                <div className="text-[13.5px] font-semibold truncate">{template.owner}</div>
                <div className="text-[11.5px] opacity-55">Template owner · doc control approver</div>
              </div>
            </div>
          </Panel>

          <Panel>
            <SectionLabel>Access</SectionLabel>
            <div className="flex flex-col gap-3">
              <div>
                <div className="text-[12px] opacity-55 mb-[7px]">Can view</div>
                <div className="flex gap-2 flex-wrap">
                  <Tag variant="neutral" className="whitespace-nowrap">
                    All employees
                  </Tag>
                  <Tag variant="neutral" className="whitespace-nowrap">
                    Contractors
                  </Tag>
                </div>
              </div>
              <div>
                <div className="text-[12px] opacity-55 mb-[7px]">Can generate</div>
                <div className="flex gap-2 flex-wrap">
                  <Tag variant="accent" className="whitespace-nowrap">
                    {template.owner}
                  </Tag>
                  <Tag variant="accent" className="whitespace-nowrap">
                    Delivery
                  </Tag>
                  <Tag variant="accent" className="whitespace-nowrap">
                    Quality
                  </Tag>
                </div>
              </div>
            </div>
          </Panel>

          <Panel>
            <SectionLabel>Version timeline</SectionLabel>
            <div className="flex flex-col gap-[10px]">
              {VERSIONS.map((v, i) => (
                <div key={v.n} className="flex items-start gap-3">
                  <Tag variant={i === 0 ? 'accent' : 'neutral'} className="whitespace-nowrap flex-none">
                    v{v.n}
                  </Tag>
                  <div className="flex-1 min-w-0">
                    <div className="text-[12.5px] opacity-55">
                      {v.when} · {v.author}
                    </div>
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
              onClick={() => navigate(`/templates/${template.id}/generate`)}
            >
              <GenerateIcon width={14} height={14} />
              Generate
            </Button>
            <Button
              variant="secondary"
              block
              className="mt-0 whitespace-nowrap"
              onClick={() => fireToast(`Downloaded ${template.name}.docx`)}
            >
              Download blank
            </Button>
          </div>
        </div>
      </div>
    </PageBody>
  )
}
