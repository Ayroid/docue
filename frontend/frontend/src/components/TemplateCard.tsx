import { useNavigate } from 'react-router-dom'
import type { TemplateOut } from '@/services/templates'
import { Button } from '@/components/ui/button'
import { statusClass } from '@/data/catalog'


/**
 * A card for one real `GET /templates` row.
 *
 * Laid out as the design system's template card: status tag in the corner,
 * icon tile, title and subtitle, a two-column fact grid, then an action row.
 *
 * The design's card shows an owner and a description. The API records
 * neither, so those slots carry facts the server does hold — format and file
 * size — rather than inventing the ones it doesn't.
 */
export function RealTemplateCard({ template }: { template: TemplateOut }) {
  const navigate = useNavigate()
  const version = template.current_version

  /* Date only — the time of day was never what distinguishes one template
     from another, and it is what forced the timestamp onto its own row. */
  const updated = new Date(version?.created_at ?? template.created_at).toLocaleDateString(undefined, {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })

  return (
    <article className="hub-tcard relative">
      <span className={`${statusClass(template.status)} absolute top-4 right-4 uppercase`}>{template.status}</span>

      {/* Two lines are reserved whether or not the title needs them, so the
          facts below line up across every card in a row. */}
      <div className="min-w-0 pr-20">
        <h3 className="text-title-lg text-ink m-0 line-clamp-2 min-h-14" title={template.title}>
          {template.title}
        </h3>
      </div>

      {/* One meta line instead of a labelled fact grid: format and version on
          the left, the date it last changed on the right. `mt-auto` moved here
          from the action row so the pair stays anchored to the card's foot. */}
      <div className="mt-auto flex items-center justify-between gap-3 text-label-md text-neutral-600">
        <span className="inline-flex items-center gap-2 min-w-0">
          <span className="uppercase">{template.format}</span>
          <span className="text-neutral-400" aria-hidden="true">
            |
          </span>
          <span>v{version?.version_number ?? 1}</span>
        </span>
        <span className="truncate">{updated}</span>
      </div>

      <div className="flex items-center gap-2 border-t border-divider pt-4">
        <button
          type="button"
          className="bg-transparent border-0 p-0 cursor-pointer font-[inherit] text-body-md text-accent hover:underline"
          onClick={() => navigate(`/templates/${template.id}`)}
        >
          Details
        </button>

        {/* No viewer shortcut here: Details carries the "open the file" link,
            so the card's action row stays a single, unambiguous next step. */}
        <Button
          variant="primary"
          size="sm"
          className="ml-auto whitespace-nowrap"
          onClick={() => navigate(`/templates/${template.id}/generate`)}
        >
          Use template
        </Button>
      </div>
    </article>
  )
}
