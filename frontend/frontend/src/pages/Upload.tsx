import { useRef, useState, type ChangeEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { CATS, type Fmt } from '@/data/mock'
import { useHub } from '@/store/HubProvider'
import { TemplateApiError, uploadTemplate, type TemplateFormat } from '@/services/templates'
import { formatBytes } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Field, Input } from '@/components/ui/input'
import { FilterTag } from '@/components/ui/tag'
import { Panel } from '@/components/ui/table'
import { PageBody, PageHeading } from '@/components/common'
import { UploadIcon } from '@/components/icons'

const CATEGORIES = CATS.filter((c) => c !== 'All')
const ACCEPTED_EXTENSIONS = ['.docx', '.xlsx', '.pptx']

const FMT_BY_FORMAT: Record<TemplateFormat, Fmt> = {
  docx: 'DOC',
  xlsx: 'XLS',
  pptx: 'PPT',
}

export function Upload() {
  const navigate = useNavigate()
  const { addUpload } = useHub()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [name, setName] = useState('')
  const [category, setCategory] = useState(CATEGORIES[0])
  const [file, setFile] = useState<File | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const pickFile = (e: ChangeEvent<HTMLInputElement>) => {
    const picked = e.target.files?.[0] ?? null
    setFile(picked)
    setError(null)
    if (picked && !name) setName(picked.name.replace(/\.[^.]+$/, ''))
  }

  const submit = async () => {
    if (!file) return
    setSubmitting(true)
    setError(null)
    try {
      const template = await uploadTemplate(file)
      const fmt = FMT_BY_FORMAT[template.format] ?? 'DOC'
      const size = template.current_version ? formatBytes(template.current_version.size_bytes) : 'unknown size'
      addUpload(name || template.title, fmt, `.${template.format} · ${size} · submitted just now`, template.id)
      navigate('/admin')
    } catch (err) {
      setError(err instanceof TemplateApiError ? err.message : 'Something went wrong uploading that file.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <PageBody className="max-w-[640px] mx-auto">
      <PageHeading center title="Upload template" subtitle="Doc control reviews every submission before it appears in Discovery." />

      <Panel className="flex flex-col gap-4">
        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPTED_EXTENSIONS.join(',')}
          className="hidden"
          onChange={pickFile}
        />
        <button
          type="button"
          className="border border-dashed border-divider rounded-[12px] py-9 px-5 flex flex-col items-center gap-[10px] cursor-pointer text-center bg-transparent font-[inherit]"
          onClick={() => fileInputRef.current?.click()}
        >
          <div className="w-11 h-11 rounded-pill bg-accent-100 text-accent-800 grid place-items-center">
            <UploadIcon width={18} height={18} />
          </div>
          <div className="text-[13.5px] font-semibold">{file?.name ?? 'Click to choose a file, or drag it here'}</div>
          <div className="text-[11.5px] opacity-55">.docx, .xlsx or .pptx — up to 25 MB</div>
        </button>

        <Field label="Template name">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Vendor Assessment Checklist" />
        </Field>

        <div>
          <div className="text-[12px] opacity-70 mb-[7px]">Category</div>
          <div className="flex gap-[9px] flex-wrap">
            {CATEGORIES.map((c) => (
              <FilterTag key={c} selected={category === c} onClick={() => setCategory(c)}>
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
          disabled={!file || submitting}
          onClick={submit}
        >
          {submitting ? 'Uploading…' : 'Submit for approval'}
        </Button>
      </Panel>
    </PageBody>
  )
}
