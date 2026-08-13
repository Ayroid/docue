import { Fragment, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useHub } from '@/store/HubProvider'
import { filterTemplates, RANK_SCORES, scoreSignals } from '@/services/search'
import { Button } from '@/components/ui/button'
import { FilterTag, Tag } from '@/components/ui/tag'
import { Table, TableCard } from '@/components/ui/table'
import { EmptyState, FormatChip, PageBody } from '@/components/common'
import { CloseIcon, SearchIcon } from '@/components/icons'

const FILTER_GROUPS = [
  { title: 'Category', key: 'cat', options: ['Functional', 'Technical', 'MOM', 'Design', 'Testing', 'API'] },
  { title: 'Format', key: 'Format', options: ['Word', 'Excel', 'PowerPoint'] },
  { title: 'Owner', key: 'Owner', options: ['Delivery PMO', 'Architecture', 'Quality', 'Pre-sales'] },
  { title: 'Version status', key: 'Version status', options: ['Approved', 'In review', 'Superseded'] },
  { title: 'Updated', key: 'Updated', options: ['This week', 'This month', 'This quarter'] },
] as const

export function Results() {
  const { templates } = useHub()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const query = params.get('q') ?? ''

  const [cat, setCat] = useState('All')
  const [facets, setFacets] = useState<Record<string, string | null>>({
    Format: null,
    Owner: null,
    'Version status': null,
    Updated: null,
  })
  const [openResult, setOpenResult] = useState<number | null>(4)
  const [draftQuery, setDraftQuery] = useState(query)

  const filtered = useMemo(() => filterTemplates(templates, query, cat), [templates, query, cat])
  const results = filtered.slice(0, 5)

  const resultLabel =
    query || cat !== 'All'
      ? `${filtered.length} template${filtered.length === 1 ? '' : 's'} matching your search`
      : '128 approved templates · ordered by how often your team uses them'

  const applied = [
    { label: `Search: ${query || 'all templates'}`, clear: () => setParams({ q: '' }) },
    ...(cat !== 'All' ? [{ label: cat, clear: () => setCat('All') }] : []),
    ...Object.keys(facets)
      .filter((k) => facets[k])
      .map((k) => ({ label: facets[k]!, clear: () => setFacets((f) => ({ ...f, [k]: null })) })),
  ]

  return (
    <PageBody>
      <div className="flex items-center gap-[9px] bg-surface border border-divider rounded-[10px] py-3 px-5 max-w-[720px] mx-auto mb-[14px]">
        <SearchIcon className="opacity-60" />
        <input
          value={draftQuery}
          onChange={(e) => setDraftQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && setParams({ q: draftQuery })}
          placeholder="Describe the document you need — e.g. test script for a payment API"
          className="flex-1 border-0 bg-transparent outline-none font-[inherit] text-[15px] text-ink min-w-0"
        />
      </div>

      <div className="flex gap-[9px] flex-wrap justify-center mb-7">
        {applied.map((a) => (
          <FilterTag
            key={a.label}
            selected
            className="inline-flex items-center max-w-[320px] overflow-hidden"
            onClick={a.clear}
          >
            {a.label}
            <CloseIcon width={11} height={11} strokeWidth={3} className="ml-[6px]" />
          </FilterTag>
        ))}
      </div>

      <div className="hub-results grid grid-cols-[260px_minmax(0,1fr)] gap-6 items-start">
        <div className="bg-surface rounded-card p-[18px] flex flex-col gap-5">
          {FILTER_GROUPS.map((g) => (
            <div key={g.title}>
              <div className="text-[10.5px] tracking-[.1em] uppercase opacity-55 mb-[10px]">{g.title}</div>
              <div className="flex flex-col gap-[2px] items-stretch">
                {g.options.map((label) => {
                  const on = g.key === 'cat' ? cat === label : facets[g.key] === label
                  return (
                    <button
                      key={label}
                      type="button"
                      className={`border-0 rounded-[9px] w-full text-left whitespace-nowrap cursor-pointer font-[inherit] text-[13px] py-[7px] px-[11px] ${
                        on ? 'bg-accent text-bg' : 'bg-transparent text-ink opacity-75'
                      }`}
                      onClick={() =>
                        g.key === 'cat'
                          ? setCat(on ? 'All' : label)
                          : setFacets((f) => ({ ...f, [g.key]: on ? null : label }))
                      }
                    >
                      {label}
                    </button>
                  )
                })}
              </div>
            </div>
          ))}
        </div>

        <div>
          <div className="flex items-center gap-4 flex-wrap mb-[14px]">
            <div>
              <h4 className="m-0">Results</h4>
              <p className="opacity-65 text-[13px] mt-[2px] mb-0">{resultLabel}</p>
            </div>
            <Button variant="ghost" className="ml-auto whitespace-nowrap" onClick={() => navigate('/discovery')}>
              Back to Discovery
            </Button>
          </div>

          <TableCard>
            <Table className="table-auto w-full min-w-[620px]">
              <thead>
                <tr>
                  <th>Template</th>
                  <th>Owner</th>
                  <th>Version</th>
                  <th>Score</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {results.map((t, i) => (
                  <Fragment key={t.id}>
                    <tr>
                      <td>
                        <div
                          className="flex items-start gap-[11px] min-w-0 cursor-pointer"
                          onClick={() => navigate(`/templates/${t.id}`)}
                        >
                          <FormatChip size={32}>{t.fmt}</FormatChip>
                          <div className="min-w-0">
                            <div className="font-semibold">{t.name}</div>
                            <div className="text-[12px] opacity-55">
                              Matched on "{query || t.category}" in the section headings and on {12 - i * 2}{' '}
                              similar documents your team generated.
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="opacity-75 whitespace-nowrap">{t.owner}</td>
                      <td>
                        <Tag variant="accent2" className="whitespace-nowrap">
                          v{t.version}
                        </Tag>
                      </td>
                      <td>
                        <Tag variant="accent" className="whitespace-nowrap">
                          {RANK_SCORES[i] ?? 68}
                        </Tag>
                      </td>
                      <td>
                        <div className="flex gap-2 justify-end">
                          <Button
                            variant="ghost"
                            className="text-[12.5px] whitespace-nowrap"
                            onClick={() => setOpenResult(openResult === t.id ? null : t.id)}
                          >
                            {openResult === t.id ? 'Hide breakdown' : 'Why this?'}
                          </Button>
                          <Button
                            variant="primary"
                            size="xs"
                            className="whitespace-nowrap"
                            onClick={() => navigate(`/templates/${t.id}/generate`)}
                          >
                            Generate
                          </Button>
                        </div>
                      </td>
                    </tr>
                    {openResult === t.id ? (
                      <tr>
                        <td colSpan={5}>
                          <div className="bg-neutral-100 rounded-[12px] py-[14px] px-4">
                            <div className="text-[10.5px] tracking-[.1em] uppercase opacity-55 mb-2">
                              Score breakdown
                            </div>
                            <Table className="w-full min-w-[420px]">
                              <thead>
                                <tr>
                                  <th>Signal</th>
                                  <th>Raw score</th>
                                  <th>Weight</th>
                                  <th>Contribution</th>
                                </tr>
                              </thead>
                              <tbody>
                                {scoreSignals(i).map((sg) => (
                                  <tr key={sg.name}>
                                    <td>{sg.name}</td>
                                    <td className="opacity-75">{sg.rawLabel}</td>
                                    <td className="opacity-75">{sg.weightLabel}</td>
                                    <td>
                                      <Tag variant="neutral" className="whitespace-nowrap">
                                        {sg.contribution}
                                      </Tag>
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </Table>
                          </div>
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                ))}
              </tbody>
            </Table>
          </TableCard>

          {filtered.length === 0 ? (
            <EmptyState
              title="Nothing matches that yet"
              body="Try fewer words, or ask the agent to draft a new template for this need."
              action={{ label: 'Clear search', onClick: () => setParams({ q: '' }) }}
            />
          ) : null}
        </div>
      </div>
    </PageBody>
  )
}
