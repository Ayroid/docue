import { useCallback, useEffect, useRef, useState } from 'react'
import {
  listNotifications,
  markAllNotificationsRead,
  markNotificationRead,
  type AppNotification,
} from '@/services/notifications'
import { useAuth } from '@/store/AuthProvider'

/** How often the bell re-checks. Thirty seconds because approvals are a
    human-speed workflow — a reviewer clicking approve and the submitter seeing
    it within half a minute is indistinguishable from instant, and it is cheap
    enough to leave running on every page. A socket would be the right answer
    for anything faster, and the backend has none. */
const POLL_INTERVAL_MS = 30_000

export interface NotificationsState {
  items: AppNotification[]
  unread: number
  loading: boolean
  error: string | null
  markRead: (id: string) => Promise<void>
  markAllRead: () => Promise<void>
  reload: () => void
}

/**
 * The bell's data: the user's notifications, polled while they are signed in.
 *
 * Polling stops when signed out — an interval firing 401s against a cleared
 * token is noise in the console and load on the server for nothing.
 */
export function useNotifications(): NotificationsState {
  const { signedIn } = useAuth()
  const [items, setItems] = useState<AppNotification[]>([])
  const [unread, setUnread] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  /* Guards every state write against a response that lands after sign-out or
     unmount — React warns on the former and the latter would resurrect a
     signed-out user's notifications. */
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  const load = useCallback(async () => {
    if (!signedIn) {
      setItems([])
      setUnread(0)
      return
    }
    setLoading(true)
    try {
      const result = await listNotifications()
      if (!alive.current) return
      setItems(result.items)
      setUnread(result.unread)
      setError(null)
    } catch (err) {
      if (!alive.current) return
      /* Kept quiet in the UI: a failed poll on background chrome should not
         put an error banner over whatever the user is actually doing. */
      setError(err instanceof Error ? err.message : 'Could not load notifications.')
    } finally {
      if (alive.current) setLoading(false)
    }
  }, [signedIn])

  useEffect(() => {
    if (!signedIn) {
      setItems([])
      setUnread(0)
      return
    }
    void load()
    const timer = setInterval(() => void load(), POLL_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [signedIn, load])

  const markRead = useCallback(async (id: string) => {
    /* Optimistic: the panel is open and the row was just clicked, so waiting a
       round trip to grey it out reads as an unresponsive button. A failure is
       corrected by the next poll. */
    setItems((prev) =>
      prev.map((item) =>
        item.id === id && item.read_at === null ? { ...item, read_at: new Date().toISOString() } : item,
      ),
    )
    setUnread((prev) => Math.max(0, prev - 1))
    try {
      await markNotificationRead(id)
    } catch {
      void load()
    }
  }, [load])

  const markAllRead = useCallback(async () => {
    const stamp = new Date().toISOString()
    setItems((prev) => prev.map((item) => (item.read_at ? item : { ...item, read_at: stamp })))
    setUnread(0)
    try {
      await markAllNotificationsRead()
    } catch {
      void load()
    }
  }, [load])

  return { items, unread, loading, error, markRead, markAllRead, reload: () => void load() }
}
