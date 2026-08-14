import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useSession } from '@/features/generate/useSession'
import { useLivePreview } from '@/features/preview/useLivePreview'
import { LivePreviewPanel } from '@/features/preview/LivePreviewPanel'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/ui/icon'
import { Textarea } from '@/components/ui/input'
import { Spinner } from '@/components/ui/spinner'
import { Tag } from '@/components/ui/tag'
import { EmptyState, PageBody, PageHeading } from '@/components/common'
import { SparkleIcon } from '@/components/icons'

/**
 * The fill conversation. Implementation Plan §5's headline screen.
 *
 * Chat on the left, live preview on the right, derivation counter along the
 * bottom. Everything on it is real: the questions come from the question
 * planner, the chips from the answer extractor, the preview from the Change
 * Specification the server would compile, and the counter from the session's
 * own progress.
 *
 * The tier picker is gone. It offered T1/T2/T3 as a per-question toggle, but
 * the tier is fixed when the session starts — it shapes the question plan — so
 * a control that appeared to change it mid-conversation was describing
 * something that could not happen.
 */
export function Generate() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [chatInput, setChatInput] = useState('')

  const resumeSessionId = params.get('session')
  /* Set when this conversation was started from "Update Document" rather than
     from Generate. It changes what the review screen offers at the end — a
     submission for approval, not a document — so it has to survive the hop. */
  const updatingTemplate = params.get('mode') === 'version'
  const state = useSession(id, { resumeSessionId })
  const { loading, error, sending, session, original, done, send, reload } = state

  const submit = async (skip = false) => {
    const value = chatInput.trim()
    if ((!value && !skip) || sending) return
    // `done` is no longer a gate. With no question left the message becomes an
    // instruction, which is the only way to say "change the heading" at all.
    if (done && (skip || !value)) return
    setChatInput('')
    /* Cleared straight away so the echo reads as sent, but handed back if the
       turn did not land. Typing an answer twice because the network blinked is
       not a reasonable thing to ask of anyone. */
    const recorded = await send(value, { skip })
    if (!recorded && !skip) setChatInput((current) => current || value)
  }

  if (loading) return <PlanningTemplate />

  /* Keyed on there being nothing to show, not on `error` being set. The old
     guard also fired for an error raised *during* the conversation, which threw
     away every answer already given because one turn failed to send. Those are
     `sendError` now and are reported beside the composer. */
  if (!session || !original) {
    return (
      <PageBody>
        <EmptyState
          title="Could not start a session"
          body={error ?? 'The template has no detected regions yet — ingestion may still be running.'}
          action={{ label: 'Try again', onClick: reload }}
        />
      </PageBody>
    )
  }

  return <Conversation {...{ state, chatInput, setChatInput, submit, navigate, updatingTemplate }} />
}

/**
 * The wait before the conversation exists.
 *
 * The planner reads the template, works out which regions a person has to
 * answer for, and writes the question list. There is no progress to report
 * while it does: the call is one request that either comes back with a plan or
 * doesn't, so this shows an indeterminate spinner and says what is being
 * worked on. No percentage, no ticking stage list — either would be a
 * animation dressed up as telemetry.
 *
 * The three lines below the spinner are what the agent does, stated in the
 * present tense as a group rather than lit one at a time, because which one it
 * is currently on is not something this page is told.
 */
function PlanningTemplate() {
  return (
    <PageBody>
      <PageHeading title="New document" subtitle="Setting up your document…" />

      <div className="bg-surface border border-divider rounded-card shadow-elev-sm px-6 py-16 grid place-items-center min-h-[52vh]">
        <div className="flex flex-col items-center text-center max-w-[46ch]">
          <Spinner size={76} thickness={4} label="Analysing the template" className="mb-6">
            <span className="text-accent">
              <SparkleIcon width={26} height={26} />
            </span>
          </Spinner>

          <h3 className="text-headline-md text-ink m-0 mb-2">The agent is analysing your template</h3>

          <p className="text-body-md text-neutral-700 m-0 mb-6">
            It is reading the layout, finding the regions that need filling in, and working out what
            it has to ask you before it can write the document.
          </p>

          <ul className="flex flex-col gap-[10px] m-0 p-0 list-none text-left w-full max-w-[34ch]">
            {[
              { icon: 'description', label: 'Reading the template' },
              { icon: 'highlight_alt', label: 'Finding the fillable regions' },
              { icon: 'forum', label: 'Planning the questions to ask' },
            ].map((step) => (
              <li key={step.label} className="flex items-center gap-3 text-body-md text-neutral-600">
                <span className="flex-none w-8 h-8 rounded-lg bg-accent-100 text-accent grid place-items-center">
                  <Icon name={step.icon} size={18} />
                </span>
                {step.label}
              </li>
            ))}
          </ul>

          <p className="text-label-md text-neutral-500 m-0 mt-6">
            A few seconds the first time this template is used — the plan is cached after that.
          </p>
        </div>
      </div>
    </PageBody>
  )
}

