import { useCallback, useEffect, useMemo, useRef } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useHub } from '@/store/HubProvider'
import { cn, formatBytes } from '@/lib/utils'
import { downloadTemplateFile, TemplateApiError, type TemplateOut } from '@/services/templates'
import { useRealTemplates } from '@/features/document-library/useRealTemplates'
import { saveTemplateToDisk } from '@/features/document-library/saveToDisk'
import { DocumentPreview } from '@/features/document-preview/DocumentPreview'
import { RealTemplateCard } from '@/components/TemplateCard'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/ui/icon'
import {
  DocumentPreviewSkeleton,
  DocumentRowSkeleton,
  Skeleton,
  SkeletonGroup,
  TemplateCardSkeleton,
} from '@/components/ui/skeleton'
import { FilterTag, Tag } from '@/components/ui/tag'
import { Segmented } from '@/components/ui/segmented'
import { Panel, SectionLabel } from '@/components/ui/table'
import { CHIP_BY_FORMAT, EmptyState, FormatChip, PageBody, PageHeading } from '@/components/common'
import { DownloadIcon, GenerateIcon, SearchIcon } from '@/components/icons'

const FORMAT_OPTIONS = [
  { value: 'all', label: 'All' },
  { value: 'docx', label: 'DOC' },
  { value: 'xlsx', label: 'XLS' },
  { value: 'pptx', label: 'PPT' },
] as const

const VIEW_OPTIONS = [
  { value: 'grid', label: 'Grid' },
  { value: 'list', label: 'List' },
] as const

const SORT_OPTIONS = [
  { value: 'recent', label: 'Newest first' },
  { value: 'title', label: 'Title A–Z' },
  { value: 'format', label: 'Format' },
] as const

type FormatFilter = (typeof FORMAT_OPTIONS)[number]['value']
type ViewMode = (typeof VIEW_OPTIONS)[number]['value']
type SortKey = (typeof SORT_OPTIONS)[number]['value']

const ALL_CATEGORIES = 'All'

const uploadedAt = (t: TemplateOut) => new Date(t.current_version?.created_at ?? t.created_at).getTime()
const uploadedOn = (t: TemplateOut) => new Date(t.current_version?.created_at ?? t.created_at).toLocaleDateString()

/** Everything a query should be able to hit, flattened once per template. */
const haystack = (t: TemplateOut) =>
  [t.title, t.original_filename, t.format, t.form_id, t.category, t.purpose, t.when_to_use, t.audience, ...t.tags]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()

/**
 * The Templates page: the whole library as cards, each carrying the two things
 * anyone comes here to do — **Use document** and **View**.
 *
 * Grid is the default. **List** brings back the reader layout — a rail of
 * documents beside a live render — for working through several files without
 * leaving the page.
 *
 * Every control writes to the URL rather than to component state. `View`
 * navigates away to `/viewer/:id`, so the filters have to survive the trip
 * back; putting them in the query string also makes a filtered library
 * something you can bookmark or paste to someone.
 */
