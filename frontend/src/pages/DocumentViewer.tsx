import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { formatBytes } from '@/lib/utils'
import { downloadTemplateFile, getTemplate, TemplateApiError, type TemplateOut } from '@/services/templates'
import { saveTemplateToDisk } from '@/features/document-library/saveToDisk'
import { DocumentStage } from '@/features/document-preview/DocumentStage'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/ui/icon'
import { Tag } from '@/components/ui/tag'
import { DocumentPreviewSkeleton } from '@/components/ui/skeleton'
import { DownloadIcon } from '@/components/icons'

type Load = { state: 'loading' } | { state: 'ready'; template: TemplateOut } | { state: 'failed'; message: string }

/**
 * A document on a page of its own, opened from the detail page's "Open full
 * page".
 *
 * Deliberately outside `AppShell`: this route is meant to be a browser tab you
 * read a document in, so it gets the full window width rather than sharing it
 * with the app's sidebar.
 *
 * It *is* session-gated, which it could not be before: the session used to live
 * in memory, so a freshly-opened tab was always signed out and a check here
 * would have bounced every one of these links to the landing page. The token is
 * in `localStorage` now, so a new tab carries the session and the guard costs
 * these links nothing. It also has to be gated — an unapproved template is
 * refused to everyone but its submitter and the admins, and reaching that
 * decision needs the request to be authenticated.
 */
export function DocumentViewer() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [load, setLoad] = useState<Load>({ state: 'loading' })
  const [downloadNote, setDownloadNote] = useState<string | null>(null)

  /* This is normally a fresh tab, which has nothing behind it — `navigate(-1)`
     would leave the reader staring at a blank one. A history length of 1 is
     exactly that case, and the Templates page is the sensible way back into the
     app from a tab that was opened straight at a document. */
  const goBack = useCallback(() => {
    if (window.history.length > 1) navigate(-1)
    else navigate('/library')
  }, [navigate])

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
        const message =
          err instanceof TemplateApiError && err.status === 404
            ? 'This document is no longer in the library.'
            : err instanceof TemplateApiError
              ? err.message
              : 'Could not open this document.'
        setLoad({ state: 'failed', message })
      })

    return () => {
      cancelled = true
    }
  }, [id])

  const template = load.state === 'ready' ? load.template : null

  /* Name the browser tab after the file — several of these are usually open at
     once, and "Docue" on all of them tells you nothing. */
  useEffect(() => {
    if (!template) return
    const previous = document.title
    document.title = `${template.original_filename} · Docue`
    return () => {
      document.title = previous
    }
  }, [template])

  /* Keyed on the id alone: a new function identity on every render would
     re-fire DocumentPreview's effect in a loop. */
  const loadBytes = useCallback(() => {
    if (!id) return Promise.reject(new Error('No document requested.'))
    return downloadTemplateFile(id)
  }, [id])

  const handleDownload = useCallback(async () => {
    if (!template) return
    setDownloadNote(null)
    try {
      await saveTemplateToDisk(template)
    } catch (err) {
      /* No toast out here — AppShell owns that chrome and this page sits
         outside it, so say it in place. */
      setDownloadNote(err instanceof TemplateApiError ? err.message : 'Could not download this file.')
    }
  }, [template])

  const version = template?.current_version

  if (!template) {
    return (
      <div className="min-h-screen bg-neutral-200">
        <header className="flex items-center gap-3 bg-surface border-b border-divider py-[16px] px-[clamp(14px,3vw,28px)]">
          <Button variant="secondary" size="sm" className="flex-none whitespace-nowrap" onClick={goBack}>
            <Icon name="arrow_back" size={16} />
            Back
          </Button>
          <span className="text-[13px] opacity-60">
            {load.state === 'failed' ? 'Document unavailable' : 'Opening document…'}
          </span>
        </header>
        {load.state === 'failed' ? (
          <p className="text-[14px] text-accent2-700 text-center py-20 px-5 m-0">{load.message}</p>
        ) : (
          /* The format is unknown until the metadata lands, so this is always
             the page variant -- a grid here would be a guess, and guessing
             wrong means the placeholder and the render disagree. */
          <div className="max-w-[900px] mx-auto py-8 px-[clamp(14px,3vw,28px)]">
            <DocumentPreviewSkeleton />
          </div>
        )}
      </div>
    )
  }

  return (
    <DocumentStage
      className="min-h-screen"
      format={template.format}
      fileName={template.original_filename}
      title={template.title}
      meta={`${template.original_filename}${version ? ` · ${formatBytes(version.size_bytes)}` : ''} · uploaded ${new Date(
        version?.created_at ?? template.created_at,
      ).toLocaleDateString()}`}
      loadBytes={loadBytes}
      leading={
        <Button variant="secondary" size="sm" className="flex-none whitespace-nowrap" onClick={goBack}>
          <Icon name="arrow_back" size={16} />
          Back
        </Button>
      }
      actions={
        <>
          <Tag variant="accent2" className="flex-none whitespace-nowrap">
            v{version?.version_number ?? 1}
          </Tag>
          {downloadNote ? <span className="text-[12px] text-accent2-700 whitespace-nowrap">{downloadNote}</span> : null}
          <Button
            variant="primary"
            size="sm"
            className="gap-[7px] whitespace-nowrap flex-none"
            onClick={() => navigate(`/templates/${template.id}/generate`)}
          >
            <Icon name="edit_document" size={16} />
            Use document
          </Button>
          <Button
            variant="secondary"
            size="sm"
            className="gap-[7px] whitespace-nowrap flex-none"
            onClick={handleDownload}
          >
            <DownloadIcon width={14} height={14} />
            Download
          </Button>
          {/* A router Link now rather than a plain anchor: this page is reached
              from inside the app as well as in a fresh tab, and a full reload
              on the in-app path throws away the session's warm state for
              nothing. It works in a fresh tab too — the route is inside the
              router either way. */}
          <Button asChild variant="ghost" size="sm" className="whitespace-nowrap flex-none">
            <Link to={`/templates/${template.id}`}>Details</Link>
          </Button>
        </>
      }
    />
  )
}
