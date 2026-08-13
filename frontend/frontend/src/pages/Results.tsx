import { useMemo, useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useRealTemplates } from '@/features/document-library/useRealTemplates'
import { filterTemplates } from '@/services/search'
import { formatBytes } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Tag } from '@/components/ui/tag'
import { Icon } from '@/components/ui/icon'
import { CHIP_BY_FORMAT, EmptyState, FormatChip, PageBody } from '@/components/common'

/* Only format is offered. The backend records no owner, version status or
   last-updated window, so every other facet would filter on nothing. */
const FORMATS = [
  { value: 'docx', label: 'Word (.docx)' },
  { value: 'xlsx', label: 'Excel (.xlsx)' },
  { value: 'pptx', label: 'PowerPoint (.pptx)' },
] as const

export function Results() {
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const query = params.get('q') ?? ''

  const [format, setFormat] = useState('all')
  const [draftQuery, setDraftQuery] = useState(query)

  const { templates, loading, error } = useRealTemplates()
  const results = useMemo(() => filterTemplates(templates, query, format), [templates, query, format])

  const submit = (e: FormEvent) => {
    e.preventDefault()
    setParams({ q: draftQuery })
  }

  return (
    <PageBody>
      <form onSubmit={submit} className="relative flex items-center max-w-3xl w-full">
        <Icon name="search" size={20} className="absolute left-4 text-neutral-500 pointer-events-none" />
        <input
          value={draftQuery}
          onChange={(e) => setDraftQuery(e.target.value)}
          placeholder="Search the library by name or file"
          aria-label="Search the library"
          className="input pl-12 rounded-pill"
        />
      </form>

      <div className="hub-results grid grid-cols-[280px_minmax(0,1fr)] gap-6 items-start">
        {/* ── Filter rail ────────────────────────────────────────────────── */}
        <aside className="flex flex-col gap-4">
          <div className="bg-neutral-200 border border-divider rounded-card p-4">
            <h3 className="text-title-lg m-0 mb-1">Search results</h3>
            <p className="text-body-md text-neutral-700 m-0">
              {loading
                ? 'Searching the library…'
                : `${results.length} template${results.length === 1 ? '' : 's'} found${query ? ` for "${query}"` : ''}`}
            </p>
          </div>

          <div className="bg-surface border border-divider rounded-card p-4">
            <div className="text-label-md uppercase text-neutral-600 mb-3">Format</div>
            <div className="flex flex-col gap-1">
              {FORMATS.map((f) => {
                const on = format === f.value
                return (
                  <label
                    key={f.value}
                    className="flex items-center gap-3 py-1.5 px-1 rounded-md cursor-pointer hover:bg-neutral-200 transition-colors"
                  >
                    <input
                      type="checkbox"
                      checked={on}
                      onChange={() => setFormat(on ? 'all' : f.value)}
                      className="w-4 h-4 accent-[color:var(--md-secondary)] cursor-pointer"
                    />
                    <span className="text-body-md">{f.label}</span>
                  </label>
                )
              })}
            </div>
            {format !== 'all' ? (
              <Button variant="ghost" size="sm" className="mt-3 px-1" onClick={() => setFormat('all')}>
                Clear filter
              </Button>
            ) : null}
          </div>
        </aside>

        {/* ── Results ────────────────────────────────────────────────────── */}
        <div className="flex flex-col gap-4 min-w-0">
          {error ? (
            <div className="bg-surface border border-divider rounded-card p-5 text-body-md text-[color:var(--md-error)]">
              {error}
            </div>
          ) : results.length ? (
            results.map((t, i) => (
              <article
                key={t.id}
                className={`bg-surface border border-divider rounded-card p-5 flex gap-4 items-start transition-shadow ${
                  i === 0 ? 'shadow-elev-md' : 'shadow-elev-sm hover:shadow-elev-md'
                }`}
              >
                <FormatChip size={40}>{CHIP_BY_FORMAT[t.format]}</FormatChip>

                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-3 flex-wrap mb-1">
                    <h3 className="text-title-lg m-0 truncate">{t.title}</h3>
                    <Tag variant="accent" className="whitespace-nowrap">
                      <Icon name="check_circle" size={13} filled />v{t.current_version?.version_number ?? 1}
                    </Tag>
                  </div>
                  <p className="text-body-md text-neutral-700 m-0 mb-3 truncate">{t.original_filename}</p>
                  <div className="flex items-center gap-4 flex-wrap text-label-md text-neutral-600">
                    <span className="inline-flex items-center gap-1.5">
                      <Icon name="database" size={14} />
                      {t.current_version ? formatBytes(t.current_version.size_bytes) : 'size unknown'}
                    </span>
                    <span className="inline-flex items-center gap-1.5">
                      <Icon name="schedule" size={14} />
                      Uploaded {new Date(t.current_version?.created_at ?? t.created_at).toLocaleDateString()}
                    </span>
                    <Tag variant="neutral" className="uppercase">
                      {t.format}
                    </Tag>
                  </div>
                </div>

                <div className="flex flex-col gap-2 flex-none">
                  <Button asChild variant="primary" size="sm">
                    <a href={`/viewer/${t.id}`} target="_blank" rel="noopener noreferrer">
                      <Icon name="visibility" size={16} />
                      View
                    </a>
                  </Button>
                  <Button variant="secondary" size="sm" onClick={() => navigate(`/templates/${t.id}`)}>
                    Details
                  </Button>
                </div>
              </article>
            ))
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