export function DocumentLibrary() {
  const navigate = useNavigate()
  const { fireToast } = useHub()
  const { templates, loading, error } = useRealTemplates()
  const [searchParams, setSearchParams] = useSearchParams()
  const searchRef = useRef<HTMLInputElement>(null)

  const query = searchParams.get('q') ?? ''
  const format = (FORMAT_OPTIONS.find((o) => o.value === searchParams.get('fmt'))?.value ?? 'all') as FormatFilter
  const category = searchParams.get('cat') ?? ALL_CATEGORIES
  const sort = (SORT_OPTIONS.find((o) => o.value === searchParams.get('sort'))?.value ?? 'recent') as SortKey
  const view = (VIEW_OPTIONS.find((o) => o.value === searchParams.get('view'))?.value ?? 'grid') as ViewMode

  /* Merge rather than replace: `setSearchParams(obj)` drops every key it isn't
     given, which would clear the selected document each time a filter moved.
     `replace` keeps typing in the search box out of the history stack, so one
     Back press from the viewer returns to the library rather than walking
     backwards through keystrokes. */
  const patch = useCallback(
    (next: Record<string, string | null>) => {
      setSearchParams(
        (prev) => {
          const params = new URLSearchParams(prev)
          for (const [key, value] of Object.entries(next)) {
            if (value === null || value === '') params.delete(key)
            else params.set(key, value)
          }
          return params
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  /* Only the categories the library actually holds — a fixed list would offer
     filters that return nothing. */
  const categories = useMemo(() => {
    const found = new Set<string>()
    for (const t of templates) if (t.category) found.add(t.category)
    return [ALL_CATEGORIES, ...[...found].sort((a, b) => a.localeCompare(b))]
  }, [templates])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    const matched = templates.filter((t) => {
      if (format !== 'all' && t.format !== format) return false
      if (category !== ALL_CATEGORIES && t.category !== category) return false
      if (!q) return true
      return haystack(t).includes(q)
    })

    return matched.sort((a, b) => {
      if (sort === 'title') return a.title.localeCompare(b.title)
      if (sort === 'format') return a.format.localeCompare(b.format) || a.title.localeCompare(b.title)
      return uploadedAt(b) - uploadedAt(a)
    })
  }, [templates, query, format, category, sort])

  const filtersActive = Boolean(query.trim()) || format !== 'all' || category !== ALL_CATEGORIES
  const clearFilters = () => patch({ q: null, fmt: null, cat: null })

  /* `/` is the search shortcut every library-shaped page has. Ignore it while
     someone is typing, or it swallows the character they meant to write. */
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey) return
      const el = e.target as HTMLElement | null
      if (el?.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(el?.tagName ?? '')) return
      e.preventDefault()
      searchRef.current?.focus()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  /* An explicit `?doc=` wins so a deep link always lands on its document, even
     when a filter would have excluded it; otherwise follow the top result. */
  const requested = searchParams.get('doc')
  const selected = templates.find((t) => t.id === requested) ?? filtered[0] ?? null
  const selectedId = selected?.id ?? null

  /* Identity must stay stable across renders or DocumentPreview's effect
     re-fires in a loop — keyed on the id alone, not the template object. */
  const loadBytes = useCallback(() => {
    if (!selectedId) return Promise.reject(new Error('No document selected.'))
    return downloadTemplateFile(selectedId)
  }, [selectedId])

  const handleDownload = useCallback(async () => {
    if (!selected) return
    try {
      await saveTemplateToDisk(selected)
      fireToast(`Downloaded ${selected.original_filename}`)
    } catch (err) {
      fireToast(err instanceof TemplateApiError ? err.message : 'Could not download this file.')
    }
  }, [selected, fireToast])

  const countLabel = loading
    ? 'Loading…'
    : filtersActive
      ? `${filtered.length} of ${templates.length} template${templates.length === 1 ? '' : 's'}`
      : `${templates.length} template${templates.length === 1 ? '' : 's'}`

  return (
    <PageBody>
      <div className="flex items-center gap-4 flex-wrap">
        <PageHeading
          className="flex-1 min-w-0"
          title="Templates"
          subtitle="Every approved template in the hub. Start a document from one, or open it to read the file itself."
        />
        <Button variant="primary" className="flex-none" onClick={() => navigate('/upload')}>
          <Icon name="add" size={18} />
          Upload template
        </Button>
      </div>

      {error ? (
        <Panel>
          <p className="text-body-md text-[color:var(--md-error)] m-0">{error}</p>
        </Panel>
      ) : !loading && templates.length === 0 ? (
        <EmptyState
          title="No templates uploaded yet"
          body="Upload a .docx, .xlsx or .pptx and it will appear here for everyone once an admin approves it."
          action={{ label: 'Upload a template', onClick: () => navigate('/upload') }}
        />
      ) : (
        <>
          {/* ── Toolbar ──────────────────────────────────────────────────── */}
          <Panel className="flex flex-col gap-4">
            <div className="flex items-center gap-3 flex-wrap">
              <div className="flex items-center gap-[9px] bg-bg border border-divider rounded-control py-2 px-3 flex-1 min-w-[240px]">
                <SearchIcon width={15} height={15} className="opacity-60 flex-none" />
                <input
                  ref={searchRef}
                  value={query}
                  onChange={(e) => patch({ q: e.target.value })}
                  placeholder="Filter by name, tag, purpose or file"
                  aria-label="Filter templates"
                  className="flex-1 border-0 bg-transparent outline-none font-[inherit] text-body-md text-ink min-w-0"
                />
                {query ? (
                  <Button
                    variant="bare"
                    size="icon"
                    className="w-6 h-6 flex-none text-neutral-600 hover:bg-neutral-200"
                    title="Clear search"
                    aria-label="Clear search"
                    onClick={() => patch({ q: null })}
                  >
                    <Icon name="close" size={16} />
                  </Button>
                ) : (
                  /* The shortcut is only worth advertising while it is the
                     thing to press — once there is a query, the clear button
                     is. */
                  <kbd className="flex-none text-[11px] text-neutral-500 border border-divider rounded-sm px-[5px] py-[1px] hidden sm:block">
                    /
                  </kbd>
                )}
              </div>

              <Segmented
                name="libraryformat"
                value={format}
                options={FORMAT_OPTIONS}
                onChange={(value) => patch({ fmt: value === 'all' ? null : value })}
                className="flex-none"
              />

              <label className="flex items-center gap-2 flex-none">
                <span className="sr-only">Sort by</span>
                <select
                  value={sort}
                  onChange={(e) => patch({ sort: e.target.value === 'recent' ? null : e.target.value })}
                  aria-label="Sort templates"
                  className="input w-auto min-h-[38px] py-[7px] cursor-pointer"
                >
                  {SORT_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </label>

              <Segmented
                name="libraryview"
                value={view}
                options={VIEW_OPTIONS}
                onChange={(value) => patch({ view: value === 'grid' ? null : value })}
                className="flex-none"
              />
            </div>

            {categories.length > 1 ? (
              <div className="flex items-center gap-2 flex-wrap">
                <SectionLabel className="mb-0 flex-none">Category</SectionLabel>
                {categories.map((c) => (
                  <FilterTag
                    key={c}
                    selected={category === c}
                    onClick={() => patch({ cat: c === ALL_CATEGORIES ? null : c })}
                  >
                    {c}
                  </FilterTag>
                ))}
              </div>
            ) : null}

            <div className="flex items-center gap-3 flex-wrap border-t border-divider pt-3 text-label-md text-neutral-600">
              <span>{countLabel}</span>
              {filtersActive ? (
                <Button variant="ghost" size="xs" className="ml-auto" onClick={clearFilters}>
                  <Icon name="filter_alt_off" size={16} />
                  Clear filters
                </Button>
              ) : null}
            </div>
          </Panel>

          {/* ── Grid ─────────────────────────────────────────────────────── */}
          {view === 'grid' ? (
            loading ? (
              <SkeletonGroup
                label="Loading templates"
                className="grid gap-5 grid-cols-[repeat(auto-fill,minmax(320px,1fr))] items-stretch"
              >
                {Array.from({ length: 6 }).map((_, i) => (
                  <TemplateCardSkeleton key={i} />
                ))}
              </SkeletonGroup>
            ) : filtered.length === 0 ? (
              <EmptyState
                size="md"
                title="Nothing matches those filters"
                body="No template in the library matches the search and filters currently applied."
                action={{ label: 'Clear filters', onClick: clearFilters }}
              />
            ) : (
              <div className="grid gap-5 grid-cols-[repeat(auto-fill,minmax(320px,1fr))] items-stretch">
                {filtered.map((t) => (
                  <RealTemplateCard key={t.id} template={t} />
                ))}
              </div>
            )
          ) : (
            /* ── List: the reader layout ────────────────────────────────── */
            <div className="hub-results grid grid-cols-[320px_minmax(0,1fr)] gap-6 items-start">
              <Panel className="min-w-0">
                <div className="doc-library-list">
                  {loading ? (
                    /* Eight rows because the rail shows roughly that many
                       before it scrolls — enough that the list arrives into a
                       filled column rather than growing into one. */
                    <SkeletonGroup label="Loading templates" className="flex flex-col gap-[2px]">
                      {Array.from({ length: 8 }).map((_, i) => (
                        <DocumentRowSkeleton key={i} />
                      ))}
                    </SkeletonGroup>
                  ) : filtered.length === 0 ? (
                    <p className="text-body-md text-neutral-600 m-0 py-6 text-center">
                      Nothing matches those filters.
                    </p>
                  ) : (
                    filtered.map((t) => (
                      <button
                        key={t.id}
                        type="button"
                        className={cn('doc-library-row', t.id === selectedId && 'active')}
                        aria-current={t.id === selectedId ? 'true' : undefined}
                        onClick={() => patch({ doc: t.id })}
                      >
                        <FormatChip size={32} tone={t.id === selectedId ? 'accent' : 'accent2'}>
                          {CHIP_BY_FORMAT[t.format]}
                        </FormatChip>
                        <span className="flex-1 min-w-0">
                          <span className="block text-[13.5px] font-semibold truncate">{t.title}</span>
                          <span className="block text-[11.5px] opacity-55 truncate">{t.original_filename}</span>
                          <span className="block text-[11px] opacity-45 mt-[2px]">
                            {t.current_version ? formatBytes(t.current_version.size_bytes) : 'size unknown'} ·{' '}
                            {uploadedOn(t)}
                          </span>
                        </span>
                      </button>
                    ))
                  )}
                </div>
              </Panel>

              <Panel className="min-w-0">
                {selected ? (
                  <>
                    <div className="flex items-start gap-3 flex-wrap mb-[14px]">
                      <div className="flex-1 min-w-0">
                        <SectionLabel className="mb-1">Live preview</SectionLabel>
                        <h4 className="m-0 truncate">{selected.title}</h4>
                        <p className="text-[11.5px] opacity-55 m-0 mt-[3px] truncate">
                          {selected.original_filename} ·{' '}
                          {selected.current_version
                            ? formatBytes(selected.current_version.size_bytes)
                            : 'size unknown'}{' '}
                          · uploaded {uploadedOn(selected)}
                        </p>
                      </div>
                      <Tag variant="accent2" className="flex-none whitespace-nowrap">
                        v{selected.current_version?.version_number ?? 1}
                      </Tag>
                    </div>

                    {/* Keyed so switching documents tears down the previous
                        render rather than leaving it on screen while the next
                        one loads. */}
                    <DocumentPreview
                      key={selected.id}
                      format={selected.format}
                      fileName={selected.original_filename}
                      loadBytes={loadBytes}
                    />

                    <div className="flex gap-2 flex-wrap mt-[14px]">
                      <Button
                        variant="primary"
                        size="sm"
                        className="gap-[7px] whitespace-nowrap"
                        onClick={() => navigate(`/templates/${selected.id}/generate`)}
                      >
                        <GenerateIcon width={14} height={14} />
                        Use document
                      </Button>
                      {/* Same destination as the card's View, so the two
                          layouts don't disagree about where the button goes.
                          The Details link that used to sit beside it pointed
                          there too. */}
                      <Button
                        variant="secondary"
                        size="sm"
                        className="gap-[7px] whitespace-nowrap"
                        onClick={() => navigate(`/templates/${selected.id}`)}
                      >
                        <Icon name="visibility" size={16} />
                        View
                      </Button>
                      <Button
                        variant="secondary"
                        size="sm"
                        className="gap-[7px] whitespace-nowrap"
                        onClick={handleDownload}
                      >
                        <DownloadIcon width={14} height={14} />
                        Download
                      </Button>
                    </div>
                  </>
                ) : loading ? (
                  /* The reader is about to auto-select the first document, so
                     this pane is genuinely pending rather than idle — a
                     skeleton says that, where "Pick a document" would be an
                     instruction the page is about to carry out itself. */
                  <>
                    <div className="flex items-start gap-3 mb-[14px]">
                      <div className="flex-1 min-w-0 flex flex-col gap-2">
                        <Skeleton height={10} width={88} rounded="sm" />
                        <Skeleton height={16} width="46%" />
                        <Skeleton height={11} width="68%" rounded="sm" />
                      </div>
                      <Skeleton width={38} height={22} rounded="pill" className="flex-none" />
                    </div>
                    <DocumentPreviewSkeleton />
                    <div className="flex gap-2 mt-[14px]">
                      <Skeleton width={130} height={32} rounded="pill" />
                      <Skeleton width={92} height={32} rounded="pill" />
                      <Skeleton width={110} height={32} rounded="pill" />
                    </div>
                  </>
                ) : (
                  <p className="text-body-md text-neutral-600 m-0 py-10 text-center">
                    Pick a template on the left to read it here.
                  </p>
                )}
              </Panel>
            </div>
          )}
        </>
      )}
    </PageBody>
  )
}
