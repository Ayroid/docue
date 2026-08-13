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
      <div className="flex items-start gap-4 flex-wrap mb-[22px]">
        <div className="min-w-0">
          <Button
            variant="ghost"
            className="py-1 px-2 mb-[6px] whitespace-nowrap"
            onClick={() => navigate('/discovery')}
          >
            Back to Discovery
          </Button>
          <h2 className="text-[clamp(24px,2.6vw,32px)] mb-1">{doc.title}</h2>
          <p className="opacity-65 text-[14px] m-0">
            {doc.format.toUpperCase()} · v{version?.version_number ?? 1} · uploaded{' '}
            {new Date(version?.created_at ?? doc.created_at).toLocaleDateString()}
          </p>
        </div>
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
          <Panel>
            <SectionLabel>File</SectionLabel>
            <div className="flex items-center gap-[10px] mb-3">
              <FormatChip size={38}>{CHIP_BY_FORMAT[doc.format]}</FormatChip>
              <div className="flex-1 min-w-0">
                <div className="text-[13.5px] font-semibold truncate">{doc.original_filename}</div>
                <div className="text-[11.5px] opacity-55">
                  {version ? formatBytes(version.size_bytes) : 'size unknown'}
                </div>
              </div>
            </div>
            <div className="flex flex-col gap-[10px] text-[12.5px]">
              {[
                ['Format', doc.format.toUpperCase()],
                ['Version', `v${version?.version_number ?? 1}`],
                ['Status', doc.status],
                ['Uploaded', new Date(version?.created_at ?? doc.created_at).toLocaleString()],
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between gap-3 border-t border-divider pt-[10px]">
                  <span className="opacity-60">{label}</span>
                  <span className="font-semibold text-right break-all">{value}</span>
                </div>
              ))}
            </div>
          </Panel>

          <div className="flex flex-col gap-[10px]">
            <Button asChild variant="primary" block className="mt-0 whitespace-nowrap">
              <a href={`/viewer/${doc.id}`} target="_blank" rel="noopener noreferrer">
                Open in full page
              </a>
            </Button>
            <Button
              variant="secondary"
              block
              className="mt-0 gap-[7px] whitespace-nowrap"
              onClick={handleDownload}
            >
              <DownloadIcon width={14} height={14} />
              Download
            </Button>
          </div>
        </div>
      </div>
    </PageBody>
  )
}
