import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { statusClass } from '@/data/catalog'
import { useHub } from '@/store/HubProvider'
import { getTemplate, TemplateApiError, type TemplateOut } from '@/services/templates'
import { formatBytes } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Table, TableCard } from '@/components/ui/table'
import { Dialog } from '@/components/ui/dialog'
import { EmptyState, FormatChip, PageBody, PageHeading } from '@/components/common'

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
  const { uploads, removeUpload, fireToast } = useHub()
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

      {uploads.length ? (
        <TableCard>
          <Table>
            <thead>
              <tr>
                <th>Submission</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {uploads.map((u) => (
                <tr key={u.id}>
                  <td>
                    <div className="flex items-center gap-[11px] min-w-0">
                      <FormatChip size={30}>{u.fmt}</FormatChip>
                      <div className="min-w-0">
                        <div className="font-semibold truncate">{u.name}</div>
                        <div className="text-[12px] opacity-55">{u.meta}</div>
                      </div>
                    </div>
                  </td>
                  <td>
                    <span className={statusClass(u.status)}>{u.status}</span>
                  </td>
                  <td>
                    <div className="flex gap-2 justify-end flex-wrap">
                      {u.backendId ? (
                        <>
                          <Button asChild variant="ghost" size="xs" className="whitespace-nowrap">
                            <a href={`/viewer/${u.backendId}`} target="_blank" rel="noopener noreferrer">
                              View
                            </a>
                          </Button>
                          <Button
                            variant="secondary"
                            size="xs"
                            className="whitespace-nowrap"
                            disabled={verify?.rowId === u.id && verify.loading}
                            onClick={() => verifyBackend(u.id, u.backendId!)}
                          >
                            {verify?.rowId === u.id && verify.loading ? 'Checking…' : 'Verify'}
                          </Button>
                        </>
                      ) : null}
                      {/* Approval is local bookkeeping: the backend publishes a
                          template the moment it is uploaded and has no review
                          state to move it through. */}
                      <Button
                        variant="secondary"
                        size="xs"
                        className="whitespace-nowrap"
                        onClick={() => {
                          removeUpload(u.id)
                          fireToast(`Cleared ${u.name} from the queue`)
                        }}
                      >
                        Clear
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        </TableCard>
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
