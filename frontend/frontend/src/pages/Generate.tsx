import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { AGENT_QS, EXTRACTED, TIER_NOTES } from '@/data/demo'
import { useHub, type Tier } from '@/store/HubProvider'
import { buildChangeSpec, FIELDS_TOTAL, fieldsFilled, parseTemplate } from '@/features/generate/session'
import { useDemoTemplate } from '@/features/generate/useDemoTemplate'
import { useLivePreview } from '@/features/preview/useLivePreview'
import { LivePreviewPanel } from '@/features/preview/LivePreviewPanel'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/input'
import { Segmented } from '@/components/ui/segmented'
import { Tag } from '@/components/ui/tag'
import { DemoBadge, PageBody, PageHeading } from '@/components/common'
import { SparkleIcon } from '@/components/icons'

const TIER_OPTIONS = [
  { value: 'T1', label: 'T1' },
  { value: 'T2', label: 'T2' },
  { value: 'T3', label: 'T3' },
] as const

export function Generate() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const { startSession, updateSession, sessions, saveDraft } = useHub()

  /* Starts from the real document the Use-template button came from — its title,
     format and version are genuine even though the walkthrough itself is
     scripted. */
  const template = useDemoTemplate(id)
  const [chatInput, setChatInput] = useState('')

  /* One session per visit, unless `?session=` names an existing one to resume
     (the Drafts and My-documents rows link in that way). Creating a session
     touches HubProvider's state, so it happens in an effect rather than
     during render — React 18 flags setState-during-a-different-component's-
     render even when, as here, it is idempotent. */
  const requestedId = params.get('session')
  const resumedId = requestedId && sessions[requestedId] ? requestedId : null
  const [createdId, setCreatedId] = useState<string | null>(null)
  /* Keyed on the route id, not `template.id` — the real template resolves
     asynchronously, so `template` is still the fallback on the first render
     and the session would otherwise remember that instead of the document the
     user actually picked. */
  useEffect(() => {
    if (!resumedId && !createdId && id) setCreatedId(startSession(id).id)
  }, [resumedId, createdId, id, startSession])

  const sessionId = resumedId ?? createdId
  const session = sessionId ? sessions[sessionId] : undefined

  useEffect(() => {
    window.scrollTo(0, 0)
  }, [sessionId])

  const answers = session?.answers ?? []
  const qIndex = session?.qIndex ?? 0
  const tier: Tier = session?.tier ?? 'T2'
  const done = qIndex >= AGENT_QS.length

  const original = useMemo(() => parseTemplate(template), [template])
  const spec = useMemo(
    () => buildChangeSpec(template, answers, tier, qIndex, chatInput),
    [template, answers, tier, qIndex, chatInput],
  )
  const preview = useLivePreview(original, spec)

  const sendAnswer = () => {
    const v = chatInput.trim()
    if (!v || done || !sessionId) return
    const next = [...answers]
    next[qIndex] = v
    updateSession(sessionId, { answers: next, qIndex: qIndex + 1 })
    setChatInput('')
  }

  /* The transcript is derived, not stored: questions up to the current index,
     each followed by its answer and the chips the extractor pulled out of it. */
  const messages: { text: string; role: 'agent' | 'user'; chips?: { key: string; value: string }[] }[] = []
  for (let i = 0; i < AGENT_QS.length && i <= qIndex; i++) {
    messages.push({ text: AGENT_QS[i].ask, role: 'agent' })
    if (answers[i] !== undefined) messages.push({ text: answers[i], role: 'user', chips: EXTRACTED[i] })
  }
  if (done) {
    messages.push({
      text: 'Thanks — that is everything. 18 of 18 placeholders are filled. Generate the document when you are ready.',
      role: 'agent',
    })
  }

  const filled = fieldsFilled(answers.length)
  const pct = Math.round((filled / FIELDS_TOTAL) * 100)
  const liveTitle = answers[0] || chatInput.trim() || `${template.name} — untitled`

  return (
    <PageBody>
      <div className="flex items-start gap-3 flex-wrap mb-[22px]">
        <PageHeading
          title="New document"
          subtitle="Answer the agent questions and the document fills in as you go."
          className="mb-0"
        />
        <DemoBadge className="mt-[10px]" />
      </div>

      <p className="text-[12.5px] opacity-60 -mt-[10px] mb-[18px] max-w-[70ch]">
        This walkthrough is a demonstration. The questions and the filled-in preview are scripted, and the document
        it creates is held in this tab only — nothing is written to the server.
      </p>

      <div className="grid grid-cols-[repeat(auto-fit,minmax(320px,1fr))] gap-5 items-stretch">
        {/* ── Conversation ─────────────────────────────────────────────── */}
        <div className="bg-surface border border-divider rounded-card flex flex-col min-h-[520px] overflow-hidden shadow-elev-sm">
          <div className="flex items-center gap-3 py-4 px-5 border-b border-divider">
            <div className="w-8 h-8 flex-none rounded-md bg-accent-100 text-accent grid place-items-center">
              <SparkleIcon width={16} height={16} />
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-label-md uppercase text-accent">AI assistant</div>
              <div className="text-title-lg text-ink">
                {done ? 'All questions answered' : `Step ${qIndex + 1} of ${AGENT_QS.length}`}
              </div>
            </div>
            <div className="flex flex-col items-end gap-[5px]">
              <Segmented
                name="hubtier"
                value={tier}
                options={TIER_OPTIONS}
                onChange={(t) => sessionId && updateSession(sessionId, { tier: t })}
              />
              <div className="text-[11.5px] opacity-55 text-right">{TIER_NOTES[tier]}</div>
            </div>
          </div>

          <div className="px-5 pt-4">
            <div className="h-1.5 w-full rounded-pill bg-neutral-200 overflow-hidden">
              <div
                className="h-full rounded-pill bg-accent2-900 transition-all duration-300"
                style={{ width: `${Math.round((Math.min(qIndex, AGENT_QS.length) / AGENT_QS.length) * 100)}%` }}
              />
            </div>
          </div>

          <div className="flex-1 p-5 flex flex-col gap-4 overflow-y-auto">
            {messages.map((m, i) => (
              <div key={i} className="flex flex-col gap-[7px]">
                <div className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div
                    className={`max-w-[82%] py-3 px-4 rounded-lg text-body-md ${
                      m.role === 'user' ? 'bg-accent2-900 text-white' : 'bg-neutral-200 text-ink'
                    }`}
                  >
                    {m.text}
                  </div>
                </div>
                {m.chips?.length ? (
                  <div className="flex gap-[7px] flex-wrap justify-end">
                    {m.chips.map((c) => (
                      <Tag key={c.key} variant="outline" className="whitespace-nowrap">
                        <span className="opacity-55">{c.key}</span>&nbsp;{c.value}
                      </Tag>
                    ))}
                  </div>
                ) : null}
              </div>
            ))}
          </div>

          <div className="py-4 px-5 border-t border-divider flex gap-3 items-center">
            <Textarea
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  sendAnswer()
                }
              }}
              placeholder={done ? 'All done' : AGENT_QS[qIndex].placeholder}
              disabled={done}
              rows={Math.min(5, Math.max(1, chatInput.split('\n').length + Math.floor(chatInput.length / 58)))}
              className="flex-1 resize-none leading-[1.5] max-h-[140px] min-h-0"
            />
            <Button
              variant="primary"
              className="whitespace-nowrap"
              disabled={!chatInput.trim() || done}
              onClick={sendAnswer}
            >
              Send
            </Button>
            <Button
              variant="secondary"
              className="whitespace-nowrap"
              disabled={answers.length === 0}
              onClick={() => sessionId && saveDraft(sessionId, template.name, template.fmt)}
            >
              Save draft
            </Button>
          </div>
        </div>

        {/* ── Live preview ─────────────────────────────────────────────── */}
        <LivePreviewPanel
          original={original}
          preview={preview}
          title={liveTitle}
          subtitle={`${template.name} v${template.version} · Yamaha Motor Solutions India`}
          answersCaptured={answers.length}
          totalQuestions={AGENT_QS.length}
        />
      </div>

      {/* ── Derivation counter + preservation guarantee ─────────────────── */}
      <div className="mt-4 bg-surface border-t border-divider rounded-card py-[14px] px-[18px] flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-[11px]">
          <div
            className="w-8 h-8 rounded-pill grid place-items-center"
            style={{
              background: `conic-gradient(var(--color-accent) ${Math.round((filled / FIELDS_TOTAL) * 360)}deg, var(--color-divider) 0)`,
            }}
          >
            <div className="w-[22px] h-[22px] rounded-pill bg-surface grid place-items-center text-[9px] font-bold">
              {pct}
            </div>
          </div>
          <span className="text-[12.5px] opacity-65">
            {answers.length} answers → {filled} of {FIELDS_TOTAL} fields
          </span>
        </div>

        <Tag variant="accent" className="whitespace-nowrap mx-auto hub-preserve-full">
          Preserved: logo · sensitivity label · 27 merged ranges · 0 formulas touched
        </Tag>
        <Tag variant="accent" className="whitespace-nowrap mx-auto hub-preserve-short">
          Preserved: 4 guarantees
        </Tag>

        <div className="flex gap-[10px] flex-wrap ml-auto">
          <Button
            variant="secondary"
            className="whitespace-nowrap"
            disabled={answers.length === 0}
            onClick={() => sessionId && saveDraft(sessionId, template.name, template.fmt)}
          >
            Save draft
          </Button>
          <Button
            variant="primary"
            className="whitespace-nowrap"
            disabled={!sessionId}
            onClick={() => sessionId && navigate(`/generate/${sessionId}/review`)}
          >
            Review &amp; commit
          </Button>
        </div>
      </div>
    </PageBody>
  )
}
