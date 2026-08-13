import { useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useRealTemplates } from '@/features/document-library/useRealTemplates'
import { filterTemplates } from '@/services/search'
import { formatBytes } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { FilterTag, Tag } from '@/components/ui/tag'
import { Table, TableCard } from '@/components/ui/table'
import { CHIP_BY_FORMAT, EmptyState, FormatChip, PageBody } from '@/components/common'
import { CloseIcon, SearchIcon } from '@/components/icons'

/* Only format is offered. The old sidebar also filtered by owner, version
   status and last-updated window — none of which the backend records, so every
   one of those options filtered against invented fields. */
const FORMATS = [
  { value: 'docx', label: 'Word' },
  { value: 'xlsx', label: 'Excel' },
  { value: 'pptx', label: 'PowerPoint' },
] as const

export function Results() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const query = params.get('q') ?? ''

  const [format, setFormat] = useState('all')
  const [draftQuery, setDraftQuery] = useState(query)

  const { templates, loading, error } = useRealTemplates()
  const results = useMemo(() => filterTemplates(templates, query, format), [templates, query, format])

  const applied = [
    { label: `Search: ${query || 'everything'}`, clear: () => setParams({ q: '' }) },
    ...(format !== 'all'
      ? [{ label: FORMATS.find((f) => f.value === format)!.label, clear: () => setFormat('all') }]
      : []),
  ]

  return (
    <PageBody>
      <div className="flex items-center gap-[9px] bg-surface border border-divider rounded-[10px] py-3 px-5 max-w-[720px] mx-auto mb-[14px]">
        <SearchIcon className="opacity-60" />
        <input
          value={draftQuery}
          onChange={(e) => setDraftQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && setParams({ q: draftQuery })}
          placeholder="Search the library by name or file"
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
        <div className="bg-surface rounded-card p-[18px]">
          <div className="text-[10.5px] tracking-[.1em] uppercase opacity-55 mb-[10px]">Format</div>
          <div className="flex flex-col gap-[2px] items-stretch">
            {FORMATS.map((f) => {
              const on = format === f.value
              return (
                <button
                  key={f.value}
                  type="button"
                  className={`border-0 rounded-[9px] w-full text-left whitespace-nowrap cursor-pointer font-[inherit] text-[13px] py-[7px] px-[11px] ${
                    on ? 'bg-accent text-bg' : 'bg-transparent text-ink opacity-75'
                  }`}
                  onClick={() => setFormat(on ? 'all' : f.value)}
                >
                  {f.label}
                </button>
              )
            })}
          </div>
        </div>

        <div>
          <div className="flex items-center gap-4 flex-wrap mb-[14px]">
            <div>
              <h4 className="m-0">Results</h4>
              <p className="opacity-65 text-[13px] mt-[2px] mb-0">
                {loading
                  ? 'Searching the library…'
                  : `${results.length} document${results.length === 1 ? '' : 's'} matching your search`}
              </p>
            </div>
            <Button variant="ghost" className="ml-auto whitespace-nowrap" onClick={() => navigate('/discovery')}>
              Back to Discovery
            </Button>
          </div>

          {error ? (
            <p className="text-[13px] text-accent2-700 m-0">{error}</p>
          ) : results.length ? (
            <TableCard>
              <Table className="table-auto w-full min-w-[620px]">
                <thead>
                  <tr>
                    <th>Document</th>
                    <th>Size</th>
                    <th>Version</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {results.map((t) => (
                    <tr key={t.id}>
                      <td>
                        <div
                          className="flex items-start gap-[11px] min-w-0 cursor-pointer"
                          onClick={() => navigate(`/templates/${t.id}`)}
                        >
                          <FormatChip size={32}>{CHIP_BY_FORMAT[t.format]}</FormatChip>
                          <div className="min-w-0">
                            <div className="font-semibold truncate">{t.title}</div>
                            <div className="text-[12px] opacity-55 truncate">{t.original_filename}</div>
                          </div>
                        </div>
                      </td>
                      <td className="opacity-75 whitespace-nowrap">
                        {t.current_version ? formatBytes(t.current_version.size_bytes) : '—'}
                      </td>
                      <td>
                        <Tag variant="accent2" className="whitespace-nowrap">
                          v{t.current_version?.version_number ?? 1}
                        </Tag>
                      </td>
                      <td>
                        <div className="flex gap-2 justify-end">
                          <Button asChild variant="primary" size="xs" className="whitespace-nowrap">
                            <a href={`/viewer/${t.id}`} target="_blank" rel="noopener noreferrer">
                              View
                            </a>
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </TableCard>
          ) : !loading ? (
            <EmptyState
              title="Nothing matches that yet"
              body="Try fewer words, or clear the format filter."
              action={{ label: 'Clear search', onClick: () => setParams({ q: '' }) }}
            />
          ) : null}
        </div>
      </div>
    </PageBody>
  )
}
