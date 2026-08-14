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
import { DocumentPreviewSkeleton, Skeleton, SkeletonGroup } from '@/components/ui/skeleton'
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
          /* The real page's own shape — breadcrumb, title block, then the
             preview beside its details rail. Landing on this and then having it
             replaced in place is the point; the single centred line it replaced
             threw the whole layout in at once. */
          <SkeletonGroup label="Loading document" className="flex flex-col gap-6">
            <div className="flex items-center gap-2">
              <Skeleton height={12} width={72} rounded="sm" />
              <Skeleton height={12} width={40} rounded="sm" />
              <Skeleton height={12} width={140} rounded="sm" />
            </div>

            <div className="flex items-start gap-4">
              <Skeleton width={40} height={40} rounded="md" className="flex-none" />
              <div className="min-w-0 flex-1 flex flex-col gap-2">
                <Skeleton height={24} width="44%" />
                <Skeleton height={13} width="30%" rounded="sm" />
              </div>
              <Skeleton width={124} height={38} rounded="pill" className="flex-none" />
            </div>

            <div className="hub-results grid grid-cols-[minmax(0,1fr)_320px] gap-6 items-start">
              <div className="bg-surface border border-divider rounded-card p-5 min-w-0">
                <div className="flex items-center gap-2 mb-[14px]">
                  <Skeleton width={86} height={22} rounded="pill" />
                  <Skeleton height={11} width={150} rounded="sm" />
                  <Skeleton width={128} height={30} rounded="pill" className="ml-auto" />
                </div>
                <DocumentPreviewSkeleton />
              </div>

              <div className="bg-surface border border-divider rounded-card p-5">
                <Skeleton height={11} width={78} rounded="sm" className="mb-4" />
                <div className="flex flex-col gap-3">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <div key={i} className="flex justify-between gap-3 border-t border-divider pt-3 first:border-0 first:pt-0">
                      <Skeleton height={12} width={64} rounded="sm" />
                      <Skeleton height={12} width={88} rounded="sm" />
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </SkeletonGroup>
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
        {/* Named "Templates", so it goes to the Templates page. It pointed at
            Discovery, which is the front door — a crumb that lands somewhere
            other than the thing it is named after is a wrong turn. */}
        <button type="button" className="bg-transparent border-0 p-0 cursor-pointer font-[inherit] text-label-md hover:text-accent" onClick={() => navigate('/library')}>
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
        </div>
      </div>

      {/* No metadata strip: every fact it carried — status, version, size and
          the date — is already in the File details panel beside the preview. */}

      {/* Only ever renders for the submitter or an admin: the API refuses an
          unapproved template to anyone else, so reaching this page at all means
          the reader is entitled to know where it stands. Without it, someone
          who has just uploaded sees a template that is simply missing from the
          library with nothing explaining why. */}
      {doc.approval_status !== 'approved' ? (
        <div
          className={`rounded-card border py-3 px-4 ${
            doc.approval_status === 'rejected'
              ? 'border-[color:var(--md-error)]/30 bg-[color:var(--md-error)]/10'
              : 'border-accent2-400/40 bg-accent2-100'
          }`}
        >
          <div className="flex items-start gap-3">
            <Icon
              name={doc.approval_status === 'rejected' ? 'error' : 'pending_actions'}
              size={20}
              className="flex-none mt-[2px]"
            />
            <div className="min-w-0">
              <div className="text-body-md font-semibold text-ink">
                {doc.approval_status === 'rejected'
                  ? 'Rejected by an admin'
                  : 'Waiting on an admin'}
              </div>
              <p className="text-body-md text-neutral-700 m-0">
                {doc.approval_status === 'rejected'
                  ? 'This version was not published. Upload a corrected file when it is ready.'
                  : 'It is not in the library or in search results until an admin approves it. You will be notified here and by email.'}
              </p>
              {doc.review_note ? (
                <p className="text-body-md text-ink m-0 mt-2">
                  <span className="text-label-md uppercase text-neutral-600">Reviewer’s note — </span>
                  {doc.review_note}
                </p>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

      <div className="hub-results grid grid-cols-[minmax(0,1fr)_320px] gap-6 items-start">
        <Panel className="min-w-0">
          <div className="flex items-center gap-2 mb-[14px]">
            <Tag variant="accent" className="whitespace-nowrap">
              Live preview
            </Tag>
            <span className="text-[11.5px] opacity-50 truncate">{doc.original_filename}</span>

            {/* Sits with the preview it acts on rather than in the page header:
                "open full page" means this pane, full width. */}
            <Button asChild variant="primary" size="sm" className="ml-auto flex-none whitespace-nowrap">
              <a href={`/viewer/${doc.id}`} target="_blank" rel="noopener noreferrer">
                <Icon name="open_in_new" size={16} />
                Open full page
              </a>
            </Button>
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

            {/* Directly under the metadata it acts on: this changes what the
                facts above will say. It leads to a choice rather than doing
                anything, so it is a secondary button and says "Update", not
                "Upload" or "Edit" — either of those would name one of the two
                routes and hide the other. */}
            <Button
              variant="secondary"
              block
              className="mt-5 whitespace-nowrap"
              onClick={() => navigate(`/templates/${doc.id}/update`)}
            >
              <Icon name="edit_document" size={18} />
              Update document
            </Button>
          </div>

          {/* Every version of this template, with what each one changed. */}
          <VersionHistory templateId={doc.id} />
        </div>
      </div>
    </PageBody>
  )
}
