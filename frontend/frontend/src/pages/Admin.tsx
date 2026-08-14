import { useCallback, useEffect, useState } from 'react'
import { useHub } from '@/store/HubProvider'
import {
  approveVersion,
  listApprovals,
  rejectVersion,
  type Approval,
  type ApprovalStatus,
} from '@/services/notifications'
import { AuthApiError } from '@/services/auth'
import { CHIP_BY_FORMAT, EmptyState, FormatChip, PageBody, PageHeading } from '@/components/common'
import { formatBytes } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/input'
import { Icon } from '@/components/ui/icon'
import { ApprovalCardSkeleton, SkeletonGroup } from '@/components/ui/skeleton'
import { Segmented } from '@/components/ui/segmented'

/* `all` leads and is the default: doc control opening this page wants to see
   the whole queue, and a filter that hides two thirds of it by default reads as
   an empty queue rather than a filtered one. It passes no `status_filter`, and
   the API defaults to every status. */
const TABS: { key: ApprovalStatus | 'all'; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'pending', label: 'Awaiting review' },
  { key: 'approved', label: 'Approved' },
  { key: 'rejected', label: 'Rejected' },
]

const STATUS_CLASS: Record<ApprovalStatus, string> = {
  pending: 'bg-accent2-100 text-accent2-900',
  approved: 'bg-accent-100 text-accent-700',
  rejected: 'bg-[color:var(--md-error)]/10 text-[color:var(--md-error)]',
}

const STATUS_LABEL: Record<ApprovalStatus, string> = {
  pending: 'Awaiting review',
  approved: 'Approved',
  rejected: 'Rejected',
}

/**
 * Doc control's review queue, read from `GET /admin/approvals`.
 *
 * This used to list templates uploaded *in this browser tab* and "approve"
 * them by flipping a label in memory — the server published everything on
 * upload regardless, so the button recorded a decision that changed nothing
 * and the list was empty after a reload.
 *
 * Approving now actually publishes: an unapproved version is absent from
 * `GET /templates` and from search, so until someone clicks here the template
 * genuinely is not in the library. Both decisions notify the submitter in the
 * hub and by email.
 */
