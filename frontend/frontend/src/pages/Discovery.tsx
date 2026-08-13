import { useMemo, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { SEARCH_EXAMPLES } from '@/data/catalog'
import { useRealTemplates } from '@/features/document-library/useRealTemplates'
import { Icon } from '@/components/ui/icon'
import { EmptyState, PageBody } from '@/components/common'
import { RealTemplateCard } from '@/components/TemplateCard'

/**
 * The hub's front door: search first, then the library as cards.
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
      [...templates].sort(
        (a, b) =>
          new Date(b.current_version?.created_at ?? b.created_at).getTime() -
          new Date(a.current_version?.created_at ?? a.created_at).getTime(),
      ),
    [templates],
  )

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
          <h1 className="text-headline-lg mb-2">What document are you looking for?</h1>
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

      {/* ── Documents curated for you ───────────────────────────────────── */}
      <section className="flex flex-col gap-5">
        <div className="min-w-0">
          <h2 className="text-headline-md text-ink m-0">Documents curated for you</h2>
          <p className="text-body-md text-neutral-700 m-0 mt-1">
            {loading
              ? 'Loading the library…'
              : error
                ? 'The library is unavailable right now.'
                : `Approved templates, newest first — ${curated.length} available.`}
          </p>
        </div>

        {loading ? (
          <div className="grid gap-5 grid-cols-[repeat(auto-fill,minmax(320px,1fr))]">
            {/* Skeletons at the card's own height so the grid doesn't jump
                when the real rows land. */}
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-[232px] rounded-card bg-neutral-200 border border-divider animate-pulse" />
            ))}
          </div>
        ) : error ? (
          <div className="bg-surface border border-divider rounded-card p-5 text-body-md text-[color:var(--md-error)]">
            {error}
          </div>
        ) : curated.length === 0 ? (
          <EmptyState
            title="The library is empty"
            body="Upload a .docx, .xlsx or .pptx and it will appear here for everyone to find."
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
