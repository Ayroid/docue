import { useNavigate } from 'react-router-dom'
import type { TemplateOut } from '@/services/templates'
import { formatBytes } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Tag } from '@/components/ui/tag'
import { CHIP_BY_FORMAT, FormatChip } from '@/components/common'
import { GenerateIcon } from '@/components/icons'

/**
 * A card for one real `GET /templates` row.
 *
 * Every field shown here comes off the record the server returned — title,
 * filename, format, size, upload date, version. The prototype's second card
 * component, which rendered invented owners, usage counts, categories and
 * one-line descriptions, is gone along with the seed data behind it.
 */
export function RealTemplateCard({ template }: { template: TemplateOut }) {
  const navigate = useNavigate()
  const version = template.current_version

  const metaParts = [
    version ? formatBytes(version.size_bytes) : 'size unknown',
    version ? `Uploaded ${new Date(version.created_at).toLocaleDateString()}` : 'Upload date unknown',
    template.status,
  ]

  return (
    <div className="hub-tcard">
      <div className="flex items-start gap-3">
        <FormatChip size={40}>{CHIP_BY_FORMAT[template.format]}</FormatChip>
        <div className="flex-1 min-w-0">
          <div className="font-heading text-[16.5px] leading-[1.25] truncate">{template.title}</div>
          <div className="text-[12px] opacity-60 mt-[3px] truncate">{template.original_filename}</div>
        </div>
        <Tag variant="accent2" className="flex-none">
          v{version?.version_number ?? 1}
        </Tag>
      </div>

      <div className="flex items-center gap-2 flex-wrap text-[11.5px] opacity-55">
        {metaParts.map((part, i) => (
          <span key={part} className="contents">
            {i > 0 ? <span>·</span> : null}
            <span className="whitespace-nowrap">{part}</span>
          </span>
        ))}
      </div>

      <div className="flex gap-2 flex-wrap mt-[2px]">
        {/* Starts the scripted generation walkthrough from this document. */}
        <Button
          variant="primary"
          size="sm"
          className="gap-[7px] whitespace-nowrap"
          onClick={() => navigate(`/templates/${template.id}/generate`)}
        >
          <GenerateIcon width={14} height={14} />
          Generate
        </Button>
        {/* Opens the real file on a page of its own, in a new tab. A genuine
            anchor rather than `window.open` so middle-click and ctrl-click do
            what the user expects and no popup blocker gets involved. */}
        <Button asChild variant="secondary" size="sm">
          <a href={`/viewer/${template.id}`} target="_blank" rel="noopener noreferrer">
            View
          </a>
        </Button>
        <Button variant="ghost" size="sm" onClick={() => navigate(`/templates/${template.id}`)}>
          Details
        </Button>
      </div>
    </div>
  )
}
