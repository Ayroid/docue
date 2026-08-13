import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { CATS, ROLE_PACKS, SEARCH_EXAMPLES, TEMPLATES } from '@/data/mock'
import { useHub } from '@/store/HubProvider'
import { filterTemplates } from '@/services/search'
import { listTemplates, TemplateApiError, type TemplateOut } from '@/services/templates'
import { Button } from '@/components/ui/button'
import { FilterTag, Tag } from '@/components/ui/tag'
import { Segmented } from '@/components/ui/segmented'
import { TableCard, Table } from '@/components/ui/table'
import { EmptyState, FormatChip, PageBody, PageHeading } from '@/components/common'
import { RealTemplateCard, TemplateCard } from '@/components/TemplateCard'
import { SearchIcon } from '@/components/icons'

const VIEW_OPTIONS = [
  { value: 'grid', label: 'Grid' },
  { value: 'table', label: 'Table' },
] as const

export function Discovery() {
  const { templates } = useHub()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [cat, setCat] = useState('All')
  const [view, setView] = useState<'grid' | 'table'>('grid')

  const filtered = useMemo(() => filterTemplates(templates, query, cat), [templates, query, cat])
  const searching = query.trim() !== '' || cat !== 'All'

  const resultLabel = searching
    ? `${filtered.length} template${filtered.length === 1 ? '' : 's'} matching your search`
    : '128 approved templates · ordered by how often your team uses them'

  const recent = [4, 1, 3, 8]
    .map((id) => TEMPLATES.find((t) => t.id === id))
    .filter((t): t is (typeof TEMPLATES)[number] => Boolean(t))

  const submit = () => navigate(`/search?q=${encodeURIComponent(query)}`)

  const [realTemplates, setRealTemplates] = useState<TemplateOut[]>([])
  const [realLoading, setRealLoading] = useState(true)
  const [realError, setRealError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    listTemplates()
      .then((result) => {
        if (!cancelled) setRealTemplates(result)
      })
      .catch((err) => {
        if (!cancelled) setRealError(err instanceof TemplateApiError ? err.message : 'Could not load templates.')
      })
      .finally(() => {
        if (!cancelled) setRealLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <PageBody>
      <PageHeading center title="Discovery" subtitle={resultLabel} />

      <div className="flex items-center gap-[9px] bg-surface border border-divider rounded-[10px] py-3 px-5 max-w-[720px] mx-auto mb-[14px]">
        <SearchIcon className="opacity-60" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
          placeholder="Describe the document you need — e.g. test script for a payment API"
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

      <div className="flex gap-[9px] flex-wrap mb-[26px]">
        {CATS.map((c) => (
          <FilterTag key={c} selected={cat === c} onClick={() => setCat(c)}>
            {c}
          </FilterTag>
        ))}
      </div>

      {!searching ? (
        <div className="mb-[34px]">
          <h4 className="mb-[14px]">Start from your role</h4>
          <div className="grid gap-[14px] grid-cols-[repeat(auto-fill,minmax(210px,1fr))]">
            {ROLE_PACKS.map((r) => (
              <button
                key={r.name}
                type="button"
                className="flex items-center gap-3 bg-accent2-100 border-0 cursor-pointer font-[inherit] text-ink text-left w-full rounded-[12px] py-[13px] px-[15px]"
                onClick={() => navigate(`/search?q=${encodeURIComponent(r.q)}`)}
              >
                <FormatChip size={34} tone="accent2">
                  {r.fmt}
                </FormatChip>
                <div className="flex-1 min-w-0">
                  <div className="text-[13.5px] font-semibold truncate">{r.name}</div>
                  <div className="text-[11.5px] opacity-60">{r.when}</div>
                </div>
              </button>
            ))}
          </div>
        </div>
      ) : null}

      <div className="mb-9">
        <h4 className="mb-[14px]">Real Templates</h4>
        {realLoading ? (
          <p className="text-[13px] opacity-60 m-0">Loading templates from the server…</p>
        ) : realError ? (
          <p className="text-[13px] text-accent2-700 m-0">{realError}</p>
        ) : realTemplates.length === 0 ? (
          <p className="text-[13px] opacity-60 m-0">No templates uploaded to the backend yet.</p>
        ) : (
          <div className="grid gap-[18px] grid-cols-[repeat(auto-fill,minmax(290px,1fr))]">
            {realTemplates.map((t) => (
              <RealTemplateCard key={t.id} template={t} />
            ))}
          </div>
        )}
      </div>

      <div className="flex items-center gap-4 flex-wrap mb-[14px]">
        <h4 className="m-0">Most used</h4>
        <div className="ml-auto flex gap-2 items-center">
          <Segmented name="hubview" value={view} options={VIEW_OPTIONS} onChange={setView} />
        </div>
      </div>

      {view === 'grid' ? (
        <div className="grid gap-[18px] grid-cols-[repeat(auto-fill,minmax(290px,1fr))]">
          {filtered.map((t) => (
            <TemplateCard key={t.id} template={t} meta="uses" />
          ))}
        </div>
      ) : (
        <TableCard>
          <Table>
            <thead>
              <tr>
                <th>Template</th>
                <th>Category</th>
                <th>Owner</th>
                <th>Version</th>
                <th>Uses</th>
                <th>Updated</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {filtered.map((t) => (
                <tr key={t.id}>
                  <td>
                    <div className="flex items-center gap-[11px]">
                      <FormatChip size={30}>{t.fmt}</FormatChip>
                      <span className="font-semibold">{t.name}</span>
                    </div>
                  </td>
                  <td className="opacity-75">{t.category}</td>
                  <td className="opacity-75">{t.owner}</td>
                  <td>
                    <Tag variant="accent2">v{t.version}</Tag>
                  </td>
                  <td className="opacity-75">{t.uses}</td>
                  <td className="opacity-75">{t.updated}</td>
                  <td>
                    <Button
                      variant="primary"
                      size="xs"
                      className="whitespace-nowrap"
                      onClick={() => navigate(`/templates/${t.id}/generate`)}
                    >
                      Generate
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        </TableCard>
      )}

      <div className="mt-9" />
      <div className="flex items-center gap-4 flex-wrap mb-[14px]">
        <h4 className="m-0">Recently updated</h4>
      </div>
      {view === 'grid' ? (
        <div className="grid gap-[18px] grid-cols-[repeat(auto-fill,minmax(290px,1fr))]">
          {recent.map((t) => (
            <TemplateCard key={t.id} template={t} meta="version" />
          ))}
        </div>
      ) : null}

      {filtered.length === 0 ? (
        <EmptyState
          title="Nothing matches that yet"
          body="Try fewer words, or ask the agent to draft a new template for this need."
          action={{
            label: 'Clear search',
            onClick: () => {
              setQuery('')
              setCat('All')
            },
          }}
        />
      ) : null}
    </PageBody>
  )
}
