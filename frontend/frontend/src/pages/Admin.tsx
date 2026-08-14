import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { statusClass } from '@/data/catalog'
import { useHub } from '@/store/HubProvider'
import { getTemplate, TemplateApiError, type TemplateOut } from '@/services/templates'
import { formatBytes } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { EmptyState, FormatChip, PageBody, PageHeading } from '@/components/common'
import { PromotionQueue } from '@/components/PromotionQueue'
import { Icon } from '@/components/ui/icon'

interface VerifyState {
  rowId: number
  loading: boolean
  result: TemplateOut | null
  error: string | null
}

/**
 * Doc control's view of what has come in.
 *
 * Only real uploads appear — templates POSTed to the backend during this
 * visit. The page previously padded itself out with five invented
 * submissions, a four-item "ingestion pipeline" and a table of access groups
 * with member counts, none of which corresponded to anything; the stat tiles
 * above them counted those invented rows.
 *
 * Uploads are session-scoped because the server has no submission-history
 * route, so a reload legitimately empties this list.
 */
export function Admin() {
  const { uploads, approveUpload, removeUpload, fireToast } = useHub()
  const navigate = useNavigate()
  const [verify, setVerify] = useState<VerifyState | null>(null)

  const verifyBackend = async (rowId: number, backendId: string) => {
    setVerify({ rowId, loading: true, result: null, error: null })
    try {
      const result = await getTemplate(backendId)
      setVerify({ rowId, loading: false, result, error: null })
    } catch (err) {
      setVerify({
        rowId,
        loading: false,
        result: null,
        error: err instanceof TemplateApiError ? err.message : 'Verification failed.',
      })
    }
  }

  return (
    <PageBody>
      <PageHeading title="Admin" subtitle="Doc control — templates submitted in this session." />

      {/* Server state, unlike the uploads list below: a promotion request has
          to survive the tab that raised it or nobody ever decides it. */}
      <PromotionQueue />

      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex-1 min-w-0">
          <h2 className="text-title-lg m-0">Manage templates</h2>
          <p className="text-body-md text-neutral-700 m-0">Administrator view of templates submitted in this session.</p>
        </div>
        <Button variant="primary" className="flex-none" onClick={() => navigate('/upload')}>
          <Icon name="add" size={18} />
          Upload template
        </Button>
      </div>

      {uploads.length ? (
        <div className="grid gap-4 grid-cols-[repeat(auto-fill,minmax(320px,1fr))]">
          {uploads.map((u) => (
            <article key={u.id} className="relative bg-surface border border-divider rounded-card p-5 flex flex-col gap-4 shadow-elev-sm">
              <span className={`${statusClass(u.status)} absolute top-4 right-4 uppercase`}>{u.status}</span>

              <FormatChip size={40}>{u.fmt}</FormatChip>

              <div className="min-w-0">
                <h3 className="text-title-lg m-0 mb-1 truncate pr-24">{u.name}</h3>
                <p className="text-body-md text-neutral-700 m-0">{u.meta}</p>
              </div>

              <div className="grid grid-cols-2 gap-3 text-label-md border-t border-divider pt-4">
                <div>
                  <div className="uppercase text-neutral-600 mb-1">Stored</div>
                  <div className="text-body-md text-ink">{u.backendId ? 'On the server' : 'Not confirmed'}</div>
                </div>
                <div>
                  <div className="uppercase text-neutral-600 mb-1">Note</div>
                  <div className="text-body-md text-ink truncate">{u.note}</div>
                </div>
              </div>

              <div className="flex gap-2 flex-wrap mt-auto pt-1">
                {u.backendId ? (
                  <>
                    <Button asChild variant="secondary" size="sm">
                      <a href={`/viewer/${u.backendId}`} target="_blank" rel="noopener noreferrer">
                        <Icon name="visibility" size={16} />
                        View
                      </a>
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={verify?.rowId === u.id && verify.loading}
                      onClick={() => verifyBackend(u.id, u.backendId!)}
                    >
                      {verify?.rowId === u.id && verify.loading ? 'Checking…' : 'Verify'}
                    </Button>
                  </>
                ) : null}
                {u.status === 'Approved' ? (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="ml-auto"
                    onClick={() => {
                      removeUpload(u.id)
                      fireToast(`Cleared ${u.name} from the queue`)
                    }}
                  >
                    Clear
                  </Button>
                ) : (
                  /* Publication is not gated by this: the server stores an
                     uploaded template as `active` and lists it immediately, so
                     the file is already in the library. This records the
                     decision — a real gate needs a review state on the API. */
                  <Button
                    variant="primary"
                    size="sm"
                    className="ml-auto"
                    onClick={() => {
                      approveUpload(u.id)
                      fireToast(`Approved ${u.name} — live in the library`)
                    }}
                  >
                    <Icon name="check" size={16} />
                    Approve
                  </Button>
                )}
              </div>
            </article>
          ))}
        </div>
      ) : (
        <EmptyState
          title="Nothing submitted yet"
          body="Templates you upload in this session show up here so you can confirm they really landed on the server."
          action={{ label: 'Upload a template', onClick: () => navigate('/upload') }}
        />
      )}

      <Dialog
        open={verify !== null}
        onOpenChange={(open) => !open && setVerify(null)}
        title="Backend record"
        actions={
          <Button variant="primary" onClick={() => setVerify(null)}>
            Done
          </Button>
        }
      >
        <div className="dialog-body">
          {verify?.loading ? (
            <p className="m-0">Checking the server…</p>
          ) : verify?.error ? (
            <p className="m-0 text-accent2-700">{verify.error}</p>
          ) : verify?.result ? (
            <div className="flex flex-col gap-[10px] text-[13.5px]">
              <p className="m-0 opacity-70">
                Re-read directly from <code>GET /templates/{'{id}'}</code> — this confirms the file is genuinely
                persisted in S3 and Postgres, not just accepted by the browser.
              </p>
              {[
                ['Template ID', verify.result.id],
                ['Status', verify.result.status],
                ['Storage key', verify.result.current_version?.storage_key ?? '—'],
                ['File hash', verify.result.current_version?.file_hash ?? '—'],
                ['Size', verify.result.current_version ? formatBytes(verify.result.current_version.size_bytes) : '—'],
                [
                  'Uploaded',
                  verify.result.current_version
                    ? new Date(verify.result.current_version.created_at).toLocaleString()
                    : '—',
                ],
              ].map(([label, value]) => (
                <div key={label} className="flex justify-between gap-3 border-t border-divider pt-[10px]">
                  <span className="opacity-60">{label}</span>
                  <span className="font-semibold text-right break-all">{value}</span>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      </Dialog>
    </PageBody>
  )
}
