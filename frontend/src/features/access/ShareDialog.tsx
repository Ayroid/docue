import { useCallback, useEffect, useState } from 'react'
import {
  getTemplateAccess,
  grantTemplateAccess,
  revokeTemplateAccess,
  setTemplateVisibility,
  type TemplateAccess,
  type Visibility,
} from '@/services/access'
import { TemplateApiError } from '@/services/templates'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { Icon } from '@/components/ui/icon'
import { Input } from '@/components/ui/input'
import { Segmented } from '@/components/ui/segmented'
import { Tag } from '@/components/ui/tag'

const VISIBILITY_OPTIONS = [
  { value: 'public' as const, label: 'Everyone' },
  { value: 'restricted' as const, label: 'Only chosen people' },
]

/**
 * Manage who can see one template. Admin-only, mounted from the template card.
 *
 * **The list is never patched locally.** Every one of the four calls returns the
 * whole access state, and this component replaces its copy with the response —
 * so a refused grant ("no account is registered to that address") leaves the
 * list showing exactly what the server has, rather than a row that only exists
 * in the browser.
 *
 * **Visibility is a radio, not a checkbox on the grant list.** "Shared with
 * nobody yet" and "open to everyone" are opposite intentions and the backend
 * keeps them apart deliberately; a single toggle that flipped to public when the
 * last person was removed would silently publish the document.
 */
export function ShareDialog({
  templateId,
  templateTitle,
  open,
  onOpenChange,
}: {
  templateId: string
  templateTitle: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [access, setAccess] = useState<TemplateAccess | null>(null)
  const [email, setEmail] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  /* Wraps every mutation: they all return the full state and all report
     failure the same way, so the one place that knows about `busy` and `error`
     is here rather than in four near-identical handlers. */
  const run = useCallback(async (action: () => Promise<TemplateAccess>, success?: string) => {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      setAccess(await action())
      if (success) setNotice(success)
      return true
    } catch (err) {
      setError(err instanceof TemplateApiError ? err.message : 'Something went wrong.')
      return false
    } finally {
      setBusy(false)
    }
  }, [])

  useEffect(() => {
    if (!open) return
    /* Reset rather than keep the previous template's list on screen while the
       new one loads — a share dialog showing the wrong people, however briefly,
       is the one mistake this component must not make. */
    setAccess(null)
    setEmail('')
    setError(null)
    setNotice(null)
    void run(() => getTemplateAccess(templateId))
  }, [open, templateId, run])

  const restricted = access?.visibility === 'restricted'

  const submitEmail = async () => {
    const trimmed = email.trim()
    if (!trimmed) return
    const ok = await run(
      () => grantTemplateAccess(templateId, trimmed),
      `${trimmed} can now open this template.`,
    )
    if (ok) setEmail('')
  }

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={`Share "${templateTitle}"`}
      className="w-[min(560px,92vw)]"
      actions={
        <Button variant="secondary" size="sm" onClick={() => onOpenChange(false)}>
          Done
        </Button>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <span className="text-label-md text-neutral-700">Who can find and use this</span>
          <Segmented
            name={`visibility-${templateId}`}
            value={(access?.visibility ?? 'public') as Visibility}
            options={VISIBILITY_OPTIONS}
            onChange={(next) =>
              void run(
                () => setTemplateVisibility(templateId, next),
                next === 'restricted'
                  ? 'Only the people below, the owner and admins can see this now.'
                  : 'Anyone signed in can see this again.',
              )
            }
          />
          {/* Said out loud because the grant rows stay visible either way: they
              are kept through a public/restricted round trip so the list does
              not have to be rebuilt, which would otherwise read as "these
              people have access" when they do not. */}
          {!restricted && access ? (
            <p className="text-label-md text-neutral-600 m-0">
              This template is open to everyone signed in. Any names below are kept for later and
              grant nothing right now.
            </p>
          ) : null}
        </div>

        <div className="flex flex-col gap-2">
          <span className="text-label-md text-neutral-700">Add someone by registered email</span>
          <div className="flex items-center gap-2">
            <Input
              type="email"
              value={email}
              placeholder="colleague@yamaha-motor-india.com"
              disabled={busy}
              onChange={(e) => setEmail(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  void submitEmail()
                }
              }}
            />
            <Button
              variant="primary"
              size="sm"
              className="flex-none"
              disabled={busy || !email.trim()}
              onClick={() => void submitEmail()}
            >
              <Icon name="add" size={16} />
              Share
            </Button>
          </div>
          <p className="text-label-md text-neutral-600 m-0">
            They must already have a Template Hub account — nothing here sends an invitation.
          </p>
        </div>

        {error ? <p className="text-label-md text-danger m-0">{error}</p> : null}
        {notice && !error ? <p className="text-label-md text-neutral-700 m-0">{notice}</p> : null}

        <div className="flex flex-col gap-1">
          <span className="text-label-md text-neutral-700">
            People with access{access ? ` (${access.grants.length})` : ''}
          </span>
          {access?.owner_email ? (
            <div className="flex items-center justify-between gap-3 border-b border-divider py-2">
              <span className="min-w-0 truncate">{access.owner_email}</span>
              <Tag variant="outline" className="flex-none text-[11px]">
                Owner
              </Tag>
            </div>
          ) : null}
          {access === null ? (
            <p className="text-label-md text-neutral-500 m-0 py-2">Loading…</p>
          ) : access.grants.length === 0 ? (
            <p className="text-label-md text-neutral-500 m-0 py-2">
              Nobody has been added yet.
            </p>
          ) : (
            access.grants.map((grant) => (
              <div
                key={grant.user_id}
                className="flex items-center justify-between gap-3 border-b border-divider py-2"
              >
                <span className="min-w-0 flex-1 truncate" title={grant.email}>
                  {grant.full_name ? `${grant.full_name} — ${grant.email}` : grant.email}
                </span>
                {/* Both are real states an admin needs to see: a grant to an
                    unverified account cannot be used yet, and an expired one
                    stopped working without anyone touching it. */}
                {grant.user_status !== 'active' ? (
                  <Tag variant="outline" className="flex-none text-[11px]" title="This account has not verified its email address yet.">
                    Unverified
                  </Tag>
                ) : null}
                {grant.expired ? (
                  <Tag variant="outline" className="flex-none text-[11px]">
                    Expired
                  </Tag>
                ) : null}
                <Button
                  variant="bare"
                  size="icon"
                  className="w-8 h-8 flex-none text-neutral-600 hover:bg-neutral-200"
                  title={`Remove ${grant.email}`}
                  aria-label={`Remove ${grant.email}`}
                  disabled={busy}
                  onClick={() =>
                    void run(
                      () => revokeTemplateAccess(templateId, grant.user_id),
                      `${grant.email} can no longer open this template.`,
                    )
                  }
                >
                  <Icon name="close" size={16} />
                </Button>
              </div>
            ))
          )}
        </div>
      </div>
    </Dialog>
  )
}
