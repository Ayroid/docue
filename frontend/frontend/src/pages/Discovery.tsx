import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { SEARCH_EXAMPLES } from '@/data/catalog'
import { useRealTemplates } from '@/features/document-library/useRealTemplates'
import { filterTemplates } from '@/services/search'
import { Button } from '@/components/ui/button'
import { FilterTag } from '@/components/ui/tag'
import { Segmented } from '@/components/ui/segmented'
import { EmptyState, PageBody, PageHeading } from '@/components/common'
import { RealTemplateCard } from '@/components/TemplateCard'
import { SearchIcon } from '@/components/icons'

/* Format is filtered rather than category: the backend records a file's
   format, and nothing else about a template that could be filtered on. The
   old category and role-pack filters sorted templates into buckets that only
   ever existed in the prototype's seed data. */
const FORMAT_OPTIONS = [
  { value: 'all', label: 'All' },
  { value: 'docx', label: 'Word' },
  { value: 'xlsx', label: 'Excel' },
  { value: 'pptx', label: 'PowerPoint' },
] as const

type FormatFilter = (typeof FORMAT_OPTIONS)[number]['value']

export function Discovery() {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [format, setFormat] = useState<FormatFilter>('all')

  const { templates, loading, error } = useRealTemplates()
  const filtered = useMemo(() => filterTemplates(templates, query, format), [templates, query, format])

  const submit = () => navigate(`/search?q=${encodeURIComponent(query)}`)

  const subtitle = loading
    ? 'Loading the library…'
    : error
      ? 'The library is unavailable right now.'
      : `${templates.length} document${templates.length === 1 ? '' : 's'} in the library`

  return (
    <PageBody>
      <PageHeading center title="Discovery" subtitle={subtitle} />

      <div className="flex items-center gap-[9px] bg-surface border border-divider rounded-[10px] py-3 px-5 max-w-[720px] mx-auto mb-[14px]">
        <SearchIcon className="opacity-60" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
          placeholder="Search the library by name or file"
          className="flex-1 border-0 bg-transparent outline-none font-[inherit] text-[15px] text-ink min-w-0"
        />
      </div>

      <div className="flex gap-[9px] flex-wrap justify-center mb-7">
        {SEARCH_EXAMPLES.map((q) => (
          <FilterTag key={q} onClick={() => setQuery(q)}>
            {q}
          </FilterTag>
        ))}
      </div>

      <div className="flex items-center gap-4 flex-wrap mb-[18px]">
        <h4 className="m-0">Library</h4>
        <Segmented name="hubformat" value={format} options={FORMAT_OPTIONS} onChange={setFormat} className="ml-auto" />
        <Button variant="ghost" size="sm" className="whitespace-nowrap" onClick={() => navigate('/library')}>
          Open reader
        </Button>
      </div>

      {loading ? (
        <p className="text-[13px] opacity-60 m-0">Loading the library…</p>
      ) : error ? (
        <p className="text-[13px] text-accent2-700 m-0">{error}</p>
      ) : templates.length === 0 ? (
        <EmptyState
          title="The library is empty"
          body="Upload a .docx, .xlsx or .pptx and it will appear here for everyone to find."
          action={{ label: 'Upload a template', onClick: () => navigate('/upload') }}
        />
      ) : filtered.length === 0 ? (
        <EmptyState
          title="Nothing matches that yet"
          body="Try fewer words, or clear the format filter."
          action={{
            label: 'Clear search',
            onClick: () => {
              setQuery('')
              setFormat('all')
            },
          }}
        />
      ) : (
        <div className="grid gap-[18px] grid-cols-[repeat(auto-fill,minmax(290px,1fr))]">
          {filtered.map((t) => (
            <RealTemplateCard key={t.id} template={t} />
          ))}
        </div>
      )}
    </PageBody>
  )
}
