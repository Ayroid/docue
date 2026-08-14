import { useCallback, useEffect, useMemo, useState } from 'react'
import { toChangeSpec, toParsedDocument } from '@/features/generate/adapters'
import type { ChangeSpec, ParsedDocument } from '@/features/preview/types'
import {
  getSession,
  getSpec,
  sendAnswer as postAnswer,
  sendInstruction as postInstruction,
  sendNotes as postNotes,
  startSession,
  type AnswerOut,
  type ProgressOut,
  type QuestionOut,
  type SessionOut,
  type TurnOut,
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
  chips?: { key: string; value: string; source?: 'answer' | 'volunteered' }[]
  /** Echoed locally and not yet recorded by the server. Rendered as in-flight
      so the transcript never implies a turn that the session does not hold. */
  pending?: boolean
}

/** An instruction is a turn in the transcript but answers no question. */
const isAnswer = (turn: TurnOut) => (turn.kind ?? 'answer') !== 'instruction'

/**
 * How many planned questions have been answered.
 *
 * Not `turns.length`. Instructions live in the same list, and counting one would
 * advance the question pointer past a question the user was never asked — the
 * client-side twin of `answered_count` in `app/conversation/state.py`.
 */
const answeredCount = (session: SessionOut) => session.turns.filter(isAnswer).length

export interface SessionState {
  loading: boolean
  /** **Startup only** — the session could not be created or loaded, so there is
      nothing to show. A failure while answering must never land here: it would
      make the page throw away a half-finished interview. That is `sendError`. */
  error: string | null
  /** The last answer or instruction failed. The conversation is intact and the
      turn can simply be sent again. */
  sendError: string | null
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
  /** Resolves `true` when the turn was recorded. The caller needs to know, so
      it can put the user's text back in the composer instead of losing it. */
  send: (answer: string, opts?: { skip?: boolean }) => Promise<boolean>
  /** Hand over a block of prior notes. Fills everything they supply and stops
      the questions still ahead from asking for it. Never consumes a question. */
  applyNotes: (input: { text?: string; file?: File }) => Promise<boolean>
  reload: () => void
}

const shown = (value: unknown) =>
  Array.isArray(value) ? `${value.length} row(s)` : String(value)

/**
 * The transcript, walked in the order it happened.
 *
 * Turns are no longer one-per-question and cannot be zipped against the plan by
 * index: a free-form instruction is a turn that answers nothing, and pairing
 * `turns[i]` with `questions[i]` after one of those would caption every later
 * answer with the wrong question. The question is emitted when the answer that
 * replies to it comes up, and instructions fall through as plain user messages.
 */