/* Split out so the hooks below never run before the session has loaded — an
   early return above a `useLivePreview` call would change the hook order
   between renders. */
function Conversation({
  state,
  chatInput,
  setChatInput,
  submit,
  navigate,
  updatingTemplate,
}: {
  state: ReturnType<typeof useSession>
  chatInput: string
  setChatInput: (v: string) => void
  submit: (skip?: boolean) => Promise<void>
  navigate: ReturnType<typeof useNavigate>
  /** Started from "Update document": the review screen submits for approval. */
  updatingTemplate: boolean
}) {
  const {
    session,
    template,
    questions,
    currentQuestion,
    pendingRegions,
    original,
    spec,
    progress,
    messages,
    sendError,
    degraded,
    warnings,
    sending,
    done,
  } = state

  const preview = useLivePreview(original!, spec)

  /* Follow the transcript down. The pane is bounded now, so a new message on a
     full conversation lands below the fold — an echo nobody scrolls to is the
     same as no echo at all. */
  const scrollRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, sending])
  const pct = progress.fields_total
    ? Math.round((progress.fields_filled / progress.fields_total) * 100)
    : 0

  const protectedCount = original!.regions.filter((r) => r.protected).length
  const answered = session!.turns.length

  return (
    <PageBody>
      <PageHeading
        title="New document"
        subtitle="Answer the agent's questions and the document fills in as you go."
      />

      {/* The plan summary — "N already correct, M derivable, K questions to
          ask" — is gone. It was a count of work not yet done, stated before the
          first question, and it duplicated what the conversation and the
          progress bar say as you go. `degraded` stays: that one changes what
          the agent will actually write, so it has to be said. */}
      {degraded ? (
        <div className="mb-4 rounded-card border border-dashed border-accent bg-accent-100 text-accent-900 py-[11px] px-[14px] text-[12.5px]">
          Running without the language model — the questions are grouped structurally and only
          what you type will be written. Nothing is invented.
        </div>
      ) : null}

      {/* Capped to the viewport so the two panes scroll inside themselves. They
          used to grow with their content, which pushed the composer — the one
          control on the screen you actually type into — below the fold on any
          template with more than a handful of regions. */}
      <div className="grid grid-cols-[repeat(auto-fit,minmax(320px,1fr))] gap-5 items-stretch h-[calc(100vh-320px)] min-h-[560px]">
        {/* ── Conversation ─────────────────────────────────────────────── */}
        <div className="bg-surface border border-divider rounded-card flex flex-col min-h-0 h-full overflow-hidden shadow-elev-sm">
          <div className="flex items-center gap-3 py-4 px-5 border-b border-divider">
            <div className="w-8 h-8 flex-none rounded-md bg-accent-100 text-accent grid place-items-center">
              <SparkleIcon width={16} height={16} />
            </div>
            {/* No step counter and no tier chip. The bar directly below already
                shows how far through the questions you are, and the tier is
                fixed when the session starts — nothing on this screen can
                change it, so naming it only invited the question. */}
            <div className="flex-1 min-w-0">
              <div className="text-title-lg text-ink">
                {done ? 'All questions answered' : 'AI assistant'}
              </div>
            </div>
          </div>

          <div className="px-5 pt-4">
            <div className="h-1.5 w-full rounded-pill bg-neutral-200 overflow-hidden">
              <div
                className="h-full rounded-pill bg-accent2-900 transition-all duration-300"
                style={{
                  width: questions.length
                    ? `${Math.round((Math.min(answered, questions.length) / questions.length) * 100)}%`
                    : '0%',
                }}
              />
            </div>
          </div>

          <div ref={scrollRef} className="flex-1 p-5 flex flex-col gap-4 overflow-y-auto">
            {messages.map((m, i) => (
              <div key={i} className="flex flex-col gap-[7px]">
                <div className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div
                    className={`max-w-[82%] py-3 px-4 rounded-lg text-body-md ${
                      m.role === 'user' ? 'bg-accent2-900 text-white' : 'bg-neutral-200 text-ink'
                    } ${m.pending ? 'opacity-60' : ''}`}
                  >
                    {m.text}
                  </div>
                </div>
                {/* An echo is on screen before the server has it. Saying so is
                    what keeps the optimism honest — the bubble is the user's
                    text, not a recorded turn, until the refetch replaces it. */}
                {m.pending ? (
                  <div className="flex justify-end">
                    <span className="text-[11px] opacity-45">Sending…</span>
                  </div>
                ) : null}
                {m.chips?.length ? (
                  <div className="flex gap-[7px] flex-wrap justify-end">
                    {m.chips.map((c) => (
                      // A volunteered value went somewhere the user was not
                      // looking. Badging it is what makes that checkable rather
                      // than something they have to trust.
                      <Tag
                        key={`${c.source ?? 'answer'}:${c.key}`}
                        variant={c.source === 'volunteered' ? 'accent' : 'outline'}
                        className="whitespace-nowrap"
                        title={
                          c.source === 'volunteered'
                            ? 'Also captured from that message — not asked for'
                            : undefined
                        }
                      >
                        <span className="opacity-55">{c.key}</span>&nbsp;{c.value}
                      </Tag>
                    ))}
                  </div>
                ) : null}
              </div>
            ))}

            {currentQuestion?.hint && !done ? (
              <div className="text-[11.5px] opacity-50 pl-1">
                {currentQuestion.hint}
                {currentQuestion.example ? ` e.g. “${currentQuestion.example}”` : ''}
              </div>
            ) : null}

            {done ? (
              <div className="flex justify-start">
                <div className="max-w-[82%] py-[11px] px-[14px] rounded-[12px] text-[14px] leading-[1.5] bg-accent-100 text-accent-900">
                  That’s everything — {progress.fields_filled} of {progress.fields_total} regions
                  are filled. Tell me about anything you want changed, or review and commit when
                  you’re ready.
                </div>
              </div>
            ) : null}

            {warnings.map((w) => (
              <div key={w} className="text-[11.5px] opacity-65 pl-1">
                {w}
              </div>
            ))}
          </div>

          {/* Reported here rather than in place of the page: the conversation
              behind it is intact and every answer already given still stands.
              The text is back in the box, so the fix is to press Send again. */}
          {sendError ? (
            <div className="mx-5 mb-1 rounded-lg border border-[color:var(--md-error)]/30 bg-[color:var(--md-error)]/10 py-2 px-3 text-[12.5px] text-ink">
              {sendError} Your answer is still in the box — try sending it again.
            </div>
          ) : null}

          <div className="py-4 px-5 border-t border-divider flex gap-3 items-center">
            <Textarea
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  void submit()
                }
              }}
              placeholder={
                done
                  ? 'Change anything — “change the heading to Q3 Review”…'
                  : 'Answer in your own words…'
              }
              // Running out of questions is not running out of things to say.
              // The composer stays open once the interview ends, and what goes
              // through it is an instruction rather than an answer.
              disabled={sending}
              rows={Math.min(5, Math.max(1, chatInput.split('\n').length + Math.floor(chatInput.length / 58)))}
              className="flex-1 resize-none leading-[1.5] max-h-[140px] min-h-0"
            />
            <Button
              variant="primary"
              className="whitespace-nowrap"
              disabled={!chatInput.trim() || sending}
              onClick={() => void submit()}
            >
              {sending ? 'Reading…' : done ? 'Apply' : 'Send'}
            </Button>
            {/* Skipping is only meaningful while a question is on the table. */}
            {done ? null : (
              <Button
                variant="secondary"
                className="whitespace-nowrap"
                disabled={sending}
                onClick={() => void submit(true)}
                title="Leave these regions untouched"
              >
                Skip
              </Button>
            )}
          </div>
        </div>

        {/* ── Live preview ─────────────────────────────────────────────── */}
        <LivePreviewPanel
          original={original!}
          preview={preview}
          title={template?.title ?? 'Untitled'}
          subtitle={
            template
              ? `${template.title}${template.form_id ? ` · ${template.form_id}` : ''}`
              : ''
          }
          pendingRegions={pendingRegions}
        />
      </div>

      {/* ── Derivation counter + preservation guarantee ─────────────────── */}
      <div className="mt-4 bg-surface border-t border-divider rounded-card py-[14px] px-[18px] flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-[11px]">
          <div
            className="w-8 h-8 rounded-pill grid place-items-center"
            style={{
              background: `conic-gradient(var(--color-accent) ${Math.round(pct * 3.6)}deg, var(--color-divider) 0)`,
            }}
          >
            <div className="w-[22px] h-[22px] rounded-pill bg-surface grid place-items-center text-[9px] font-bold">
              {pct}
            </div>
          </div>
          <span className="text-[12.5px] opacity-65">
            {answered} answer{answered === 1 ? '' : 's'} → {progress.fields_filled} of{' '}
            {progress.fields_total} fields
          </span>
        </div>

        {/* Counted from this document's own schema. The figures used to be
            hardcoded to the MOM's, which made them decoration on anything else. */}
        <Tag variant="accent" className="whitespace-nowrap mx-auto">
          {protectedCount} protected region{protectedCount === 1 ? '' : 's'} never written
        </Tag>

        <div className="flex gap-[10px] flex-wrap ml-auto">
          <Button
            variant="primary"
            className="whitespace-nowrap"
            disabled={progress.fields_filled === 0}
            onClick={() =>
              navigate(
                `/generate/${session!.session_id}/review${updatingTemplate ? '?mode=version' : ''}`,
              )
            }
          >
            {updatingTemplate ? 'Review & submit' : 'Review & commit'}
          </Button>
        </div>
      </div>
    </PageBody>
  )
}
