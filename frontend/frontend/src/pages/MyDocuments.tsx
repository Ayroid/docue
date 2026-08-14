import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useHub } from '@/store/HubProvider'
import {
  downloadDocumentFile,
  listDocuments,
  submitAsVersion,
  DocumentApiError,
  type GeneratedDocument,
} from '@/services/documents'
import { formatBytes } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Tag } from '@/components/ui/tag'
import { EmptyState, FormatChip, PageBody, PageHeading } from '@/components/common'

const CHIP: Record<string, string> = { xlsx: 'XLS', docx: 'DOC', pptx: 'PPT' }

/**
 * Documents this account has generated, read from `GET /documents`.
 *
 * **Why this page used to be empty.** It rendered from a `useState([])` in the
 * hub provider, filled only by the commit that happened in the same browser
 * tab. There was no documents service to read from — a generated file was
 * stored as a *version* of its template, so it had no identity of its own and
 * nothing to list. A reload cleared the array and the page went blank, which
 * looked like a bug and was really a missing concept.
 *
 * Documents are their own rows now, so this is server state and survives a
 * reload, a new tab and a different machine.
 */
export function MyDocuments() {
  const { drafts, fireToast } = useHub()
  const navigate = useNavigate()

  const [documents, setDocuments] = useState<GeneratedDocument[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    listDocuments()
      .then((rows) => {
        setDocuments(rows)
        setError(null)
      })
      .catch((err: unknown) =>
        setError(
          err instanceof DocumentApiError && err.status === 401
            ? 'Sign in to see your documents.'
            : err instanceof Error
              ? err.message
              : 'Could not load your documents.',
        ),
      )
      .finally(() => setLoading(false))
  }, [])

  useEffect(load, [load])

  const download = async (doc: GeneratedDocument) => {
    try {
      await downloadDocumentFile(doc)
      fireToast(`Downloaded ${doc.title}`)
    } catch (err) {
      fireToast(err instanceof Error ? err.message : 'Could not download that document.')
    }
  }

  const submit = async (doc: GeneratedDocument) => {
    setBusy(doc.id)
    try {
      const updated = await submitAsVersion(doc.id)
      fireToast(`Sent to doc control as v${updated.promoted_version_number}`)
      setDocuments((rows) => rows.map((r) => (r.id === doc.id ? updated : r)))
    } catch (err) {
      fireToast(err instanceof Error ? err.message : 'Could not submit that document.')
    } finally {
      setBusy(null)
    }
  }

  if (loading) {
    return (
      <PageBody>
        <PageHeading title="My documents" subtitle="Documents you've generated from a template." />
        <p className="text-body-md text-neutral-700">Loading…</p>
      </PageBody>
    )
  }

  if (!documents.length && !drafts.length) {
    return (
      <PageBody>
        <PageHeading title="My documents" subtitle="Documents you've generated from a template." />
        {error ? <p className="text-body-md text-[color:var(--md-error)]">{error}</p> : null}
        <EmptyState
          title="No generated documents yet"
          body="Pick a template in the library and choose Generate to walk through creating one."
          action={{ label: 'Browse the library', onClick: () => navigate('/discovery') }}
        />
      </PageBody>
    )
  }

  return (
    <PageBody>
      <PageHeading
        title="My documents"
        subtitle={`${documents.length} document${documents.length === 1 ? '' : 's'}${
          drafts.length ? ` · ${drafts.length} in-progress draft${drafts.length === 1 ? '' : 's'}` : ''
        }`}
      />

      {error ? <p className="text-body-md text-[color:var(--md-error)]">{error}</p> : null}

      {drafts.length ? (
        <div className="mb-9">
          <h4 className="mb-[14px]">Drafts</h4>
          <div className="flex flex-col gap-3">
            {drafts.map((d) => (
              <div key={d.id} className="bg-surface rounded-card py-4 px-[18px] flex items-center gap-4 flex-wrap">
                <FormatChip size={38}>{d.fmt}</FormatChip>
                <div className="flex-[1_1_200px] min-w-[170px]">
                  <div className="font-semibold">{d.title}</div>
                  {/* Still tab-local: a draft is an unfinished conversation, and
                      the session it belongs to is already on the server. */}
                  <div className="text-[12px] opacity-55">{d.saved} · this tab only</div>
                </div>
                <Button
                  variant="primary"
                  size="sm"
                  className="ml-auto whitespace-nowrap"
                  onClick={() => navigate(`/templates/${d.templateId}/generate?session=d${d.id}`)}
                >
                  Resume
                </Button>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      <div className="flex flex-col gap-3">
        {documents.map((doc) => (
          <div
            key={doc.id}
            className="bg-surface border border-divider rounded-card py-4 px-[18px] flex items-center gap-4 flex-wrap"
          >
            <FormatChip size={38}>{CHIP[doc.format ?? ''] ?? 'DOC'}</FormatChip>

            <div className="flex-[1_1_240px] min-w-[190px]">
              <div className="font-semibold truncate">{doc.title}</div>
              <div className="text-[12px] opacity-55">
                {doc.template_title ?? 'Template'} · v{doc.base_version_number} ·{' '}
                {formatBytes(doc.size_bytes)} · {new Date(doc.created_at).toLocaleString()}
              </div>
            </div>

            {/* The template has moved on. The document is still exactly what its
                author produced, so this is information, not a warning. */}
            {!doc.base_version_is_current ? (
              <Tag variant="neutral" className="whitespace-nowrap flex-none">
                Template has moved on
              </Tag>
            ) : null}

            {doc.promoted_status ? (
              <Tag
                variant={doc.promoted_status === 'rejected' ? 'accent2' : 'accent'}
                className="whitespace-nowrap flex-none"
              >
                {doc.promoted_status === 'pending'
                  ? `Submitted as v${doc.promoted_version_number}`
                  : doc.promoted_status === 'approved'
                    ? `Published as v${doc.promoted_version_number}`
                    : `v${doc.promoted_version_number} rejected`}
              </Tag>
            ) : null}

            <div className="flex gap-2 ml-auto flex-none">
              <Button
                variant="secondary"
                size="sm"
                className="whitespace-nowrap"
                onClick={() => void download(doc)}
              >
                Download
              </Button>
              {/* Only offered once. After submitting, the badge above says what
                  happened to it, which is the more useful answer than a button
                  that would be refused. */}
              {!doc.promoted_status ? (
                <Button
                  variant="ghost"
                  size="sm"
                  className="whitespace-nowrap"
                  disabled={busy === doc.id}
                  onClick={() => void submit(doc)}
                >
                  {busy === doc.id ? 'Submitting…' : 'Submit as version'}
                </Button>
              ) : null}
            </div>
          </div>
        ))}
      </div>
    </PageBody>
  )
}
