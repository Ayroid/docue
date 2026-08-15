import { useNavigate } from 'react-router-dom'
import { EmptyState, PageBody, PageHeading } from '@/components/common'

/**
 * Every number this page used to show was invented: the stat tiles, the
 * generation trend line (two hardcoded SVG paths that changed shape when you
 * switched the date range but described nothing), the "search queries with no
 * good match" table, stale and never-used template lists, and per-stage
 * generation latency.
 *
 * Nothing is instrumented yet — the backend records no usage, searches or
 * timings — so there is no honest chart to draw.
 */
export function Analytics() {
  const navigate = useNavigate()

  return (
    <PageBody>
      <PageHeading title="Analytics" subtitle="Adoption, generation cost and where the library is thin." />

      <EmptyState
        title="No usage data yet"
        body="Nothing in the hub is instrumented, so there are no adoption, search or cost figures to report. This page fills in once the server starts recording usage."
        action={{ label: 'Browse the library', onClick: () => navigate('/discovery') }}
      />
    </PageBody>
  )
}