function messagesFrom(session: SessionOut | null, questions: QuestionOut[]): ChatMessage[] {
  if (!session) return []
  const out: ChatMessage[] = []
  let asked = 0

  for (const turn of session.turns) {
    if (isAnswer(turn)) {
      const question = questions[asked]
      if (question) out.push({ role: 'agent', text: question.question_text })
      asked += 1
    }
    out.push({
      role: 'user',
      text: turn.skipped ? '(skipped)' : turn.answer,
      // Rebuilt from the stored extraction, so a reload shows the same chips
      // the answer response did rather than losing them.
      chips: [
        ...Object.entries(turn.extracted).map(([key, value]) => ({
          key,
          value: shown(value),
          source: 'answer' as const,
        })),
        ...Object.entries(turn.volunteered ?? {}).map(([key, value]) => ({
          key,
          value: shown(value),
          source: 'volunteered' as const,
        })),
      ],
    })
  }

  // The question still on the table, asked but not yet answered.
  const pending = questions[asked]
  if (pending) out.push({ role: 'agent', text: pending.question_text })
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
  options: { resumeSessionId?: string | null; intent?: string; tier?: Tier; notes?: string } = {},
): SessionState {
  const { resumeSessionId = null, intent, tier, notes } = options

  const [loading, setLoading] = useState(true)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sendError, setSendError] = useState<string | null>(null)
  const [session, setSession] = useState<SessionOut | null>(null)
  const [template, setTemplate] = useState<TemplateOut | null>(null)
  const [original, setOriginal] = useState<ParsedDocument | null>(null)
  const [specBody, setSpecBody] = useState<SpecOut | null>(null)
  const [planSummary, setPlanSummary] = useState<string | null>(null)
  const [warnings, setWarnings] = useState<string[]>([])
  const [degraded, setDegraded] = useState(false)
  const [prefillDegraded, setPrefillDegraded] = useState(false)
  const [nonce, setNonce] = useState(0)
  /* The answer just sent, held only until the refetched session contains it.
     Sending is a model call — extraction and derivation — so without this the
     message is nowhere at all for several seconds: cleared from the composer
     and not yet in the transcript. */
  const [pendingEcho, setPendingEcho] = useState<string | null>(null)

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
          : await startSession({ templateId: templateId!, intent, tier, notes })
        if (cancelled) return

        if ('plan_summary' in live) setPlanSummary((live as { plan_summary: string }).plan_summary)
        setSession(live)
        // A pasted blob that could not be read is the one degraded state that
        // happens before any turn, so `send` never gets the chance to report
        // it. Held apart from the per-turn flag so the first answer's `false`
        // cannot wipe it.
        setPrefillDegraded(Boolean((live.known_context as { prefill_degraded?: boolean })?.prefill_degraded))

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
      if (!session) return false
      const question = session.questions[answeredCount(session)] ?? null
      // No question left, but the user still has something to say — that is an
      // instruction, not a dead end. Skipping is meaningless without a question
      // to skip, so it is only offered on the answer path.
      if (!question && (opts.skip || !answer.trim())) return false

      /* Set before the request, not after: the whole point is that it lands on
         screen on the same tick the user pressed Enter. */
      setPendingEcho(opts.skip ? '(skipped)' : answer)
      setSending(true)
      setSendError(null)
      try {
        const turn: AnswerOut = question
          ? await postAnswer(session.session_id, {
              questionId: question.question_id,
              answer,
              skip: opts.skip,
            })
          : await postInstruction(session.session_id, answer)
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
        return true
      } catch (err) {
        /* `sendError`, not `error`. Writing to `error` here is what let one
           failed answer replace the whole conversation with the "could not
           start a session" screen — the session had started perfectly well. */
        setSendError(err instanceof Error ? err.message : 'That answer could not be recorded.')
        return false
      } finally {
        /* Dropped in the same commit as `setSession`, so the echo is replaced
           by the real turn rather than both being on screen for a frame. On a
           failure it goes too — a message that was never recorded must not sit
           in the transcript looking like it was. */
        setPendingEcho(null)
        setSending(false)
      }
    },
    [session],
  )

  /**
   * Notes pasted into the panel above the chat.
   *
   * Routed to `/instruct` rather than `/answer` even when a question is
   * pending: a page of notes is not an answer to "what was the venue?", and
   * sending it as one would consume that question and attribute everything it
   * happened to fill to a question it was not a reply to. The server narrows
   * the questions still ahead, so what the notes covered stops being asked.
   */
  const applyNotes = useCallback(
    async (input: { text?: string; file?: File }) => {
      const text = (input.text ?? '').trim()
      if (!session || (!text && !input.file)) return false
      setPendingEcho(input.file ? `Reading ${input.file.name}…` : text)
      setSending(true)
      setSendError(null)
      try {
        const turn: AnswerOut = await postNotes(session.session_id, { text, file: input.file })
        setWarnings(turn.warnings)
        setDegraded(turn.degraded)
        const [live, spec] = await Promise.all([
          getSession(session.session_id),
          getSpec(session.session_id),
        ])
        setSession(live)
        setSpecBody(spec)
        return true
      } catch (err) {
        setSendError(err instanceof Error ? err.message : 'Those notes could not be read.')
        return false
      } finally {
        setPendingEcho(null)
        setSending(false)
      }
    },
    [session],
  )

  const questions = session?.questions ?? []
  const currentQuestion = session ? (session.questions[answeredCount(session)] ?? null) : null

  const spec = useMemo(
    () => (specBody ? toChangeSpec(specBody.spec) : EMPTY_SPEC),
    [specBody],
  )
  /* The echo goes last. `messagesFrom` ends on the question still on the table,
     which is exactly the one this answer is replying to. */
  const messages = useMemo(() => {
    const transcript = messagesFrom(session, questions)
    if (pendingEcho === null) return transcript
    return [...transcript, { role: 'user' as const, text: pendingEcho, pending: true }]
  }, [session, questions, pendingEcho])

  return {
    loading,
    error,
    sendError,
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
    // The per-turn flag OR the pre-fill one. `send` overwrites its own flag on
    // every turn, so a blob that could not be read would otherwise stop being
    // reported the moment the first question was answered.
    degraded: degraded || prefillDegraded,
    warnings,
    done: Boolean(session) && currentQuestion === null,
    send,
    applyNotes,
    reload,
  }
}
