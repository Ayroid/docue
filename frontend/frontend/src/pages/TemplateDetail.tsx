import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useHub } from '@/store/HubProvider'
import { formatBytes } from '@/lib/utils'
import { downloadTemplateFile, getTemplate, TemplateApiError, type TemplateOut } from '@/services/templates'
import { saveTemplateToDisk } from '@/features/document-library/saveToDisk'
import { DocumentPreview } from '@/features/document-preview/DocumentPreview'
import { Button } from '@/components/ui/button'
import { Tag } from '@/components/ui/tag'
import { Panel, SectionLabel } from '@/components/ui/table'
import { CHIP_BY_FORMAT, EmptyState, FormatChip, PageBody } from '@/components/common'
import { VersionHistory } from '@/components/VersionHistory'
import { Icon } from '@/components/ui/icon'
import { DownloadIcon } from '@/components/icons'

type Load = { state: 'loading' } | { state: 'ready'; template: TemplateOut } | { state: 'failed'; message: string }

/**
 * Everything on this page is read back from `GET /templates/{id}`.
 *
 * The prototype hung three sidebar panels here — owner, access groups and a
 * version timeline — plus a "region map" overlay of numbered fillable areas
 * and a four-page pager. None of it came from the file: the regions were fixed
 * pixel coordinates that sat in the same place whatever you opened. All of it
 * is gone until the backend can answer for those things.
 */
export function TemplateDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { fireToast } = useHub()
  const [load, setLoad] = useState<Load>({ state: 'loading' })

  useEffect(() => {
    if (!id) return
    let cancelled = false
    setLoad({ state: 'loading' })

    getTemplate(id)
      .then((template) => {
        if (!cancelled) setLoad({ state: 'ready', template })
      })
      .catch((err) => {
        if (cancelled) return
        setLoad({
          state: 'failed',
          message:
            err instanceof TemplateApiError && err.status === 404
              ? 'That document is not in the library.'
              : err instanceof TemplateApiError
                ? err.message
                : 'Could not open that document.',
        })
      })

    return () => {
      cancelled = true
    }
  }, [id])

  const template = load.state === 'ready' ? load.template : null

  const loadBytes = useCallback(() => {
    if (!id) return Promise.reject(new Error('No document requested.'))
    return downloadTemplateFile(id)
  }, [id])

  const handleDownload = useCallback(async () => {
    if (!template) return
    try {
      await saveTemplateToDisk(template)
      fireToast(`Downloaded ${template.original_filename}`)
    } catch (err) {
      fireToast(err instanceof TemplateApiError ? err.message : 'Could not download this file.')
    }
  }, [template, fireToast])

  if (load.state !== 'ready') {
    return (
      <PageBody>
        <Button variant="ghost" className="py-1 px-2 mb-[6px] whitespace-nowrap" onClick={() => navigate('/discovery')}>
          Back to Discovery
        </Button>
        {load.state === 'failed' ? (
          <EmptyState
            title="Document not found"
            body={load.message}
            action={{ label: 'Back to Discovery', onClick: () => navigate('/discovery') }}
          />
        ) : (
          <p className="text-[13px] opacity-60 py-16 text-center m-0">Loading document…</p>
        )}
      </PageBody>
    )
  }

  /* Re-read off the narrowed `load` rather than the nullable `template` above,
     which only exists so the hooks can run before this early return. */
  const doc = load.template
  const version = doc.current_version

  return (
    <PageBody>
      <nav className="flex items-center gap-2 text-label-md text-neutral-600">
        <button type="button" className="bg-transparent border-0 p-0 cursor-pointer font-[inherit] text-label-md hover:text-accent" onClick={() => navigate('/discovery')}>
          Templates
        </button>
        <Icon name="chevron_right" size={14} />
        <span className="uppercase">{doc.format}</span>
        <Icon name="chevron_right" size={14} />
        <span className="text-ink truncate max-w-[40ch]">{doc.title}</span>
      </nav>

      <div className="flex items-start gap-4 flex-wrap">
        <FormatChip size={40}>{CHIP_BY_FORMAT[doc.format]}</FormatChip>
        <div className="min-w-0 flex-1">
          <h1 className="text-headline-lg text-ink m-0 mb-1 truncate">{doc.title}</h1>
          <p className="text-body-md text-neutral-700 m-0 truncate">{doc.original_filename}</p>
        </div>
        <div className="flex gap-2 flex-none">
          <Button variant="secondary" onClick={handleDownload}>
            <DownloadIcon width={16} height={16} />
            Download
          </Button>
          <Button asChild variant="primary">
            <a href={`/viewer/${doc.id}`} target="_blank" rel="noopener noreferrer">
              <Icon name="open_in_new" size={16} />
              Open full page
            </a>
          </Button>
        </div>
      </div>

      {/* Metadata strip — one cell per fact the server actually records. */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { icon: 'verified', label: 'Status', value: doc.status },
          { icon: 'history', label: 'Current version', value: `v${version?.version_number ?? 1}` },
          { icon: 'database', label: 'Size', value: version ? formatBytes(version.size_bytes) : 'unknown' },
          {
            icon: 'calendar_today',
            label: 'Last updated',
            value: new Date(version?.created_at ?? doc.created_at).toLocaleDateString(),
          },
        ].map((m) => (
          <div key={m.label} className="bg-surface border border-divider rounded-card p-4">
            <div className="text-label-md uppercase text-neutral-600 mb-2">{m.label}</div>
            <div className="flex items-center gap-2 text-body-lg font-semibold text-ink">
              <Icon name={m.icon} size={18} className="text-accent" />
              <span className="truncate capitalize">{m.value}</span>
            </div>
          </div>
        ))}
      </div>

      <div className="hub-results grid grid-cols-[minmax(0,1fr)_320px] gap-6 items-start">
        <Panel className="min-w-0">
          <div className="flex items-center gap-2 mb-[14px]">
            <Tag variant="accent" className="whitespace-nowrap">
              Live preview
            </Tag>
            <span className="text-[11.5px] opacity-50 truncate">{doc.original_filename}</span>
          </div>

          <DocumentPreview
            format={doc.format}
            fileName={doc.original_filename}
            loadBytes={loadBytes}
          />
        </Panel>

        <div className="flex flex-col gap-4 min-w-0">
          <div className="bg-surface border border-divider rounded-card p-5">
            <SectionLabel>File details</SectionLabel>
            <div className="flex flex-col gap-3 text-body-md">
              {[
                ['Format', doc.format.toUpperCase()],
                ['Version', `v${version?.version_number ?? 1}`],
                ['Status', doc.status],
                ['Size', version ? formatBytes(version.size_bytes) : '—'],
                ['Uploaded', new Date(version?.created_at ?? doc.created_at).toLocaleString()],
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between gap-3 border-t border-divider pt-3 first:border-0 first:pt-0">
                  <span className="text-neutral-700">{label}</span>
                  <span className="font-semibold text-right break-all">{value}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Every version of this template, with what each one changed. */}
          <VersionHistory templateId={doc.id} />
        </div>
      </div>
    </PageBody>
  )
}
