import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { getTemplate, TemplateApiError, type TemplateOut } from '@/services/templates'
import { Button } from '@/components/ui/button'
import { EmptyState, PageBody, PageHeading } from '@/components/common'
import { Icon } from '@/components/ui/icon'

/**
 * The fork between the two ways to revise a template.
 *
 * It is a page rather than a menu because the two routes are not variations on
 * one action — one uploads a file somebody edited in Excel, the other opens a
 * conversation. Putting them behind a dropdown would make a real decision look
 * like a setting.
 *
 * Both end in the same place: a `pending` version in doc control's queue. The
 * copy says so on both cards, because "update the template" reads like an
 * immediate change and it is not one.
 */
export function UpdateTemplate() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [template, setTemplate] = useState<TemplateOut | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!id) return
    let cancelled = false
    getTemplate(id)
      .then((t) => {
        if (!cancelled) setTemplate(t)
      })
      .catch((err: unknown) => {
        if (!cancelled)
          setError(err instanceof TemplateApiError ? err.message : 'Could not open that template.')
      })
    return () => {
      cancelled = true
    }
  }, [id])

  if (error || !id) {
    return (
      <PageBody>
        <EmptyState
          title="Template not found"
          body={error ?? 'No template was named.'}
          action={{ label: 'Back to Discovery', onClick: () => navigate('/discovery') }}
        />
      </PageBody>
    )
  }

  const current = template?.current_version?.version_number

  return (
    <PageBody>
      <Button
        variant="ghost"
        className="py-1 px-2 mb-[6px] whitespace-nowrap"
        onClick={() => navigate(`/templates/${id}`)}
      >
        Back to the template
      </Button>

      <PageHeading
        title="Update this template"
        subtitle={
          template
            ? `${template.title}${current ? ` — currently v${current}` : ''}. Whichever route you pick, the result goes to doc control for approval before it replaces the current version.`
            : 'Loading…'
        }
      />

      <div className="grid gap-5 grid-cols-[repeat(auto-fit,minmax(300px,1fr))]">
        <ChoiceCard
          icon="upload_file"
          title="Upload a file"
          body="You have already edited the template — in Excel, Word or PowerPoint — and want that file to become the next version."
          note="Must be the same file type as the template."
          action="Choose a file"
          onClick={() => navigate(`/upload?template=${id}`)}
        />
        <ChoiceCard
          icon="forum"
          title="Revise with the assistant"
          body="Work through the template with the assistant and let it apply your changes. Every edit is shown with where it came from before anything is saved."
          note="Best for changing wording and content, not layout."
          action="Start a conversation"
          onClick={() => navigate(`/templates/${id}/generate?mode=template`)}
        />
      </div>
    </PageBody>
  )
}

function ChoiceCard({
  icon,
  title,
  body,
  note,
  action,
  onClick,
}: {
  icon: string
  title: string
  body: string
  note: string
  action: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="text-left bg-surface border border-divider rounded-card p-6 flex flex-col gap-4 min-h-[260px] cursor-pointer transition-shadow hover:shadow-elev-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
    >
      <span className="w-12 h-12 rounded-card bg-accent-100 text-accent-700 grid place-items-center flex-none">
        <Icon name={icon} size={26} />
      </span>

      <div className="flex-1 min-w-0">
        <h3 className="text-title-lg m-0 mb-2">{title}</h3>
        <p className="text-body-md text-neutral-700 m-0">{body}</p>
      </div>

      <p className="text-label-md text-neutral-600 m-0">{note}</p>

      <span className="text-body-md font-semibold text-accent-700 inline-flex items-center gap-1">
        {action}
        <Icon name="arrow_forward" size={18} />
      </span>
    </button>
  )
}
