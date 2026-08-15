import { useCallback, useEffect, useRef, useState, type ChangeEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { CATS, type Fmt } from '@/data/catalog'
import { useHub } from '@/store/HubProvider'
import { useAuth } from '@/store/AuthProvider'
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
import { Icon } from '@/components/ui/icon'
import { useBlockStrayFileDrops, useFileDrop } from '@/features/upload/useFileDrop'
import { cn } from '@/lib/utils'

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
  /* `?template=` turns this page into "upload the next version of that
     template" — the file half of the Update template choice. */
  const [searchParams] = useSearchParams()
  const updatingTemplateId = searchParams.get('template')
  const { addUpload, fireToast } = useHub()
  const { isAdmin } = useAuth()
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

  /* Which upload has already been announced. A ref rather than state because
     the effect below must not re-run when it changes -- and comparing the id
     rather than holding a boolean is what lets a second upload in the same
     visit announce itself instead of being swallowed by the first one's flag. */
  const announcedFor = useRef<string | null>(null)

  /**
   * Say so once the template is actually in the library.
   *
   * Fired on the job settling rather than on the 202, because the 202 only
   * means the bytes are stored -- claiming publication there would be a
   * promise the page cannot yet keep. Admins only: for everyone else the
   * upload is genuinely not published, it is queued, and the approval dialog
   * already says so.
   *
   * `failed` is excluded. A failed job still leaves a downloadable template in
   * the library, so the claim would be defensible -- but the progress panel is
   * showing an error at that moment and a success toast beside it reads as the
   * page contradicting itself.
   */
  useEffect(() => {
    if (!isAdmin || !tracking) return
    if (announcedFor.current === tracking.templateId) return
    if (!ingestion.ready && !ingestion.enrichmentPending) return

    announcedFor.current = tracking.templateId
    fireToast(
      ingestion.ready
        ? 'Published to the library'
        : 'Published to the library — search indexing is still catching up',
    )
  }, [isAdmin, tracking, ingestion.ready, ingestion.enrichmentPending, fireToast])

  /* One acceptance path for both ways in — clicking the zone and dropping on
     it. A dropped file has to clear exactly the same bar as a picked one, and
     duplicating the check is how the two drift apart. */
  const acceptFile = useCallback(
    (picked: File | null) => {
      setFile(picked)
      setError(
        picked && !formatFromFileName(picked.name)
          ? 'Only .docx, .xlsx and .pptx files can be uploaded.'
          : null,
      )
      /* Only seeds an empty field: re-picking must not overwrite a name that
         has been typed by hand. */
      if (picked) setName((current) => current || picked.name.replace(/\.[^.]+$/, ''))
    },
    [],
  )

  const pickFile = (e: ChangeEvent<HTMLInputElement>) => {
    acceptFile(e.target.files?.[0] ?? null)
    /* Clear the input's own value so choosing the *same* file again still
       fires `change` — without this, re-picking after a failed upload is
       silently ignored. */
    e.target.value = ''
  }

  /* Two zones, two flags: the dashed picker on the left and the empty preview
     panel on the right, which is the largest thing on screen and the one a
     file is most likely aimed at. */
  const zoneDrop = useFileDrop(acceptFile)
  const previewDrop = useFileDrop(acceptFile)
  useBlockStrayFileDrops()

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
      const accepted = await uploadTemplate(file, updatingTemplateId ?? undefined)
      const templateId = uploadedTemplateId(accepted)
      if ('job_id' in accepted) setTracking({ templateId, jobId: accepted.job_id })
      const stored = await getTemplate(templateId).catch(() => null)

      const storedFormat = stored?.format ?? format
      const fmt = storedFormat ? FMT_BY_FORMAT[storedFormat] : 'DOC'
      const size = stored?.current_version ? formatBytes(stored.current_version.size_bytes) : formatBytes(file.size)

      /* The confirmation dialog says admins have been notified and the
         template waits on an admin's decision. For an admin's own upload none
         of that is true -- the API approves it on arrival and mails nobody --
         so it would describe a queue the file never entered. The ingestion
         panel and the "Open template" button below are the confirmation
         instead, and they are accurate for both roles. */
      if (!isAdmin) {
        addUpload(
          name || stored?.title || file.name.replace(/\.[^.]+$/, ''),
          fmt,
          `.${storedFormat ?? 'file'} · ${size} · submitted just now`,
        )
      }
    } catch (err) {
      setError(err instanceof TemplateApiError ? err.message : 'Something went wrong uploading that file.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <PageBody>
      {/* An admin's upload is approved by the API on arrival, so promising them
          a review would describe a step that does not happen and leave them
          waiting on a queue their own file never enters. */}
      <PageHeading
        title={updatingTemplateId ? 'Upload a new version' : 'Upload template'}
        subtitle={
          // A *new version* is pending for everyone, admins included: the API
          // auto-approves an admin's new template, not their replacement of an
          // existing one. Telling an admin their version skips review would
          // describe a step that does not happen to it.
          updatingTemplateId
            ? 'This replaces the template once doc control approves it. Until then the library keeps serving the current version.'
            : isAdmin
              ? 'Your uploads are published straight to the library — no review step.'
              : 'An admin reviews every submission before it appears in Discovery.'
        }
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
            className={cn(
              'border-2 border-dashed rounded-card py-8 px-4 flex flex-col items-center gap-3 cursor-pointer text-center font-[inherit] transition-colors',
              zoneDrop.dragging
                ? 'border-accent bg-accent-100 border-solid'
                : 'border-divider bg-neutral-200/50 hover:border-accent hover:bg-accent-100/40',
            )}
            onClick={() => fileInputRef.current?.click()}
            {...zoneDrop.dropProps}
          >
            <div
              className={cn(
                'w-12 h-12 rounded-lg grid place-items-center transition-colors',
                zoneDrop.dragging ? 'bg-accent text-white' : 'bg-accent-100 text-accent',
              )}
            >
              <UploadIcon width={18} height={18} />
            </div>
            <div className="text-body-md font-semibold break-words min-w-0 max-w-full">
              {zoneDrop.dragging ? 'Drop it here' : (file?.name ?? 'Drop a file here, or click to choose')}
            </div>
            <div className="text-label-md text-neutral-600">
              {zoneDrop.dragging
                ? 'Release to load it'
                : file
                  ? `${formatBytes(file.size)} · drop or click to replace`
                  : '.docx, .xlsx or .pptx — up to 25 MB'}
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
            <div className="text-label-md uppercase text-neutral-600 mb-2">Category</div>
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

          {error ? <p className="text-body-md text-[color:var(--md-error)] m-0">{error}</p> : null}

          <Button
            variant="primary"
            block
            className="mt-0 whitespace-nowrap"
            disabled={!ready || submitting || ingestion.active}
            onClick={submit}
          >
            {submitting
              ? 'Uploading…'
              : ingestion.active
                ? 'Processing…'
                : isAdmin
                  ? 'Publish'
                  : 'Submit for approval'}
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
            meta={`${file.name} · ${formatBytes(file.size)} · ${isAdmin ? 'not published yet' : 'not submitted yet'}`}
            loadBytes={loadPickedFileBytes}
          />
        ) : (
          /* Also a drop target. It is by far the largest thing on screen and it
             is where the eye already is, so a dragged file gets aimed at it
             whatever the small dashed zone on the left says. */
          <Panel
            className={cn(
              'min-w-0 h-[calc(100vh-230px)] min-h-[420px] grid place-items-center transition-colors',
              previewDrop.dragging && 'border-accent border-2 border-dashed bg-accent-100/50',
            )}
            {...previewDrop.dropProps}
          >
            <div className="text-center px-5 pointer-events-none">
              <div
                className={cn(
                  'w-[72px] h-[72px] rounded-pill mx-auto mb-5 grid place-items-center transition-colors',
                  previewDrop.dragging ? 'bg-accent text-white' : 'bg-neutral-200 text-neutral-500',
                )}
              >
                <Icon name="upload_file" size={30} />
              </div>
              <h4 className="mb-2 text-title-lg">
                {previewDrop.dragging ? 'Drop it here' : 'Nothing to preview yet'}
              </h4>
              <p className="text-neutral-700 text-body-md max-w-[42ch] mx-auto m-0">
                {previewDrop.dragging
                  ? 'Release to load it.'
                  : file
                    ? 'That file type can’t be previewed — choose a .docx, .xlsx or .pptx.'
                    : 'Drop a file here, or choose one on the left, and it will render exactly as reviewers will see it.'}
              </p>
            </div>
          </Panel>
        )}
      </div>
    </PageBody>
  )
}
