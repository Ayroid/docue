import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useHub } from '@/store/HubProvider'
import {
  approvePromotion,
  listPromotions,
  rejectPromotion,
  PromotionApiError,
  type Promotion,
} from '@/services/promotions'
import { Button } from '@/components/ui/button'
import { Tag } from '@/components/ui/tag'
import { Panel, SectionLabel } from '@/components/ui/table'

/**
 * Doc control's approval queue: versions people want to become templates.
 *
 * Unlike the uploads list above it on the Admin page, this is server state —
 * it survives a reload, because a request that vanished when someone closed a
 * tab would be a request nobody ever decides.
 *
 * Approving re-ingests the file through the same path an upload takes, so the
 * template's regions, metadata and embedding all follow the new bytes. That
 * takes 15-40s, which is why the row reports "re-indexing" rather than
 * pretending the change is instant.
 */
export function PromotionQueue() {
  const { userId, role, fireToast } = useHub()
  const navigate = useNavigate()
  const [pending, setPending] = useState<Promotion[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [notes, setNotes] = useState<Record<string, string>>({})

  const refresh = useCallback(() => {
    setLoading(true)
    listPromotions('pending', userId)
      .then((rows) => {
        setPending(rows)
        setError(null)
      })
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : 'Could not load the queue.'),
      )
      .finally(() => setLoading(false))
  }, [userId])

  useEffect(refresh, [refresh])

  const decide = async (promotion: Promotion, approve: boolean) => {
    setBusy(promotion.id)
    setError(null)
    const note = notes[promotion.id]?.trim() || null
    try {
      const decided = approve
        ? await approvePromotion(promotion.id, note, userId)
        : await rejectPromotion(promotion.id, note, userId)
      fireToast(
        decided.status === 'approved'
          ? `Published v${decided.version_number} — re-indexing now`
          : 'Request rejected',
      )
      setPending((rows) => rows.filter((r) => r.id !== promotion.id))
    } catch (err) {
      setError(
        err instanceof PromotionApiError && err.status === 403
          ? 'Only doc control can decide a request.'
          : err instanceof Error
            ? err.message
            : 'The decision failed.',
      )
    } finally {
      setBusy(null)
    }
  }

  // Not an admin: this queue is not theirs to see. The endpoint enforces the
  // same thing, so this is presentation, not protection.
  if (role !== 'Admin') return null

  return (
    <Panel className="mt-6">
      <div className="flex items-center gap-3 flex-wrap">
        <SectionLabel className="mb-0">Version approvals</SectionLabel>
        {pending.length ? (
          <Tag variant="accent2" className="whitespace-nowrap flex-none">
            {pending.length} waiting
          </Tag>
        ) : null}
      </div>

      {error ? <p className="text-[12.5px] opacity-75 mt-[10px]">{error}</p> : null}

      {loading ? (
        <p className="text-[12.5px] opacity-55 mt-[10px]">Loading…</p>
      ) : !pending.length ? (
        <p className="text-[12.5px] opacity-55 mt-[10px]">
          Nothing waiting. Versions submitted from the review screen appear here.
        </p>
      ) : (
        <div className="flex flex-col gap-[14px] mt-[14px]">
          {pending.map((p) => (
            <div key={p.id} className="bg-bg rounded-card p-[14px] flex flex-col gap-[10px]">
              <div className="flex items-start gap-3 flex-wrap">
                <div className="flex-[1_1_220px] min-w-[180px]">
                  <button
                    type="button"
                    className="font-semibold text-[13.5px] text-left underline-offset-2 hover:underline"
                    onClick={() => navigate(`/templates/${p.template_id}`)}
                  >
                    {p.template_title ?? 'Template'} · v{p.version_number}
                  </button>
                  <div className="text-[12px] opacity-60 mt-[2px]">
                    {p.requested_by ?? 'someone'} asked to publish this
                    {' · '}
                    {new Date(p.created_at).toLocaleString()}
                  </div>
                </div>
                <Tag variant="neutral" className="whitespace-nowrap flex-none">
                  {p.requested_role}
                </Tag>
              </div>

              {p.note ? <p className="text-[12.5px] opacity-75">“{p.note}”</p> : null}

              <textarea
                className="w-full bg-surface rounded-[8px] p-[10px] text-[12.5px] resize-y min-h-[54px]"
                placeholder="Reason — sent to whoever asked. On a rejection it is the only explanation they get."
                value={notes[p.id] ?? ''}
                onChange={(e) => setNotes((n) => ({ ...n, [p.id]: e.target.value }))}
                disabled={busy === p.id}
              />

              <div className="flex gap-[10px] flex-wrap">
                <Button
                  variant="primary"
                  size="sm"
                  className="whitespace-nowrap"
                  disabled={busy === p.id}
                  onClick={() => void decide(p, true)}
                >
                  {busy === p.id ? 'Working…' : 'Approve & publish'}
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  className="whitespace-nowrap"
                  disabled={busy === p.id}
                  onClick={() => void decide(p, false)}
                >
                  Reject
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </Panel>
  )
}
