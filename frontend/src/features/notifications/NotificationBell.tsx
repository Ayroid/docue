import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useNotifications } from '@/features/notifications/useNotifications'
import type { AppNotification } from '@/services/notifications'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/ui/icon'

/** Which icon each kind gets. Approval requests are a task, the other two are
    outcomes, and they should not look alike in a mixed list. */
const ICON_BY_KIND: Record<AppNotification['kind'], string> = {
  approval_requested: 'pending_actions',
  template_approved: 'check_circle',
  template_rejected: 'error',
}

const TONE_BY_KIND: Record<AppNotification['kind'], string> = {
  approval_requested: 'bg-accent2-100 text-accent2-900',
  template_approved: 'bg-accent-100 text-accent-700',
  template_rejected: 'bg-[color:var(--md-error)]/10 text-[color:var(--md-error)]',
}

/** Relative time, to the resolution that actually matters here.
 *
 *  Approvals are a hours-and-days workflow, so "3 days ago" is the useful
 *  granularity and an exact timestamp is noise. Falls back to a date past a
 *  week, where "9 days ago" stops being easier to read than the date. */
function relativeTime(iso: string): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const seconds = Math.floor((Date.now() - then) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days}d ago`
  return new Date(iso).toLocaleDateString()
}

/**
 * The header bell: an unread count and a panel of recent notifications.
 *
 * Clicking a row marks it read and, when it points at a template, navigates
 * there — an approval notification whose only affordance is "acknowledged"
 * makes the reader go and find the template by hand.
 */
export function NotificationBell() {
  const navigate = useNavigate()
  const { items, unread, loading, markRead, markAllRead, reload } = useNotifications()
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)

  /* Close on an outside click or Escape. Without both, the panel stays open
     behind whatever the user clicks next and covers the page. */
  useEffect(() => {
    if (!open) return

    const onPointerDown = (event: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(event.target as Node)) setOpen(false)
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }

    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  const openPanel = () => {
    setOpen((wasOpen) => {
      /* Refresh on open rather than on close, so the list is current at the
         moment it becomes visible instead of up to 30s stale. */
      if (!wasOpen) reload()
      return !wasOpen
    })
  }

  const activate = async (item: AppNotification) => {
    await markRead(item.id)
    if (item.template_id) {
      setOpen(false)
      navigate(`/templates/${item.template_id}`)
    }
  }

  return (
    <div className="relative" ref={wrapRef}>
      <Button
        variant="bare"
        size="icon"
        className="hover:bg-neutral-200 text-neutral-700 relative"
        title={unread ? `${unread} unread notification${unread === 1 ? '' : 's'}` : 'Notifications'}
        aria-label={unread ? `Notifications, ${unread} unread` : 'Notifications'}
        aria-expanded={open}
        onClick={openPanel}
      >
        <Icon name="notifications" size={22} />
        {unread > 0 ? (
          <span className="absolute top-[6px] right-[6px] min-w-[16px] h-4 px-[4px] rounded-pill bg-[color:var(--md-error)] text-white text-[10px] leading-4 font-bold text-center">
            {unread > 9 ? '9+' : unread}
          </span>
        ) : null}
      </Button>

      {open ? (
        <div className="elev-lg absolute top-[52px] right-0 w-[340px] max-w-[calc(100vw-32px)] bg-surface border border-divider rounded-lg z-30 overflow-hidden">
          <div className="flex items-center justify-between gap-2 px-4 py-3 border-b border-divider">
            <span className="text-title-lg">Notifications</span>
            {unread > 0 ? (
              <Button variant="ghost" size="xs" onClick={() => void markAllRead()}>
                Mark all read
              </Button>
            ) : null}
          </div>

          <div className="max-h-[380px] overflow-auto">
            {items.length === 0 ? (
              <p className="text-body-md text-neutral-700 m-0 px-4 py-8 text-center">
                {loading ? 'Loading…' : 'Nothing yet.'}
              </p>
            ) : (
              items.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => void activate(item)}
                  className={`w-full text-left flex gap-3 px-4 py-3 border-b border-divider last:border-b-0 bg-transparent border-x-0 border-t-0 cursor-pointer font-[inherit] hover:bg-neutral-200/60 transition-colors ${
                    item.read_at ? 'opacity-60' : ''
                  }`}
                >
                  <div
                    className={`flex-none w-8 h-8 rounded-md grid place-items-center ${TONE_BY_KIND[item.kind]}`}
                  >
                    <Icon name={ICON_BY_KIND[item.kind]} size={18} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-body-md font-semibold text-ink truncate">{item.title}</div>
                    <div className="text-label-md text-neutral-700 line-clamp-2">{item.body}</div>
                    <div className="text-label-md text-neutral-600 mt-1">{relativeTime(item.created_at)}</div>
                  </div>
                  {item.read_at ? null : (
                    <span className="flex-none w-2 h-2 rounded-pill bg-accent mt-2" aria-hidden />
                  )}
                </button>
              ))
            )}
          </div>
        </div>
      ) : null}
    </div>
  )
}
