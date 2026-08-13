import { useCallback, useEffect, useMemo, useState } from 'react'
import { toChangeSpec, toParsedDocument } from '@/features/generate/adapters'
import type { ChangeSpec, ParsedDocument } from '@/features/preview/types'
import {
  getSession,
  getSpec,
  sendAnswer as postAnswer,
  startSession,
  type AnswerOut,
  type ProgressOut,
  type QuestionOut,
  type SessionOut,
  type SpecOut,
  type Tier,
} from '@/services/sessions'
import { getTemplate, getTemplateRegions, type TemplateOut } from '@/services/templates'

const EMPTY_SPEC: ChangeSpec = { specVersion: '1.0', baseVersionId: '', tier: 'T2', operations: [] }

const EMPTY_PROGRESS: ProgressOut = {
  answered: 0,
  total_questions: 0,
  fields_filled: 0,
  fields_total: 0,
}

export interface ChatMessage {
  role: 'agent' | 'user'
  text: string
  chips?: { key: string; value: string }[]
}

export interface SessionState {
  loading: boolean
  error: string | null
  /** Set while an answer is in flight — the extractor is a model call. */
  sending: boolean
  session: SessionOut | null
  template: TemplateOut | null
  questions: QuestionOut[]
  currentQuestion: QuestionOut | null
  /** The regions the current question will fill. The preview highlights these. */
  pendingRegions: string[]
  original: ParsedDocument | null
  spec: ChangeSpec
  specSkipped: SpecOut['skipped']
  progress: ProgressOut
  messages: ChatMessage[]
  planSummary: string | null
  /** True when a model stage was unavailable and a fallback produced this state. */
  degraded: boolean
  warnings: string[]
  done: boolean
  send: (answer: string, opts?: { skip?: boolean }) => Promise<void>
  reload: () => void
}

function messagesFrom(session: SessionOut | null, questions: QuestionOut[]): ChatMessage[] {
  if (!session) return []
  const out: ChatMessage[] = []

  for (let i = 0; i < questions.length && i <= session.turns.length; i++) {
    out.push({ role: 'agent', text: questions[i].question_text })
    const turn = session.turns[i]
    if (!turn) continue
    out.push({
      role: 'user',
      text: turn.skipped ? '(skipped)' : turn.answer,
      // Rebuilt from the stored extraction, so a reload shows the same chips
      // the answer response did rather than losing them.
      chips: Object.entries(turn.extracted).map(([key, value]) => ({
        key,
        value: Array.isArray(value) ? `${value.length} row(s)` : String(value),
      })),
    })
  }
  return out
}

/**
 * The fill conversation, backed by the real `/api/v1/sessions` endpoints.
 *
 * Replaces the scripted walkthrough that used to live in `data/demo.ts`. The
 * questions, the extraction, the derived values and the Change Spec all come
 * from the server now; what stays client-side is the *preview*, which applies
 * the spec to an in-memory copy of the parsed original (Implementation Plan §5's
 * fast path) and never touches the stored document.
 *
 * The spec is refetched after every answer rather than assembled here. It is
 * the server's artifact — it is what will actually be compiled — and rebuilding
 * a second copy in the browser is how the preview and the output drift apart.
 */
export function useSession(
  templateId: string | undefined,
  options: { resumeSessionId?: string | null; intent?: string; tier?: Tier } = {},
): SessionState {
  const { resumeSessionId = null, intent, tier } = options

  const [loading, setLoading] = useState(true)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [session, setSession] = useState<SessionOut | null>(null)
  const [template, setTemplate] = useState<TemplateOut | null>(null)
  const [original, setOriginal] = useState<ParsedDocument | null>(null)
  const [specBody, setSpecBody] = useState<SpecOut | null>(null)
  const [planSummary, setPlanSummary] = useState<string | null>(null)
  const [warnings, setWarnings] = useState<string[]>([])
  const [degraded, setDegraded] = useState(false)
  const [nonce, setNonce] = useState(0)

  const reload = useCallback(() => setNonce((n) => n + 1), [])

  useEffect(() => {
    if (!templateId && !resumeSessionId) return
    let cancelled = false

    async function boot() {
      setLoading(true)
      setError(null)
      try {
        const live = resumeSessionId
          ? await getSession(resumeSessionId)
          : await startSession({ templateId: templateId!, intent, tier })
        if (cancelled) return

        if ('plan_summary' in live) setPlanSummary((live as { plan_summary: string }).plan_summary)
        setSession(live)

        // The template record and the region schema in parallel — neither
        // depends on the other and both are needed before the first paint.
        const [record, schema] = await Promise.all([
          getTemplate(live.template_id),
          getTemplateRegions(live.template_id, live.base_version_id),
        ])
        if (cancelled) return

        setTemplate(record)
        setOriginal(
          toParsedDocument(schema, {
            title: record.title,
            subtitle: `${record.title} · ${record.form_id ?? record.format.toUpperCase()}`,
          }),
        )

        const spec = await getSpec(live.session_id)
        if (!cancelled) setSpecBody(spec)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Could not start the session.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    void boot()
    return () => {
      cancelled = true
    }
    // `intent` and `tier` are start-time only: changing them mid-conversation
    // would restart it and throw away the answers already given.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templateId, resumeSessionId, nonce])

  const send = useCallback(
    async (answer: string, opts: { skip?: boolean } = {}) => {
      if (!session) return
      const question = session.questions[session.turns.length]
      if (!question) return

      setSending(true)
      setError(null)
      try {
        const turn: AnswerOut = await postAnswer(session.session_id, {
          questionId: question.question_id,
          answer,
          skip: opts.skip,
        })
        setWarnings(turn.warnings)
        setDegraded(turn.degraded)

        // Refetch rather than patch locally: the turn response reports what
        // changed, but the session is the source of truth for what the review
        // screen and a reload will see.
        const [live, spec] = await Promise.all([
          getSession(session.session_id),
          getSpec(session.session_id),
        ])
        setSession(live)
        setSpecBody(spec)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'That answer could not be recorded.')
      } finally {
        setSending(false)
      }
    },
    [session],
  )

  const questions = session?.questions ?? []
  const currentQuestion = session ? (session.questions[session.turns.length] ?? null) : null

  const spec = useMemo(
    () => (specBody ? toChangeSpec(specBody.spec) : EMPTY_SPEC),
    [specBody],
  )
  const messages = useMemo(() => messagesFrom(session, questions), [session, questions])

  return {
    loading,
    error,
    sending,
    session,
    template,
    questions,
    currentQuestion,
    pendingRegions: currentQuestion?.covers_regions ?? [],
    original,
    spec,
    specSkipped: specBody?.skipped ?? [],
    progress: session?.progress ?? EMPTY_PROGRESS,
    messages,
    planSummary,
    degraded,
    warnings,
    done: Boolean(session) && currentQuestion === null,
    send,
    reload,
  }
}
