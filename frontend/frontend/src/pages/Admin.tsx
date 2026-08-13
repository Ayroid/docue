import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ACCESS_GROUPS, QUEUE, SUBMISSIONS, SUB_FILTERS, statusClass } from '@/data/mock'
import { useHub } from '@/store/HubProvider'
import { getTemplate, TemplateApiError, type TemplateOut } from '@/services/templates'
import { formatBytes } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { FilterTag } from '@/components/ui/tag'
import { Table, TableCard, Panel, SectionLabel } from '@/components/ui/table'
import { Dialog } from '@/components/ui/dialog'
import { EmptyState, FormatChip, PageBody, PageHeading } from '@/components/common'
import { CheckIcon } from '@/components/icons'

interface VerifyState {
  rowId: number
  loading: boolean
  result: TemplateOut | null
  error: string | null
}

export function Admin() {
  const { uploads, publishUpload, fireToast } = useHub()
  const navigate = useNavigate()
  const [filter, setFilter] = useState('All')
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

  /* Live uploads from this session lead the queue; the mock submission
     history fills it out so the page never looks empty on first load. */
  const combined = useMemo(
    () => [
      ...uploads.map((u) => ({ ...u, live: true as const })),
      ...SUBMISSIONS.map((s) => ({ ...s, live: false as const })),
    ],
    [uploads],
  )
  const filtered = combined.filter((s) => filter === 'All' || s.kind === filter)

  const pendingCount = uploads.length + QUEUE.filter((q) => q.kind === 'In process').length
  const publishedToday = QUEUE.filter((q) => q.status === 'Published').length

  return (
    <PageBody>
      <PageHeading title="Admin" subtitle="Doc control — approve incoming templates and manage access." />

      <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-4 mb-7">
        {[
          { label: 'Pending review', value: String(pendingCount) },
          { label: 'Parsed this week', value: String(QUEUE.length) },
          { label: 'Published today', value: String(publishedToday) },
          { label: 'Access groups', value: String(ACCESS_GROUPS.length) },
        ].map((s) => (
          <Panel key={s.label}>
            <div className="font-heading text-[26px] mb-1">{s.value}</div>
            <div className="text-[12.5px] opacity-60">{s.label}</div>
          </Panel>
        ))}
      </div>

      <div className="hub-results grid grid-cols-[minmax(0,1fr)_340px] gap-6 items-start">
        <div className="flex flex-col gap-5 min-w-0">
          <div>
            <div className="flex items-center gap-4 flex-wrap mb-[14px]">
              <h4 className="m-0">Submissions</h4>
              <div className="flex gap-[9px] flex-wrap ml-auto">
                {SUB_FILTERS.map((f) => (
                  <FilterTag key={f} selected={filter === f} onClick={() => setFilter(f)}>
                    {f}
                  </FilterTag>
                ))}
              </div>
            </div>

            {filtered.length ? (
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
                    {filtered.map((s) => (
                      <tr key={`${s.live ? 'live' : 'mock'}-${s.id}`}>
                        <td>
                          <div className="flex items-center gap-[11px] min-w-0">
                            <FormatChip size={30}>{s.fmt}</FormatChip>
                            <div className="min-w-0">
                              <div className="font-semibold truncate">{s.name}</div>
                              <div className="text-[12px] opacity-55">{s.meta}</div>
                              <div className="text-[12px] opacity-55">{s.note}</div>
                            </div>
                          </div>
                        </td>
                        <td>
                          <span className={statusClass(s.status)}>{s.status}</span>
                        </td>
                        <td>
                          <div className="flex gap-2 justify-end flex-wrap">
                            {s.live && s.backendId ? (
                              <Button
                                variant="secondary"
                                size="xs"
                                className="whitespace-nowrap"
                                disabled={verify?.rowId === s.id && verify.loading}
                                onClick={() => verifyBackend(s.id, s.backendId!)}
                              >
                                {verify?.rowId === s.id && verify.loading ? 'Checking…' : 'Verify'}
                              </Button>
                            ) : null}
                            {s.live && s.status !== 'Approved' ? (
                              <>
                                <Button
                                  variant="primary"
                                  size="xs"
                                  className="whitespace-nowrap"
                                  onClick={() => publishUpload(s.id, s.name, s.fmt)}
                                >
                                  Approve
                                </Button>
                                <Button
                                  variant="secondary"
                                  size="xs"
                                  className="whitespace-nowrap"
                                  onClick={() => fireToast(`Sent ${s.name} back for changes`)}
                                >
                                  Send back
                                </Button>
                              </>
                            ) : null}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </TableCard>
            ) : (
              <EmptyState size="md" title="Nothing here" body="No submissions currently match this filter." />
            )}
          </div>

          <div>
            <h4 className="mb-[14px]">Ingestion pipeline</h4>
            <div className="flex flex-col gap-3">
              {QUEUE.map((q) => (
                <div key={q.id} className="bg-surface rounded-card py-4 px-[18px] flex items-center gap-4 flex-wrap">
                  <FormatChip size={34}>{q.fmt}</FormatChip>
                  <div className="flex-[1_1_200px] min-w-[170px]">
                    <div className="font-semibold">{q.name}</div>
                    <div className="text-[12px] opacity-55">{q.note}</div>
                  </div>
                  <span className={`${statusClass(q.status)} ml-auto flex-none`}>{q.status}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="flex flex-col gap-4 min-w-0">
          <Panel>
            <SectionLabel>Access groups</SectionLabel>
            <Table>
              <thead>
                <tr>
                  <th>Group</th>
                  <th>View</th>
                  <th>Gen</th>
                  <th>Admin</th>
                </tr>
              </thead>
              <tbody>
                {ACCESS_GROUPS.map((g) => (
                  <tr key={g.name}>
                    <td>
                      <div className="font-semibold text-[13px]">{g.name}</div>
                      <div className="text-[11px] opacity-55">{g.members} members</div>
                    </td>
                    {[g.view, g.gen, g.admin].map((on, i) => (
                      <td key={i}>{on ? <CheckIcon width={14} height={14} className="text-accent" /> : null}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </Table>
          </Panel>

          <Button variant="secondary" block className="mt-0 whitespace-nowrap" onClick={() => navigate('/upload')}>
            Upload template
          </Button>
        </div>
      </div>

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
