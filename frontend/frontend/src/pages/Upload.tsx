import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { CATS } from '@/data/mock'
import { useHub } from '@/store/HubProvider'
import { Button } from '@/components/ui/button'
import { Field, Input } from '@/components/ui/input'
import { FilterTag } from '@/components/ui/tag'
import { Panel } from '@/components/ui/table'
import { PageBody, PageHeading } from '@/components/common'
import { UploadIcon } from '@/components/icons'

const CATEGORIES = CATS.filter((c) => c !== 'All')

export function Upload() {
  const navigate = useNavigate()
  const { addUpload } = useHub()
  const [name, setName] = useState('')
  const [category, setCategory] = useState(CATEGORIES[0])
  const [fileName, setFileName] = useState<string | null>(null)

  const submit = () => {
    addUpload()
    navigate('/admin')
  }

  return (
    <PageBody className="max-w-[640px] mx-auto">
      <PageHeading center title="Upload template" subtitle="Doc control reviews every submission before it appears in Discovery." />

      <Panel className="flex flex-col gap-4">
        <label
          className="border border-dashed border-divider rounded-[12px] py-9 px-5 flex flex-col items-center gap-[10px] cursor-pointer text-center"
          onClick={() => setFileName(fileName ?? 'Vendor Assessment Checklist.docx')}
        >
          <div className="w-11 h-11 rounded-pill bg-accent-100 text-accent-800 grid place-items-center">
            <UploadIcon width={18} height={18} />
          </div>
          <div className="text-[13.5px] font-semibold">{fileName ?? 'Click to choose a file, or drag it here'}</div>
          <div className="text-[11.5px] opacity-55">.docx, .xlsx or .pptx — up to 20 MB</div>
        </label>

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

        <Button variant="primary" block className="mt-0 whitespace-nowrap" disabled={!fileName} onClick={submit}>
          Submit for approval
        </Button>
      </Panel>
    </PageBody>
  )
}
