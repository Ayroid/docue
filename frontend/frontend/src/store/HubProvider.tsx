import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react'
import type { Fmt } from '@/data/catalog'

export type Role = 'Admin' | 'Member'
export type Tier = 'T1' | 'T2' | 'T3'

/* ── Generation walkthrough state ────────────────────────────────────────
   Everything in this block belongs to the scripted Generate → Review →
   Document demo. It starts empty and only fills as someone walks through it,
   so nothing invented is on screen until they do. There is no generation
   service, so none of it is persisted or sent anywhere. */

export interface Draft {
  id: string
  title: string
  templateId: string
  fmt: Fmt
  answers: string[]
  saved: string
}

/** A document produced by the walkthrough. Exists in this tab only. */
export interface DemoDoc {
  id: string
  name: string
  template: string
  version: string
  fmt: Fmt
  ext: string
  size: string
  created: string
  status: string
  kind: string
  templateId?: string
}

export interface Session {
  id: string
  templateId: string
  tier: Tier
  answers: string[]
  qIndex: number
  documentId?: string
  draftId?: string
}

export interface Upload {
  id: number
  name: string
  fmt: Fmt
  meta: string
  note: string
  status: string
  kind: string
  /** The real backend template id — every row here came from a real `POST /templates`. */
  backendId?: string
}

/**
 * Session state that isn't owned by the server yet: who's signed in, the
 * sidebar, the toast, and the templates uploaded during this visit.
 *
 * It deliberately holds no template or document *content*. Those come from the
 * backend through `services/templates.ts`; this provider used to seed the app
 * with invented ones and no longer does.
 */
interface HubState {
  loggedIn: boolean
  login: () => void
  logout: () => void
  role: Role
  sidebarOpen: boolean
  toggleSidebar: () => void

  /** Templates uploaded in this session — cleared on reload, since the server
      has no per-user submission history yet. */
  uploads: Upload[]
  lastUpload: { name: string; fmt: Fmt; meta: string } | null
  addUpload: (name: string, fmt: Fmt, meta: string, backendId?: string) => void
  removeUpload: (id: number) => void
  approveUpload: (id: number) => void

  /** Walkthrough state — see the note above `Draft`. */
  documents: DemoDoc[]
  drafts: Draft[]
  sessions: Record<string, Session>
  startSession: (templateId: string, seed?: Partial<Session>) => Session
  updateSession: (id: string, patch: Partial<Session>) => void
  getSession: (id: string) => Session | undefined
  saveDraft: (sessionId: string, templateName: string, fmt: Fmt) => void
  commitSession: (sessionId: string, templateName: string, version: string, fmt: Fmt) => string

  toast: string | null
  fireToast: (message: string) => void
  uploadDialogOpen: boolean
  closeUploadDialog: () => void
}

const HubContext = createContext<HubState | null>(null)

let sessionSeq = 0

