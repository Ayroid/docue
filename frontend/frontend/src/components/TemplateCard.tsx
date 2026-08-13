import { useNavigate } from 'react-router-dom'
import type { Template } from '@/data/mock'
import { Button } from '@/components/ui/button'
import { Tag } from '@/components/ui/tag'
import { FormatChip } from '@/components/common'
import { GenerateIcon } from '@/components/icons'

/**
 * The Discovery card. `meta` differs between the two rails the prototype
 * renders — "Most used" leads with the usage count, "Recently updated" leads
 * with the version — so the caller supplies it.
 */
export function TemplateCard({ template, meta }: { template: Template; meta: 'uses' | 'version' }) {
  const navigate = useNavigate()

  const metaParts =
    meta === 'uses'
      ? [`${template.uses} uses`, template.updated, template.category]
      : [`v${template.version}`, `Updated ${template.updated}`, template.category]

  return (
    <div className="hub-tcard">
      <div className="flex items-start gap-3">
        <FormatChip size={40}>{template.fmt}</FormatChip>
        <div className="flex-1 min-w-0">
          <div className="font-heading text-[16.5px] leading-[1.25]">{template.name}</div>
          <div className="text-[12px] opacity-60 mt-[3px]">{template.owner}</div>
        </div>
        <Tag variant="accent2" className="flex-none">
          v{template.version}
        </Tag>
      </div>

      <p className="text-[13px] opacity-75 m-0 [text-wrap:pretty]">{template.desc}</p>

      <div className="flex items-center gap-2 flex-wrap text-[11.5px] opacity-55">
        {metaParts.map((part, i) => (
          <span key={part} className="contents">
            {i > 0 ? <span>·</span> : null}
            <span className="whitespace-nowrap">{part}</span>
          </span>
        ))}
      </div>

      <div className="flex gap-2 flex-wrap mt-[2px]">
        <Button
          variant="primary"
          size="sm"
          className="gap-[7px] whitespace-nowrap"
          onClick={() => navigate(`/templates/${template.id}/generate`)}
        >
          <GenerateIcon width={14} height={14} />
          Generate
        </Button>
        <Button variant="secondary" size="sm" onClick={() => navigate(`/templates/${template.id}`)}>
          View
        </Button>
        <Button variant="ghost" size="sm" onClick={() => navigate(`/templates/${template.id}`)}>
          v{template.version} history
        </Button>
      </div>
    </div>
  )
}
