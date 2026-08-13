import { useCallback, useRef, useState, type ChangeEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { CATS, type Fmt } from '@/data/catalog'
import { useHub } from '@/store/HubProvider'
import { getTemplate, TemplateApiError, uploadTemplate, uploadedTemplateId, type TemplateFormat } from '@/services/templates'
import { formatBytes } from '@/lib/utils'
import { DocumentStage } from '@/features/document-preview/DocumentStage'
import { Button } from '@/components/ui/button'
import { Field, Input } from '@/components/ui/input'
import { FilterTag } from '@/components/ui/tag'
import { Panel } from '@/components/ui/table'
import { PageBody, PageHeading } from '@/components/common'
import { IngestionProgressPanel } from '@/features/ingestion/IngestionProgress'
import { useIngestionJob } from '@/features/ingestion/useIngestionJob'
import { UploadIcon } from '@/components/icons'

const CATEGORIES = CATS.filter((c) => c !== 'All')
const ACCEPTED_EXTENSIONS = ['.docx', '.xlsx', '.pptx']

const FMT_BY_FORMAT: Record<TemplateFormat, Fmt> = {
  docx: 'DOC',
  xlsx: 'XLS',
  pptx: 'PPT',
}

function formatFromFileName(name: string): TemplateFormat | null {
  const ext = name.slice(name.lastIndexOf('.')).toLowerCase()
  return ext === '.docx' || ext === '.xlsx' || ext === '.pptx' ? (ext.slice(1) as TemplateFormat) : null
}

/**
 * Laid out as the viewer is — details rail on the left, the document itself
 * filling the right — and rendered through the same `DocumentStage`, so what
 * you check before submitting is literally the same picture you get back from
 * `/viewer/:id` afterwards.
 *
 * Nothing on the left is usable until a file is chosen: naming and filing a
 * submission that doesn't exist yet has no meaning, and leaving the fields live
 * invites filling them in and then losing them to a file pick.
 */
export function Upload() {
  const navigate = useNavigate()
  const { addUpload } = useHub()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [name, setName] = useState('')
  const [category, setCategory] = useState(CATEGORIES[0])
  const [file, setFile] = useState<File | null>(null)
  const [submitting, setSubmitting] = useState(false)
  /* Kept after the upload returns so the job can be watched in place. The 202
     is the start of the work, not the end of it: detection and the model pass
     take up to a minute, and without this the page would claim success while
     the template was still unusable. */
  const [tracking, setTracking] = useState<{ templateId: string; jobId: string } | null>(null)
  const [error, setError] = useState<string | null>(null)

  const ingestion = useIngestionJob(tracking?.templateId ?? null, tracking?.jobId ?? null)
  const format = file ? formatFromFileName(file.name) : null
  const ready = Boolean(file && format)

  const pickFile = (e: ChangeEvent<HTMLInputElement>) => {
    const picked = e.target.files?.[0] ?? null
    setFile(picked)
    setError(picked && !formatFromFileName(picked.name) ? 'Only .docx, .xlsx and .pptx files can be uploaded.' : null)
    if (picked && !name) setName(picked.name.replace(/\.[^.]+$/, ''))
  }

  const loadPickedFileBytes = useCallback(() => {
    if (!file) return Promise.reject(new Error('No file selected.'))
    return file.arrayBuffer()
  }, [file])

  const submit = async () => {
    if (!file) return
    setSubmitting(true)
    setError(null)
    try {
      /* 202 with a job id — the file is stored and region detection is queued.
         The template row exists by then, so read it back for the real title,
         format and size rather than describing the row from the picked file. */
      const accepted = await uploadTemplate(file)
      const templateId = uploadedTemplateId(accepted)
      if ('job_id' in accepted) setTracking({ templateId, jobId: accepted.job_id })
      const stored = await getTemplate(templateId).catch(() => null)

      const storedFormat = stored?.format ?? format
      const fmt = storedFormat ? FMT_BY_FORMAT[storedFormat] : 'DOC'
      const size = stored?.current_version ? formatBytes(stored.current_version.size_bytes) : formatBytes(file.size)

      addUpload(
        name || stored?.title || file.name.replace(/\.[^.]+$/, ''),
        fmt,
        `.${storedFormat ?? 'file'} · ${size} · submitted just now`,
        templateId,
      )
    } catch (err) {
      setError(err instanceof TemplateApiError ? err.message : 'Something went wrong uploading that file.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <PageBody>
      <PageHeading
        title="Upload template"
        subtitle="Doc control reviews every submission before it appears in Discovery."
      />

      <div className="hub-results grid grid-cols-[340px_minmax(0,1fr)] gap-6 items-start">
        <Panel className="flex flex-col gap-4 min-w-0">
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPTED_EXTENSIONS.join(',')}
            className="hidden"
            onChange={pickFile}
          />
          <button
            type="button"
            className="border border-dashed border-divider rounded-[12px] py-7 px-4 flex flex-col items-center gap-[10px] cursor-pointer text-center bg-transparent font-[inherit]"
            onClick={() => fileInputRef.current?.click()}
          >
            <div className="w-11 h-11 rounded-pill bg-accent-100 text-accent-800 grid place-items-center">
              <UploadIcon width={18} height={18} />
            </div>
            <div className="text-[13.5px] font-semibold break-words min-w-0 max-w-full">
              {file?.name ?? 'Click to choose a file'}
            </div>
            <div className="text-[11.5px] opacity-55">
              {file ? `${formatBytes(file.size)} · click to replace` : '.docx, .xlsx or .pptx — up to 25 MB'}
            </div>
          </button>

          <Field label="Template name">
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Vendor Assessment Checklist"
              disabled={!ready}
            />
          </Field>

          <div>
            <div className="text-[12px] opacity-70 mb-[7px]">Category</div>
            <div className="flex gap-[9px] flex-wrap">
              {CATEGORIES.map((c) => (
                <FilterTag
                  key={c}
                  selected={category === c}
                  disabled={!ready}
                  onClick={() => setCategory(c)}
                >
                  {c}
                </FilterTag>
              ))}
            </div>
          </div>

          {error ? <p className="text-[13px] text-accent2-700 m-0">{error}</p> : null}

          <Button
            variant="primary"
            block
            className="mt-0 whitespace-nowrap"
            disabled={!ready || submitting || ingestion.active}
            onClick={submit}
          >
            {submitting ? 'Uploading…' : ingestion.active ? 'Processing…' : 'Submit for approval'}
          </Button>

          {/* The 202 is the start of the work. Showing the job here is what
              turns a silent 45 seconds into something a user can read. */}
          <IngestionProgressPanel progress={ingestion} />

          {tracking && !ingestion.active && (
            <Button
              variant="secondary"
              block
              className="whitespace-nowrap"
              onClick={() => navigate(`/templates/${tracking.templateId}`)}
            >
              Open template
            </Button>
          )}
        </Panel>

        {file && format ? (
          <DocumentStage
            /* Re-keyed per file so picking a different one tears the previous
               render down instead of leaving it on screen underneath. */
            key={`${file.name}:${file.size}:${file.lastModified}`}
            className="rounded-card overflow-hidden h-[calc(100vh-230px)] min-h-[420px]"
            bodyClassName="overflow-auto"
            format={format}
            fileName={file.name}
            title={name || file.name}
            meta={`${file.name} · ${formatBytes(file.size)} · not submitted yet`}
            loadBytes={loadPickedFileBytes}
          />
        ) : (
          <Panel className="min-w-0 h-[calc(100vh-230px)] min-h-[420px] grid place-items-center">
            <div className="text-center px-5">
              <div className="w-[72px] h-[72px] rounded-pill bg-accent2-100 mx-auto mb-[18px]" />
              <h4 className="mb-2">Nothing to preview yet</h4>
              <p className="opacity-65 text-[14px] max-w-[38ch] mx-auto m-0">
                {file
                  ? 'That file type can’t be previewed — choose a .docx, .xlsx or .pptx.'
                  : 'Choose a file and it will render here exactly as reviewers will see it.'}
              </p>
            </div>
          </Panel>
        )}
      </div>
    </PageBody>
  )
}
