import { useCallback, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { TemplateApiError, type TemplateOut } from '@/services/templates'
import { saveTemplateToDisk } from '@/features/document-library/saveToDisk'
import { ShareDialog } from '@/features/access/ShareDialog'
import { useAuth } from '@/store/AuthProvider'
import { useHub } from '@/store/HubProvider'
import { formatBytes } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/ui/icon'
import { Tag } from '@/components/ui/tag'
import { CHIP_BY_FORMAT, FormatChip } from '@/components/common'

/**
 * The pill marks an *exception*, so there is deliberately no 'approved' entry.
 *
 * Everything the library lists is approved by construction, so an "Approved"
 * badge on every card carried no information and took the corner the title
 * wants. Pending and rejected are the two states worth flagging — and they are
 * only ever visible to the submitter looking at their own upload, or to an
 * admin.
 *
 * Keyed on `approval_status` rather than `status`: `status` is free text whose
 * values are lowercase, so the old `statusClass()` — comparing against
 * 'Approved'/'Final'/'Published' — matched none of them.
 *
 * Typed on `string`, not the union: the column behind it is an unconstrained
 * `str`, and a value neither this file nor the API contract knows about should
 * fall through to no pill rather than take the whole grid down.
 */
const APPROVAL_PILL: Record<string, { className: string; label: string } | undefined> = {
  pending: { className: 'pill pill-warn', label: 'Pending' },
  rejected: { className: 'pill pill-bad', label: 'Rejected' },
}

/** Four chips is where the row wraps at the narrowest card width. */
const MAX_TAGS = 3

/**
 * One real `GET /templates` row, as a card.
 *
 * Shared by Discovery and the Templates page so a template looks the same
 * wherever it is met. Two actions carry the two things anyone comes here to
 * do — **Use document** starts a generation session, **View** opens the file
 * full-page — with download and details demoted to icon buttons so the pair
 * stays unambiguous.
 *
 * The description, tags and category are the backend's enrichment fields.
 * They are null for the ~45s after an upload and stay null if the model was
 * unavailable, so every one of them renders as absent rather than as an error.
 */
export function RealTemplateCard({ template }: { template: TemplateOut }) {
  const navigate = useNavigate()
  const { fireToast } = useHub()
  const { isAdmin } = useAuth()
  const [shareOpen, setShareOpen] = useState(false)
  const version = template.current_version
  const pill = APPROVAL_PILL[template.approval_status]
  const restricted = template.visibility === 'restricted'

  /* Date only — the time of day was never what distinguishes one template
     from another, and it is what forced the timestamp onto its own row. */
  const updated = new Date(version?.created_at ?? template.created_at).toLocaleDateString(undefined, {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  })

  const extraTags = Math.max(0, template.tags.length - MAX_TAGS)

  const handleDownload = useCallback(async () => {
    try {
      await saveTemplateToDisk(template)
      fireToast(`Downloaded ${template.original_filename}`)
    } catch (err) {
      fireToast(err instanceof TemplateApiError ? err.message : 'Could not download this file.')
    }
  }, [template, fireToast])

  return (
    <article
      className="hub-tcard"
      /* Right-click is the SharePoint muscle memory this was asked for, and it
         is deliberately *not* the only way in — the kebab in the action row
         opens the same dialog, because a right-click-only affordance is
         invisible to anyone who does not already expect it and unreachable on
         a touch screen. The browser's own menu is left alone for everyone who
         cannot act on it, so non-admins keep copy/paste on a card. */
      onContextMenu={
        isAdmin
          ? (event) => {
              event.preventDefault()
              setShareOpen(true)
            }
          : undefined
      }
    >
      <div className="flex items-start gap-3">
        <FormatChip size={40}>{CHIP_BY_FORMAT[template.format]}</FormatChip>

        {/* Two lines are reserved whether or not the title needs them, so the
            description below lines up across every card in a row. */}
        <div className="min-w-0 flex-1">
          <h3 className="text-title-lg text-ink m-0 line-clamp-2 min-h-14" title={template.title}>
            {template.title}
          </h3>
          <p className="text-label-md text-neutral-600 m-0 truncate" title={template.original_filename}>
            {template.form_id ?? template.original_filename}
          </p>
        </div>

        {pill ? <span className={`${pill.className} flex-none uppercase`}>{pill.label}</span> : null}
      </div>

      {/* The enrichment pass writes this. Absent is a normal state, not a
          failure, so it says so plainly instead of leaving a blank gap that
          reads as a broken card. */}
      <p
        className={`text-body-md m-0 line-clamp-2 min-h-10 ${
          template.purpose ? 'text-neutral-700' : 'text-neutral-500 italic'
        }`}
        title={template.purpose ?? undefined}
      >
        {template.purpose ?? 'No description yet.'}
      </p>

      <div className="flex flex-wrap items-center gap-1.5 min-h-6">
        {/* Shown to everyone who can see the card, not just admins. A user who
            has been given access to a restricted document should know it is
            restricted — that it reached them is the exception, not the rule,
            and it tells them not to forward it. */}
        {restricted ? (
          <Tag
            variant="outline"
            className="text-[11px] py-[2px] px-[8px]"
            title="Only chosen people, the owner and admins can see this template."
          >
            Restricted
          </Tag>
        ) : null}
        {template.category ? (
          <Tag variant="accent" className="text-[11px] py-[2px] px-[8px]">
            {template.category}
          </Tag>
        ) : null}
        {template.tags.slice(0, MAX_TAGS).map((tag) => (
          <Tag key={tag} variant="accent2" className="text-[11px] py-[2px] px-[8px]">
            {tag}
          </Tag>
        ))}
        {extraTags ? (
          <Tag variant="outline" className="text-[11px] py-[2px] px-[8px]" title={template.tags.join(', ')}>
            +{extraTags}
          </Tag>
        ) : null}
        {/* Not an error either: embedding runs after the file is stored, so a
            just-uploaded template is downloadable before it is findable. */}
        {!template.searchable ? (
          <Tag
            variant="outline"
            className="text-[11px] py-[2px] px-[8px]"
            title="Not yet embedded — it will not appear in semantic search results until it is."
          >
            Indexing
          </Tag>
        ) : null}
      </div>

      {/* `mt-auto` anchors the facts and the actions to the card's foot, so a
          short title and a long one still produce the same card. */}
      <div className="mt-auto flex items-center justify-between gap-3 border-t border-divider pt-3 text-label-md text-neutral-600">
        <span className="inline-flex items-center gap-2 min-w-0">
          <span className="uppercase">{template.format}</span>
          <span className="text-neutral-400" aria-hidden="true">
            |
          </span>
          <span>v{version?.version_number ?? 1}</span>
          {version ? (
            <>
              <span className="text-neutral-400" aria-hidden="true">
                |
              </span>
              <span className="whitespace-nowrap">{formatBytes(version.size_bytes)}</span>
            </>
          ) : null}
        </span>
        <span className="truncate">{updated}</span>
      </div>

      <div className="flex items-center gap-2">
        <Button
          variant="primary"
          size="sm"
          className="flex-1 whitespace-nowrap"
          onClick={() => navigate(`/templates/${template.id}/generate`)}
        >
          <Icon name="edit_document" size={16} />
          Use document
        </Button>
        {/* The detail page, not `/viewer`: it opens the file *and* everything
            recorded about it, which is what someone checking a template before
            using it actually wants. It carries its own "Open full page" link
            for the bare-document reading. The separate info button that used to
            sit in this row went to the same place, so it was a second control
            for one destination. */}
        <Button
          variant="secondary"
          size="sm"
          className="flex-1 whitespace-nowrap"
          onClick={() => navigate(`/templates/${template.id}`)}
        >
          <Icon name="visibility" size={16} />
          View
        </Button>
        <Button
          variant="bare"
          size="icon"
          className="w-9 h-9 flex-none text-neutral-600 hover:bg-neutral-200"
          title={`Download ${template.original_filename}`}
          aria-label={`Download ${template.original_filename}`}
          onClick={handleDownload}
        >
          <Icon name="download" size={18} />
        </Button>
        {/* The discoverable half of the pair. Right-clicking the card opens the
            same dialog for the same people — this exists because a
            right-click-only affordance is invisible to anyone who does not
            already expect it, and unreachable on a touch screen. */}
        {isAdmin ? (
          <Button
            variant="bare"
            size="icon"
            className="w-9 h-9 flex-none text-neutral-600 hover:bg-neutral-200"
            title={`Manage access for ${template.title}`}
            aria-label={`Manage access for ${template.title}`}
            onClick={() => setShareOpen(true)}
          >
            <Icon name="more_vert" size={18} />
          </Button>
        ) : null}
      </div>

      {/* Mounted only for admins, and only once opened does it fetch: the
          dialog loads the access list on `open`, so a grid of twenty cards
          costs twenty *nothing*s rather than twenty requests. */}
      {isAdmin ? (
        <ShareDialog
          templateId={template.id}
          templateTitle={template.title}
          open={shareOpen}
          onOpenChange={setShareOpen}
        />
      ) : null}
    </article>
  )
}
