import { PREVIEW_LINES } from '@/data/mock'
import { Tag } from '@/components/ui/tag'
import { PreviewLines } from '@/components/common'
import type { LivePreview } from './useLivePreview'
import type { ParsedDocument } from './types'

const LEGEND = [
  { label: 'Typed', className: 'whitespace-nowrap' },
  { label: 'Derived', className: 'whitespace-nowrap border border-dashed border-accent bg-transparent' },
  {
    label: 'AI-drafted',
    className: 'whitespace-nowrap border border-dashed border-accent bg-accent-100 text-accent-900',
  },
  { label: 'Unchanged', className: 'whitespace-nowrap opacity-45' },
]

/**
 * The right-hand pane of the fill conversation.
 *
 * What you see first is the **structural** preview: an HTML table built from
 * the parsed regions of the in-memory working copy, with regions the last
 * answer touched pulsing on `hubglow`. It renders on the same tick the answer
 * lands, so there is no spinner between typing and seeing the document change.
 *
 * The pixel-accurate LibreOffice render arrives a second or two later and takes
 * over the body area below the fields. Until it does — and whenever a newer
 * answer has superseded it — the skeleton stands in, and the status chip says
 * which of the two the user is looking at.
 */
export function LivePreviewPanel({
  original,
  preview,
  title,
  subtitle,
  answersCaptured,
  totalQuestions,
}: {
  original: ParsedDocument
  preview: LivePreview
  title: string
  subtitle: string
  answersCaptured: number
  totalQuestions: number
}) {
  const { working, render, renderStatus, renderStale, fastPathMs } = preview

  /* Branding and other protected regions are shown on the detail page's region
     map, not here — this pane is about what the conversation is changing. */
  const fields = working.regions.filter((r) => r.kind !== 'branding' && r.regionId !== 'doc.confidentiality')

  const renderLabel =
    renderStatus === 'rendering' || renderStale
      ? 'Rendering exact layout…'
      : renderStatus === 'ready'
        ? `Exact layout · rendered in ${render?.renderedInMs}ms`
        : renderStatus === 'failed'
          ? 'Exact render unavailable — showing structure'
          : 'Structure only'

  const showAccurateRender = renderStatus === 'ready' && !renderStale

  return (
    <div className="bg-neutral-100 rounded-card py-[26px] px-7 flex flex-col">
      <div className="flex items-center gap-2 mb-[14px] flex-wrap">
        <Tag variant="accent" className="whitespace-nowrap">
          Live preview
        </Tag>
        <span className="text-[11.5px] opacity-50">
          {Math.min(answersCaptured, totalQuestions)} of {totalQuestions} answers captured
        </span>
        <div className="flex gap-[7px] flex-wrap ml-auto">
          {LEGEND.map((l) => (
            <Tag key={l.label} variant="neutral" className={l.className}>
              {l.label}
            </Tag>
          ))}
        </div>
      </div>

      <div className="font-heading text-[20px] leading-[1.2] mb-[3px]">{title}</div>
      <div className="text-[11.5px] opacity-55 mb-5">{subtitle}</div>

      {/* ── Fast path: structural preview from the parsed regions ─────────── */}
      <table className="w-full border-collapse">
        <tbody>
          {fields.map((region) => {
            const empty = !region.content
            const dashed = region.provenance === 'derived' || region.provenance === 'ai'
            return (
              <tr
                key={region.regionId}
                className={`border-b border-divider ${region.changed ? 'animate-hubglow' : ''}`}
              >
                <th className="w-[120px] text-left align-top font-normal text-[12px] opacity-55 py-[9px] px-2">
                  {region.label}
                </th>
                <td className="py-[9px] px-2">
                  <div className="flex items-center gap-2 flex-wrap">
                    <div
                      className={`text-[13.5px] py-[2px] px-[6px] rounded-[6px] ${
                        empty ? 'opacity-35' : 'text-ink'
                      } ${dashed ? 'border border-dashed border-accent' : ''}`}
                    >
                      {region.content || 'Waiting for your answer'}
                    </div>
                    {region.provenance === 'ai' && !empty ? (
                      <Tag variant="accent" className="whitespace-nowrap">
                        AI-drafted
                      </Tag>
                    ) : null}
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>

      {/* ── Accurate path: swapped in when the render lands ───────────────── */}
      <div className="mt-[22px] flex items-center gap-2">
        <span className="text-[11px] opacity-45">{renderLabel}</span>
        {renderStatus === 'rendering' || renderStale ? (
          <span className="w-[10px] h-[10px] rounded-pill bg-accent-300 animate-pulse" />
        ) : null}
        <span className="ml-auto text-[11px] opacity-30">structure in {fastPathMs.toFixed(0)}ms</span>
      </div>

      <div className="mt-[9px] flex flex-col gap-[9px]">
        {showAccurateRender ? (
          <img
            src={render!.pngUrl}
            alt={`Rendered preview of ${original.title}`}
            className="w-full rounded-[8px] bg-neutral-200"
            /* The simulated renderer returns a `render://` URL with no bytes
               behind it. Falling back to the skeleton keeps the swap visible
               without shipping a broken image. */
            onError={(e) => {
              e.currentTarget.style.display = 'none'
            }}
          />
        ) : null}
        <PreviewLines lines={PREVIEW_LINES.slice(0, 6)} flat />
      </div>
    </div>
  )
}