export function Admin() {
  const { fireToast } = useHub()

  const [tab, setTab] = useState<ApprovalStatus | 'all'>('all')
  const [queue, setQueue] = useState<Approval[]>([])
  const [pending, setPending] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  /** The row currently being decided, so only its buttons show a busy state. */
  const [busyId, setBusyId] = useState<string | null>(null)
  /** Open when rejecting — the note is mandatory, so it needs a real prompt. */
  const [rejecting, setRejecting] = useState<Approval | null>(null)
  const [note, setNote] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const result = await listApprovals(tab === 'all' ? undefined : tab)
      setQueue(result.items)
      setPending(result.pending)
      setError(null)
    } catch (err) {
      setError(err instanceof AuthApiError ? err.message : 'Could not load the approval queue.')
    } finally {
      setLoading(false)
    }
  }, [tab])

  useEffect(() => {
    void load()
  }, [load])

  const approve = async (row: Approval) => {
    setBusyId(row.version_id)
    try {
      await approveVersion(row.version_id)
      fireToast(`Approved ${row.title} — published to the library`)
      await load()
    } catch (err) {
      setError(err instanceof AuthApiError ? err.message : 'Could not approve that version.')
    } finally {
      setBusyId(null)
    }
  }

  const confirmReject = async () => {
    if (!rejecting) return
    setBusyId(rejecting.version_id)
    try {
      await rejectVersion(rejecting.version_id, note.trim())
      fireToast(`Sent ${rejecting.title} back to ${rejecting.submitted_by_name ?? 'its submitter'}`)
      setRejecting(null)
      setNote('')
      await load()
    } catch (err) {
      setError(err instanceof AuthApiError ? err.message : 'Could not record that decision.')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <PageBody>
      <PageHeading
        title="Admin"
        subtitle="Doc control — every template version waiting on a decision."
      />

      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex-1 min-w-0">
          <h2 className="text-title-lg m-0">Approval queue</h2>
          <p className="text-body-md text-neutral-700 m-0">
            {pending === 0
              ? 'Nothing is waiting on you.'
              : `${pending} version${pending === 1 ? '' : 's'} awaiting review. Nothing here is in the library until it is approved.`}
          </p>
        </div>
        <Button variant="secondary" className="flex-none" onClick={() => void load()} disabled={loading}>
          <Icon name="refresh" size={18} />
          {loading ? 'Refreshing…' : 'Refresh'}
        </Button>
      </div>

      <Segmented
        name="approval-filter"
        value={tab}
        onChange={setTab}
        options={TABS.map((t) => ({ value: t.key, label: t.label }))}
      />

      {error ? (
        <p className="text-body-md text-[color:var(--md-error)] bg-[color:var(--md-error)]/10 border border-[color:var(--md-error)]/30 rounded-lg py-[10px] px-3 m-0">
          {error}
        </p>
      ) : null}

      {loading && !queue.length ? (
        /* Only when there is nothing to show yet. A refresh with rows already
           on screen keeps them and lets the Refresh button carry the busy
           state -- replacing a queue you are reading with placeholders is a
           worse answer than briefly showing slightly stale rows. */
        <SkeletonGroup
          label="Loading the approval queue"
          className="grid gap-4 grid-cols-[repeat(auto-fill,minmax(340px,1fr))]"
        >
          {Array.from({ length: 6 }).map((_, i) => (
            <ApprovalCardSkeleton key={i} />
          ))}
        </SkeletonGroup>
      ) : queue.length ? (
        <div className="grid gap-4 grid-cols-[repeat(auto-fill,minmax(340px,1fr))]">
          {queue.map((row) => (
            <article
              key={row.version_id}
              className="relative bg-surface border border-divider rounded-card p-5 flex flex-col gap-4 shadow-elev-sm"
            >
              <span
                className={`absolute top-4 right-4 uppercase text-[11px] font-semibold tracking-[.06em] rounded-tag py-[3px] px-[9px] ${STATUS_CLASS[row.approval_status]}`}
              >
                {STATUS_LABEL[row.approval_status]}
              </span>

              <FormatChip size={40}>{CHIP_BY_FORMAT[row.format]}</FormatChip>

              <div className="min-w-0">
                <h3 className="text-title-lg m-0 mb-1 truncate pr-28">{row.title}</h3>
                <p className="text-body-md text-neutral-700 m-0 truncate">
                  {row.original_filename} · v{row.version_number} · {formatBytes(row.size_bytes)}
                </p>
              </div>

              {row.purpose ? (
                <p className="text-body-md text-neutral-700 m-0 line-clamp-3">{row.purpose}</p>
              ) : (
                /* Null until the enrichment pass finishes — pending, not
                   missing. Saying so stops a reviewer reading a blank as a
                   broken upload. */
                <p className="text-body-md text-neutral-600 italic m-0">
                  Description still being generated…
                </p>
              )}

              <div className="grid grid-cols-2 gap-3 text-label-md border-t border-divider pt-4">
                <div className="min-w-0">
                  <div className="uppercase text-neutral-600 mb-1">Submitted by</div>
                  <div className="text-body-md text-ink truncate">
                    {row.submitted_by_name ?? 'Unknown'}
                  </div>
                </div>
                <div className="min-w-0">
                  <div className="uppercase text-neutral-600 mb-1">Submitted</div>
                  <div className="text-body-md text-ink truncate">
                    {new Date(row.submitted_at).toLocaleString()}
                  </div>
                </div>
              </div>

              {row.review_note ? (
                <div className="text-label-md border-t border-divider pt-3">
                  <div className="uppercase text-neutral-600 mb-1">
                    Note from {row.reviewed_by_name ?? 'the reviewer'}
                  </div>
                  <p className="text-body-md text-ink m-0">{row.review_note}</p>
                </div>
              ) : null}

              <div className="flex gap-2 flex-wrap mt-auto pt-1">
                <Button asChild variant="secondary" size="sm">
                  <a href={`/viewer/${row.template_id}`} target="_blank" rel="noopener noreferrer">
                    <Icon name="visibility" size={16} />
                    Open
                  </a>
                </Button>

                {row.approval_status === 'pending' ? (
                  <>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="ml-auto"
                      disabled={busyId === row.version_id}
                      onClick={() => {
                        setRejecting(row)
                        setNote('')
                      }}
                    >
                      Request changes
                    </Button>
                    <Button
                      variant="primary"
                      size="sm"
                      disabled={busyId === row.version_id}
                      onClick={() => void approve(row)}
                    >
                      <Icon name="check" size={16} />
                      {busyId === row.version_id ? 'Working…' : 'Approve'}
                    </Button>
                  </>
                ) : (
                  <span className="ml-auto self-center text-label-md text-neutral-600">
                    {row.reviewed_at
                      ? `Reviewed ${new Date(row.reviewed_at).toLocaleDateString()}`
                      : 'Reviewed'}
                  </span>
                )}
              </div>
            </article>
          ))}
        </div>
      ) : (
        /* No upload action here. This page is about deciding on other people's
           submissions, and the queue being empty is the good outcome rather
           than a prompt to add something -- uploading lives in the library.

           No `loading` case either: an empty queue mid-load renders the
           skeleton branch above, so reaching here means the load finished. */
        <EmptyState
          title={tab === 'pending' ? 'Nothing awaiting review' : 'Nothing here'}
          body={
            tab === 'pending'
              ? 'When someone submits a template it lands here, and you are notified in the hub and by email.'
              : tab === 'all'
                ? 'No template versions have been submitted yet.'
                : 'No versions in this state yet.'
          }
        />
      )}

      <Dialog
        open={rejecting !== null}
        onOpenChange={(open) => {
          if (!open) {
            setRejecting(null)
            setNote('')
          }
        }}
        title="Request changes"
        actions={
          <>
            <Button
              variant="secondary"
              onClick={() => {
                setRejecting(null)
                setNote('')
              }}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              disabled={note.trim().length < 3 || busyId !== null}
              onClick={() => void confirmReject()}
            >
              Send back
            </Button>
          </>
        }
      >
        <div className="dialog-body">
          <p className="m-0 mb-3 text-body-md">
            {rejecting?.submitted_by_name ?? 'The submitter'} gets this note in the hub and by email.
            It is the only thing telling them what to fix, so a reason is required.
          </p>
          <Textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={4}
            placeholder="e.g. The revision block still says Ver. 1 — update it and re-upload."
            autoFocus
          />
        </div>
      </Dialog>
    </PageBody>
  )
}
