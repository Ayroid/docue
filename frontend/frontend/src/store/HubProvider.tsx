import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react'
import { MYDOCS, SEED_DRAFTS, TEMPLATES, type Fmt, type MyDoc, type Template } from '@/data/mock'

export type Role = 'Admin' | 'Member'
export type Tier = 'T1' | 'T2' | 'T3'

export interface Draft {
  id: string
  title: string
  templateId: number
  fmt: Fmt
  answers: string[]
  saved: string
}

export interface Upload {
  id: number
  name: string
  fmt: Fmt
  meta: string
  note: string
  status: string
  kind: string
  /** The real backend template id, when this row came from an actual `POST /templates` call. */
  backendId?: string
}

/** A generation session — the server-side resumable state of §6, held client-side for now. */
export interface Session {
  id: string
  templateId: number
  tier: Tier
  answers: string[]
  qIndex: number
  /** Set once the user commits; the id of the resulting generated document. */
  documentId?: string
  draftId?: string
}

interface HubState {
  loggedIn: boolean
  login: () => void
  logout: () => void
  role: Role
  sidebarOpen: boolean
  toggleSidebar: () => void

  templates: Template[]
  documents: MyDoc[]
  drafts: Draft[]
  uploads: Upload[]

  sessions: Record<string, Session>
  startSession: (templateId: number, seed?: Partial<Session>) => Session
  updateSession: (id: string, patch: Partial<Session>) => void
  getSession: (id: string) => Session | undefined

  saveDraft: (sessionId: string) => void
  commitSession: (sessionId: string) => string
  lastUpload: { name: string; fmt: Fmt; meta: string } | null
  addUpload: (name: string, fmt: Fmt, meta: string, backendId?: string) => void
  publishUpload: (id: number, name: string, fmt: Fmt) => void

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

  const [published, setPublished] = useState<Template[]>([])
  const [documents, setDocuments] = useState<MyDoc[]>(MYDOCS)
  const [drafts, setDrafts] = useState<Draft[]>(SEED_DRAFTS)
  const [uploads, setUploads] = useState<Upload[]>([])
  const [lastUpload, setLastUpload] = useState<{ name: string; fmt: Fmt; meta: string } | null>(null)
  const [sessions, setSessions] = useState<Record<string, Session>>({})
  const [toast, setToast] = useState<string | null>(null)
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false)
  const toastTimer = useRef<ReturnType<typeof setTimeout>>()

  const templates = useMemo(() => [...published, ...TEMPLATES], [published])

  const fireToast = useCallback((message: string) => {
    setToast(message)
    clearTimeout(toastTimer.current)
    toastTimer.current = setTimeout(() => setToast(null), 2600)
  }, [])

  const startSession = useCallback((templateId: number, seed: Partial<Session> = {}) => {
    const session: Session = {
      id: `s${++sessionSeq}`,
      templateId,
      tier: 'T2',
      answers: [],
      qIndex: 0,
      ...seed,
    }
    setSessions((prev) => ({ ...prev, [session.id]: session }))
    return session
  }, [])

  const updateSession = useCallback((id: string, patch: Partial<Session>) => {
    setSessions((prev) => (prev[id] ? { ...prev, [id]: { ...prev[id], ...patch } } : prev))
  }, [])

  const getSession = useCallback((id: string) => sessions[id], [sessions])

  const saveDraft = useCallback(
    (sessionId: string) => {
      const session = sessions[sessionId]
      if (!session) return

      const template = TEMPLATES.find((t) => t.id === session.templateId)
      const entry: Draft = {
        id: session.draftId ?? `d${sessionId}`,
        title: session.answers[0] || (template ? `${template.name} — draft` : 'Untitled draft'),
        templateId: session.templateId,
        fmt: template?.fmt ?? 'DOC',
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
    (sessionId: string) => {
      const session = sessions[sessionId]
      const template = TEMPLATES.find((t) => t.id === session?.templateId)
      const docId = `g${sessionId}`
      const name = session?.answers[0] || (template ? `${template.name} — new` : 'Generated document')
      const ext = template?.fmt === 'XLS' ? '.xlsx' : template?.fmt === 'PPT' ? '.pptx' : '.docx'

      setDocuments((prev) =>
        prev.some((d) => d.id === docId)
          ? prev
          : [
              {
                id: docId,
                name,
                template: template?.name ?? 'Unknown template',
                version: template?.version ?? '—',
                fmt: template?.fmt ?? 'DOC',
                ext,
                size: '86 KB',
                created: 'Today, 10:24',
                status: 'Draft',
                kind: template?.fmt === 'XLS' ? 'Excel' : template?.fmt === 'PPT' ? 'PowerPoint' : 'Word',
              },
              ...prev,
            ],
      )
      updateSession(sessionId, { documentId: docId })
      return docId
    },
    [sessions, updateSession],
  )

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

  const publishUpload = useCallback(
    (id: number, name: string, fmt: Fmt) => {
      setUploads((prev) => prev.filter((u) => u.id !== id))
      setPublished((prev) => [
        {
          id: 1000 + prev.length,
          name,
          category: 'Functional',
          group: 'MOM',
          fmt,
          owner: 'Doc control',
          version: '1.0',
          uses: 0,
          updated: 'just now',
          desc: 'Newly published from the ingestion queue.',
        },
        ...prev,
      ])
      fireToast(`Published ${name} to Discovery`)
    },
    [fireToast],
  )

  const value = useMemo<HubState>(
    () => ({
      loggedIn,
      login: () => setLoggedIn(true),
      logout: () => setLoggedIn(false),
      role,
      sidebarOpen,
      toggleSidebar: () => setSidebarOpen((v) => !v),
      templates,
      documents,
      drafts,
      uploads,
      sessions,
      startSession,
      updateSession,
      getSession,
      saveDraft,
      commitSession,
      lastUpload,
      addUpload,
      publishUpload,
      toast,
      fireToast,
      uploadDialogOpen,
      closeUploadDialog: () => setUploadDialogOpen(false),
    }),
    [
      loggedIn,
      role,
      sidebarOpen,
      templates,
      documents,
      drafts,
      uploads,
      sessions,
      startSession,
      updateSession,
      getSession,
      saveDraft,
      commitSession,
      lastUpload,
      addUpload,
      publishUpload,
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
