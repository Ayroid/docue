import { useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/input'
import { NOTE_FILE_TYPES } from '@/services/sessions'

/**
 * "I already have this written down."
 *
 * Collapsed by default and sitting above the transcript, so the one-click path
 * into the conversation is unchanged for anyone with nothing to paste. Opening
 * it is a deliberate act; ignoring it costs a line of chrome.
 *
 * Deliberately **not** the composer. The composer is capped at five rows, sends
 * on a bare Enter and is aimed at the current question — every one of which is
 * wrong for a page of minutes pasted out of an email. This is also why it does
 * not route through `send`: a block of notes is not an answer to "what was the
 * venue?", and sending it as one would consume that question.
 */
export function NotesPanel({
  disabled,
  onApply,
}: {
  disabled?: boolean
  onApply: (input: { text?: string; file?: File }) => void
}) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="mx-5 mt-4 mb-0 py-[9px] px-3 rounded-card border border-dashed border-divider
                   text-left text-[12.5px] opacity-70 hover:opacity-100 hover:border-accent
                   bg-transparent cursor-pointer font-[inherit] transition-colors"
      >
        Have notes already? Paste them or attach a file, and I&rsquo;ll fill in what they cover.
      </button>
    )
  }

  const apply = () => {
    const value = text.trim()
    if ((!value && !file) || disabled) return
    // Cleared and closed immediately: what happens next is visible in the
    // transcript and the preview, so leaving the panel open with the text still
    // in it would suggest nothing had been done with it.
    setText('')
    setFile(null)
    setOpen(false)
    onApply({ text: value, file: file ?? undefined })
  }

  return (
    <div className="mx-5 mt-4 p-3 rounded-card border border-divider bg-neutral-200/40 flex flex-col gap-2">
      <div className="text-[12.5px] opacity-70">
        Paste meeting notes, an email, a brief &mdash; or attach a file. Whatever it covers gets
        filled in; whatever it doesn&rsquo;t, I&rsquo;ll still ask about.
      </div>
      <Textarea
        autoFocus
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Cycle 2 of the AP automation workshop, 15 September, Conference Room 7&hellip;"
        rows={7}
        className="resize-none leading-[1.5] text-[13px]"
      />

      <input
        ref={fileRef}
        type="file"
        accept={NOTE_FILE_TYPES}
        className="hidden"
        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
      />
      <div className="flex items-center gap-2 text-[12px]">
        <Button variant="secondary" disabled={disabled} onClick={() => fileRef.current?.click()}>
          Attach a file
        </Button>
        {file ? (
          <>
            <span className="opacity-70">{file.name}</span>
            <button
              type="button"
              className="bg-transparent border-0 cursor-pointer underline opacity-55 font-[inherit] text-[12px]"
              onClick={() => {
                setFile(null)
                if (fileRef.current) fileRef.current.value = ''
              }}
            >
              remove
            </button>
          </>
        ) : (
          <span className="opacity-45">Word, Excel, PowerPoint, PDF or a text file</span>
        )}
      </div>

      <div className="flex gap-2 items-center">
        <Button variant="primary" disabled={(!text.trim() && !file) || disabled} onClick={apply}>
          {disabled ? 'Reading…' : 'Use these notes'}
        </Button>
        <Button
          variant="secondary"
          disabled={disabled}
          onClick={() => {
            setText('')
            setFile(null)
            setOpen(false)
          }}
        >
          Cancel
        </Button>
        <span className="text-[11.5px] opacity-50">
          Nothing is invented &mdash; only what the text actually says.
        </span>
      </div>
    </div>
  )
}
