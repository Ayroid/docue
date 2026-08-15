import { useNavigate } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import { Tag } from '@/components/ui/tag'
import { CHIP_BY_FORMAT, FormatChip } from '@/components/common'
import type { SearchResult } from '@/services/templates'

import { Highlighted } from './highlight'

/**
 * One hit, with the reason it is a hit.
 *
 * `match_explanation` and the rank badges come from the backend's own fusion --
 * they are read off the two rankings, not written by a model, so they can be
 * shown verbatim without claiming something the retrieval did not do. That
 * distinction is the point of showing them at all: a plausible-sounding reason
 * generated after the fact would be worse than no reason.
 */
export function SearchResultCard({ result }: { result: SearchResult }) {
  const navigate = useNavigate()
  const { scores } = result

  return (
    <div className="bg-surface rounded-card p-[18px] flex flex-col gap-3">
      <div className="flex items-start gap-[11px] min-w-0">
        <FormatChip size={32}>{CHIP_BY_FORMAT[result.format]}</FormatChip>
        <div className="min-w-0 flex-1">
          <button
            type="button"
            className="font-semibold text-[15px] text-left bg-transparent border-0 p-0 font-[inherit] cursor-pointer text-ink truncate max-w-full"
            onClick={() => navigate(`/templates/${result.template_id}`)}
          >
            {result.title}
          </button>
          {result.form_id && <div className="text-[12px] opacity-55">{result.form_id}</div>}
        </div>
        <Button asChild variant="primary" size="xs" className="whitespace-nowrap">
          <a href={`/viewer/${result.template_id}`} target="_blank" rel="noopener noreferrer">
            View
          </a>
        </Button>
      </div>

      {result.purpose && <p className="m-0 text-[13px] opacity-80">{result.purpose}</p>}

      {result.highlights.length > 0 && (
        <div className="text-[12.5px] opacity-75 border-l-2 border-divider pl-3 flex flex-col gap-1">
          {result.highlights.map((fragment, index) => (
            <p key={index} className="m-0">
              <Highlighted fragment={fragment} />
            </p>
          ))}
        </div>
      )}

      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[11.5px] opacity-55">{result.match_explanation}</span>
        <span className="ml-auto flex items-center gap-[6px] text-[11px] opacity-55 tabular-nums">
          {scores.vector_rank != null && <Tag variant="accent2">meaning #{scores.vector_rank}</Tag>}
          {scores.bm25_rank != null && <Tag>keywords #{scores.bm25_rank}</Tag>}
        </span>
      </div>

      {result.tags.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {result.tags.slice(0, 8).map((tag) => (
            <span
              key={tag}
              className="text-[11px] rounded-pill bg-accent-100 text-accent-800 px-2 py-[2px]"
            >
              {tag}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
