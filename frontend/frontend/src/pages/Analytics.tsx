import { useState } from 'react'
import {
  LATENCY_STATS,
  NEVER_USED,
  RANGE_LABELS,
  SEARCH_GAPS,
  SERIES,
  STALE_TEMPLATES,
  STAT_TILES,
} from '@/data/mock'
import { Segmented } from '@/components/ui/segmented'
import { Tag } from '@/components/ui/tag'
import { Panel, SectionLabel, Table } from '@/components/ui/table'
import { PageBody, PageHeading } from '@/components/common'

const RANGE_OPTIONS = [
  { value: '30d', label: '30 days' },
  { value: '90d', label: '90 days' },
  { value: '12m', label: '12 months' },
] as const

type Range = (typeof RANGE_OPTIONS)[number]['value']

export function Analytics() {
  const [range, setRange] = useState<Range>('30d')
  const series = SERIES[range]
  const [from, to] = RANGE_LABELS[range]

  return (
    <PageBody>
      <div className="flex items-start gap-4 flex-wrap mb-[22px]">
        <PageHeading title="Analytics" subtitle="Adoption, generation cost and where the library is thin." className="mb-0" />
        <Segmented name="hubrange" value={range} options={RANGE_OPTIONS} onChange={setRange} className="ml-auto" />
      </div>

      <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-4 mb-6">
        {STAT_TILES.map((s) => (
          <Panel key={s.label}>
            <div className="font-heading text-[28px] mb-1">{s.value}</div>
            <div className="text-[12.5px] opacity-70 mb-[2px]">{s.label}</div>
            <div className="text-[11px] opacity-50">{s.delta}</div>
          </Panel>
        ))}
      </div>

      <Panel className="mb-6">
        <div className="flex items-center gap-2 mb-[14px]">
          <SectionLabel className="mb-0">Documents generated</SectionLabel>
          <span className="text-[11.5px] opacity-50 ml-auto">{from} – {to}</span>
        </div>
        <svg viewBox="0 0 600 180" className="w-full h-[180px]" preserveAspectRatio="none">
          <path d={series.area} fill="var(--color-accent-100)" />
          <path d={series.line} fill="none" stroke="var(--color-accent)" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </Panel>

      <div className="hub-results grid grid-cols-[minmax(0,1fr)_340px] gap-6 items-start">
        <div className="flex flex-col gap-5 min-w-0">
          <Panel>
            <SectionLabel>Search queries with no good match</SectionLabel>
            <Table>
              <thead>
                <tr>
                  <th>Query</th>
                  <th>Searches</th>
                  <th>People</th>
                </tr>
              </thead>
              <tbody>
                {SEARCH_GAPS.map((g) => (
                  <tr key={g.query}>
                    <td className="font-semibold">{g.query}</td>
                    <td className="opacity-75">{g.searches}</td>
                    <td className="opacity-75">{g.people}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Panel>

          <Panel>
            <SectionLabel>Stale templates</SectionLabel>
            <div className="flex flex-col gap-3">
              {STALE_TEMPLATES.map((t) => (
                <div key={t.name} className="flex items-center gap-4 flex-wrap py-1">
                  <div className="flex-[1_1_200px] min-w-[170px]">
                    <div className="font-semibold text-[13.5px]">{t.name}</div>
                    <div className="text-[12px] opacity-55">{t.owner} · updated {t.updated}</div>
                  </div>
                  <Tag variant="accent2" className="whitespace-nowrap ml-auto">
                    {t.uses} uses
                  </Tag>
                </div>
              ))}
            </div>
          </Panel>
        </div>

        <div className="flex flex-col gap-4 min-w-0">
          <Panel>
            <SectionLabel>Generation cost</SectionLabel>
            <div className="flex flex-col gap-[10px]">
              {LATENCY_STATS.map((s) => (
                <div key={s.label} className="flex items-center justify-between">
                  <span className="text-[13px] opacity-70">{s.label}</span>
                  <span className="text-[13.5px] font-semibold">{s.value}</span>
                </div>
              ))}
            </div>
          </Panel>

          <Panel>
            <SectionLabel>Never used</SectionLabel>
            <div className="flex flex-col gap-[10px]">
              {NEVER_USED.map((t) => (
                <div key={t.name}>
                  <div className="text-[13px] font-semibold">{t.name}</div>
                  <div className="text-[11.5px] opacity-55">{t.meta}</div>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      </div>
    </PageBody>
  )
}
