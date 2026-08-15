import { useMemo, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { SEARCH_EXAMPLES } from '@/data/catalog'
import { useRealTemplates } from '@/features/document-library/useRealTemplates'
import { Button } from '@/components/ui/button'
import { Icon } from '@/components/ui/icon'
import { SkeletonGroup, TemplateCardSkeleton } from '@/components/ui/skeleton'
import { EmptyState, PageBody } from '@/components/common'
import { RealTemplateCard } from '@/components/TemplateCard'

/** A front door shows a sample, not an inventory — the full set is one click
    away on the Templates page. */
const CURATED_LIMIT = 5

/**
 * The hub's front door: search first, then a handful of templates as cards.
 *
 * "Curated for you" is ordered newest-first. The API records no usage, no
 * owner and no per-person history, so there is no personal signal to rank on —
 * recency is the only honest ordering available, and the section is presented
 * as a starting point rather than a claim about relevance.
 */
export function Discovery() {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')

  const { templates, loading, error } = useRealTemplates()

  const curated = useMemo(
    () =>
      [...templates]
        .sort(
          (a, b) =>
            new Date(b.current_version?.created_at ?? b.created_at).getTime() -
            new Date(a.current_version?.created_at ?? a.created_at).getTime(),
        )
        .slice(0, CURATED_LIMIT),
    [templates],
  )

  /* The count comes from `templates`, not from the sliced `curated` — the
     section says how big the library is, and reading it off the capped list
     would report "5 available" however many there really are. */
  const total = templates.length
  const capped = total > CURATED_LIMIT

  const submit = (e: FormEvent) => {
    e.preventDefault()
    navigate(`/search?q=${encodeURIComponent(query)}`)
  }

  return (
    <PageBody>
      {/* ── Hero search ─────────────────────────────────────────────────── */}
      <section className="relative overflow-hidden rounded-card bg-accent2-900 text-white px-6 py-14 sm:px-10 sm:py-16 shadow-elev-lg flex flex-col items-center text-center gap-7">
        <div className="pointer-events-none absolute -top-32 -left-32 w-64 h-64 rounded-pill bg-accent opacity-20 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-32 -right-32 w-64 h-64 rounded-pill bg-accent-400 opacity-10 blur-3xl" />

        <div className="relative z-10 max-w-2xl">
          <h1 className="text-headline-lg mb-2">What template are you looking for?</h1>
          <p className="text-body-lg text-white/80 m-0">
            Search across approved YMSLI templates using natural language.
          </p>
        </div>

        <form onSubmit={submit} className="relative z-10 w-full max-w-3xl flex flex-col gap-4">
          <div className="relative flex items-center">
            <Icon name="search" size={20} className="absolute left-4 text-neutral-500 pointer-events-none" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Try: MOM for a D365 workshop"
              aria-label="Search the library"
              className="w-full bg-white text-ink rounded-pill py-4 pl-12 pr-16 text-body-lg shadow-elev-md outline-none border border-transparent focus:border-accent placeholder:text-neutral-500"
            />
            <button
              type="submit"
              title="Search"
              className="absolute right-3 w-10 h-10 grid place-items-center rounded-pill bg-accent text-white border-0 cursor-pointer hover:bg-accent-500 transition-colors"
            >
              <Icon name="arrow_forward" size={20} />
            </button>
          </div>

          <div className="flex flex-wrap items-center justify-center gap-2">
            <span className="text-label-md uppercase text-white/60 mr-1">Suggestions:</span>
            {SEARCH_EXAMPLES.map((q) => (
              <button
                key={q}
                type="button"
                className="px-4 py-1.5 rounded-pill bg-white/10 hover:bg-white/20 text-body-md text-white border-0 cursor-pointer transition-colors whitespace-nowrap"
                onClick={() => setQuery(q)}
              >
                {q}
              </button>
            ))}
          </div>
        </form>
      </section>

      {/* ── Templates curated for you ───────────────────────────────────── */}
      <section className="flex flex-col gap-5">
        <div className="flex items-end gap-4 flex-wrap">
          <div className="min-w-0 flex-1">
            <h2 className="text-headline-md text-ink m-0">Templates curated for you</h2>
            <p className="text-body-md text-neutral-700 m-0 mt-1">
              {loading
                ? 'Loading the library…'
                : error
                  ? 'The library is unavailable right now.'
                  : capped
                    ? /* Say which few these are. "5 available" off a capped list
                         would under-report the library by however many it hides. */
                      `The ${CURATED_LIMIT} newest of ${total} approved templates.`
                    : `Approved templates, newest first — ${total} available.`}
            </p>
          </div>

          {/* The way to the rest of them. Without it the cap silently hides the
              library from anyone who takes this section as the whole of it. */}
          {!loading && !error && total > 0 ? (
            <Button variant="secondary" className="flex-none" onClick={() => navigate('/library')}>
              Browse all templates
              <Icon name="arrow_forward" size={18} />
            </Button>
          ) : null}
        </div>

        {loading ? (
          /* Exactly as many placeholders as the section can render, so the grid
             does not shrink the moment the real cards land. They carry the
             card's actual anatomy — title, description, tags, meta, actions —
             so the wait shows what is coming rather than only where it will go. */
          <SkeletonGroup
            label="Loading templates"
            className="grid gap-5 grid-cols-[repeat(auto-fill,minmax(320px,1fr))] items-stretch"
          >
            {Array.from({ length: CURATED_LIMIT }).map((_, i) => (
              <TemplateCardSkeleton key={i} />
            ))}
          </SkeletonGroup>
        ) : error ? (
          <div className="bg-surface border border-divider rounded-card p-5 text-body-md text-[color:var(--md-error)]">
            {error}
          </div>
        ) : curated.length === 0 ? (
          <EmptyState
            title="No templates yet"
            body="Upload a .docx, .xlsx or .pptx and it will appear here for everyone to find once an admin approves it."
            action={{ label: 'Upload a template', onClick: () => navigate('/upload') }}
          />
        ) : (
          <div className="grid gap-5 grid-cols-[repeat(auto-fill,minmax(320px,1fr))] items-stretch">
            {curated.map((t) => (
              <RealTemplateCard key={t.id} template={t} />
            ))}
          </div>
        )}
      </section>
    </PageBody>
  )
}
