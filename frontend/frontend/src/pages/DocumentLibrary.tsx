import { useCallback, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useHub } from '@/store/HubProvider'
import { cn, formatBytes } from '@/lib/utils'
import { downloadTemplateFile, TemplateApiError, type TemplateOut } from '@/services/templates'
import { useRealTemplates } from '@/features/document-library/useRealTemplates'
import { saveTemplateToDisk } from '@/features/document-library/saveToDisk'
import { DocumentPreview } from '@/features/document-preview/DocumentPreview'
import { Button } from '@/components/ui/button'
import { Tag } from '@/components/ui/tag'
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

type FormatFilter = (typeof FORMAT_OPTIONS)[number]['value']

const uploadedOn = (t: TemplateOut) =>
  new Date(t.current_version?.created_at ?? t.created_at).toLocaleDateString()

/**
 * Read every document in the library without leaving the page: pick a row on
 * the left, the real file renders on the right. Everything listed here is a
 * genuine backend upload.
 */
export function DocumentLibrary() {
  const navigate = useNavigate()
  const { fireToast } = useHub()
  const { templates, loading, error } = useRealTemplates()
  const [searchParams, setSearchParams] = useSearchParams()
  const [query, setQuery] = useState('')
  const [format, setFormat] = useState<FormatFilter>('all')

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return templates.filter((t) => {
      if (format !== 'all' && t.format !== format) return false
      if (!q) return true
      return `${t.title} ${t.original_filename} ${t.format}`.toLowerCase().includes(q)
    })
  }, [templates, query, format])

  /* An explicit `?doc=` wins so a deep link always lands on its document, even
     when a filter would have excluded it; otherwise follow the top result. */
  const requested = searchParams.get('doc')
  const selected = templates.find((t) => t.id === requested) ?? filtered[0] ?? null
  const selectedId = selected?.id ?? null

  const select = (id: string) => setSearchParams({ doc: id }, { replace: true })

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
    : `${filtered.length} of ${templates.length} document${templates.length === 1 ? '' : 's'}`

  return (
    <PageBody>
      <PageHeading
        title="Document library"
        subtitle="Every uploaded template, rendered in the browser — no Office install, no download needed."
      />

      {error ? (
        <Panel>
          <p className="text-[13px] text-accent2-700 m-0">{error}</p>
        </Panel>
      ) : !loading && templates.length === 0 ? (
        <Panel>
          <EmptyState
            title="No documents uploaded yet"
            body="Upload a .docx, .xlsx or .pptx template and it will show up here, ready to read."
            action={{ label: 'Upload a template', onClick: () => navigate('/upload') }}
          />
        </Panel>
      ) : (
        <div className="hub-results grid grid-cols-[320px_minmax(0,1fr)] gap-6 items-start">
          <Panel className="min-w-0">
            <div className="flex items-center gap-[9px] bg-bg border border-divider rounded-[10px] py-2 px-3 mb-3">
              <SearchIcon width={15} height={15} className="opacity-60" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Filter by name or file"
                aria-label="Filter documents"
                className="flex-1 border-0 bg-transparent outline-none font-[inherit] text-[13px] text-ink min-w-0"
              />
            </div>

            <Segmented
              name="doclibformat"
              value={format}
              options={FORMAT_OPTIONS}
              onChange={setFormat}
              className="doc-library-filter mb-3"
            />

            <div className="doc-library-list">
              {loading ? (
                <p className="text-[13px] opacity-60 m-0 py-6 text-center">Loading documents…</p>
              ) : filtered.length === 0 ? (
                <p className="text-[13px] opacity-60 m-0 py-6 text-center">Nothing matches that filter.</p>
              ) : (
                filtered.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    className={cn('doc-library-row', t.id === selectedId && 'active')}
                    aria-current={t.id === selectedId ? 'true' : undefined}
                    onClick={() => select(t.id)}
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

            <div className="text-[11.5px] opacity-50 mt-3 pt-3 border-t border-divider">{countLabel}</div>
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
                      {selected.current_version ? formatBytes(selected.current_version.size_bytes) : 'size unknown'} ·
                      uploaded {uploadedOn(selected)}
                    </p>
                  </div>
                  <Tag variant="accent2" className="flex-none whitespace-nowrap">
                    v{selected.current_version?.version_number ?? 1}
                  </Tag>
                </div>

                {/* Keyed so switching documents tears down the previous render
                    rather than leaving it on screen while the next one loads. */}
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
                    Use template
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
                  <Button
                    variant="ghost"
                    size="sm"
                    className="whitespace-nowrap"
                    onClick={() => navigate(`/templates/${selected.id}`)}
                  >
                    Open detail
                  </Button>
                </div>
              </>
            ) : (
              <p className="text-[13px] opacity-60 m-0 py-10 text-center">
                {loading ? 'Loading documents…' : 'Pick a document on the left to read it here.'}
              </p>
            )}
          </Panel>
        </div>
      )}
    </PageBody>
  )
}