export function HubProvider({ children }: { children: ReactNode }) {
  const [loggedIn, setLoggedIn] = useState(false)
  const [role] = useState<Role>('Admin')
  const [sidebarOpen, setSidebarOpen] = useState(true)

  const [uploads, setUploads] = useState<Upload[]>([])
  const [documents, setDocuments] = useState<DemoDoc[]>([])
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [sessions, setSessions] = useState<Record<string, Session>>({})
  const [lastUpload, setLastUpload] = useState<{ name: string; fmt: Fmt; meta: string } | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false)
  const toastTimer = useRef<ReturnType<typeof setTimeout>>()

  const fireToast = useCallback((message: string) => {
    setToast(message)
    clearTimeout(toastTimer.current)
    toastTimer.current = setTimeout(() => setToast(null), 2600)
  }, [])

  const addUpload = useCallback((name: string, fmt: Fmt, meta: string, backendId?: string) => {
    setUploads((prev) => [
      {
        id: 2000 + prev.length,
        name,
        fmt,
        meta,
        note: 'Waiting on doc control approval',
        status: 'Awaiting review',
        kind: 'In process',
        backendId,
      },
      ...prev,
    ])
    setLastUpload({ name, fmt, meta })
    setUploadDialogOpen(true)
  }, [])

  const removeUpload = useCallback((id: number) => {
    setUploads((prev) => prev.filter((u) => u.id !== id))
  }, [])

  /* Marks the submission approved in this session's queue. Publication itself
     is not gated by this: the server stores a template as `active` the moment
     it is uploaded and `GET /templates` returns it, so the file is already in
     the library. Gating would need a review state on the API. */
  const approveUpload = useCallback((id: number) => {
    setUploads((prev) =>
      prev.map((u) =>
        u.id === id ? { ...u, status: 'Approved', kind: 'Approved', note: 'Published to the library' } : u,
      ),
    )
  }, [])

  /* ── Generation walkthrough ─────────────────────────────────────────── */

  const startSession = useCallback((templateId: string, seed: Partial<Session> = {}) => {
    sessionSeq += 1
    const session: Session = { id: `s${sessionSeq}`, templateId, tier: 'T2', answers: [], qIndex: 0, ...seed }
    setSessions((prev) => ({ ...prev, [session.id]: session }))
    return session
  }, [])

  const updateSession = useCallback((id: string, patch: Partial<Session>) => {
    setSessions((prev) => (prev[id] ? { ...prev, [id]: { ...prev[id], ...patch } } : prev))
  }, [])

  const getSession = useCallback((id: string) => sessions[id], [sessions])

  const saveDraft = useCallback(
    (sessionId: string, templateName: string, fmt: Fmt) => {
      const session = sessions[sessionId]
      if (!session) return

      const entry: Draft = {
        id: session.draftId ?? `d${sessionId}`,
        title: session.answers[0] || `${templateName} — draft`,
        templateId: session.templateId,
        fmt,
        answers: [...session.answers],
        saved: 'Saved just now',
      }
      setDrafts((prev) => [entry, ...prev.filter((d) => d.id !== entry.id)])
      updateSession(sessionId, { draftId: entry.id })
      fireToast('Draft saved')
    },
    [sessions, updateSession, fireToast],
  )

  const commitSession = useCallback(
    (sessionId: string, templateName: string, version: string, fmt: Fmt) => {
      const session = sessions[sessionId]
      const docId = `g${sessionId}`
      const ext = fmt === 'XLS' ? '.xlsx' : fmt === 'PPT' ? '.pptx' : '.docx'

      setDocuments((prev) =>
        prev.some((d) => d.id === docId)
          ? prev
          : [
              {
                id: docId,
                name: session?.answers[0] || `${templateName} — new`,
                template: templateName,
                version,
                fmt,
                ext,
                size: '—',
                created: 'just now',
                status: 'Draft',
                kind: fmt === 'XLS' ? 'Excel' : fmt === 'PPT' ? 'PowerPoint' : 'Word',
                templateId: session?.templateId,
              },
              ...prev,
            ],
      )
      updateSession(sessionId, { documentId: docId })
      return docId
    },
    [sessions, updateSession],
  )

  const value = useMemo<HubState>(
    () => ({
      loggedIn,
      login: () => setLoggedIn(true),
      logout: () => setLoggedIn(false),
      role,
      sidebarOpen,
      toggleSidebar: () => setSidebarOpen((v) => !v),
      uploads,
      lastUpload,
      addUpload,
      removeUpload,
      approveUpload,
      documents,
      drafts,
      sessions,
      startSession,
      updateSession,
      getSession,
      saveDraft,
      commitSession,
      toast,
      fireToast,
      uploadDialogOpen,
      closeUploadDialog: () => setUploadDialogOpen(false),
    }),
    [
      loggedIn,
      role,
      sidebarOpen,
      uploads,
      lastUpload,
      addUpload,
      removeUpload,
      approveUpload,
      documents,
      drafts,
      sessions,
      startSession,
      updateSession,
      getSession,
      saveDraft,
      commitSession,
      toast,
      fireToast,
      uploadDialogOpen,
    ],
  )

  return <HubContext.Provider value={value}>{children}</HubContext.Provider>
}

export function useHub() {
  const ctx = useContext(HubContext)
  if (!ctx) throw new Error('useHub must be used inside <HubProvider>')
  return ctx
}
