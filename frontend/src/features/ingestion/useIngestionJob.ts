import { useEffect, useRef, useState } from 'react'

import { getIngestionStatus, TemplateApiError, type JobStatus } from '@/services/templates'

/**
 * Poll one ingestion job until it settles.
 *
 * Upload answers 202 the moment the file is stored, and the real work happens
 * afterwards: structural detection first, then the AI pass that makes the
 * template searchable. Without polling, an upload looks like it either
 * finished instantly or hung — the user has no way to tell which.
 *
 * Two behaviours here follow from how the backend is built, not from taste:
 *
 * - **Stop on `succeeded` *or* `failed`.** A failed job still leaves a usable,
 *   downloadable template; the file and version row are committed before the
 *   job starts. So failure means "no region map", not "upload lost".
 * - **`enrichment: null` on a succeeded job is not an error.** Enrichment runs
 *   after the structural result is committed and cannot fail it, so the model
 *   being unavailable leaves a good template that simply is not searchable
 *   yet. `pending` below says exactly that.
 *
 * A transient fetch failure does not end the poll — the job keeps running on
 * the server regardless of whether we can reach it, so the poll retries and
 * only surfaces an error once the job itself reports one.
 */

const POLL_INTERVAL_MS = 1000
/* Structural work lands ~15s in; the enrich stage adds 15-60s on top (the BRD,
   at 61 regions, is the slow case). Two minutes is generous enough that a slow
   model call never looks like a stall. */
const TIMEOUT_MS = 120_000

export interface IngestionProgress {
  job: JobStatus | null
  /** Still working: queued or running. */
  active: boolean
  /** The job reported a failure. The template is still downloadable. */
  failed: boolean
  /** Succeeded, but the AI pass produced nothing — not searchable yet. */
  enrichmentPending: boolean
  /** Fully done: regions detected and the template is embedded. */
  ready: boolean
  error: string | null
}

const STAGE_LABELS: Record<string, string> = {
  fingerprint: 'Reading the file',
  detect: 'Finding regions',
  harvest: 'Reading the form details',
  verify: 'Checking region ids are stable',
  persist: 'Saving the region map',
  enrich: 'Describing and indexing it',
  done: 'Done',
}

export function stageLabel(stage: string | null): string {
  if (!stage) return 'Queued'
  return STAGE_LABELS[stage] ?? stage
}

export function useIngestionJob(templateId: string | null, jobId: string | null): IngestionProgress {
  const [job, setJob] = useState<JobStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const startedAt = useRef<number>(0)
  /* Whether there is a job to watch at all. Without this the hook cannot tell
     "nothing uploaded yet" from "uploaded, first poll still in flight" -- both
     leave `job` null -- and the caller ends up disabled on a job that does not
     exist. */
  const watching = Boolean(templateId && jobId)

  useEffect(() => {
    // Dropped on every id change so a second upload does not inherit the first
    // job's terminal status while its own first poll is still in flight.
    setJob(null)
    setError(null)
    if (!templateId || !jobId) return

    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    startedAt.current = Date.now()

    const tick = async () => {
      try {
        const next = await getIngestionStatus(templateId, jobId)
        if (cancelled) return
        setJob(next)
        setError(null)
        if (next.status === 'succeeded' || next.status === 'failed') return
      } catch (err) {
        if (cancelled) return
        /* Deliberately not fatal: the job runs server-side whether or not this
           request landed, so a blip should not freeze the UI on a stale stage. */
        if (err instanceof TemplateApiError && err.status === 404) {
          setError('That ingestion job could not be found.')
          return
        }
      }
      if (Date.now() - startedAt.current > TIMEOUT_MS) {
        setError('Still processing — this is taking longer than expected.')
        return
      }
      timer = setTimeout(tick, POLL_INTERVAL_MS)
    }

    void tick()
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [templateId, jobId])

  const status = job?.status ?? null
  return {
    job,
    // `status === null` still counts as active, but only while a job is being
    // watched: it is the gap between the 202 landing and the first poll
    // answering, and dropping it would flick the caller back to idle mid-run.
    active: watching && (status === null || status === 'queued' || status === 'running'),
    failed: status === 'failed',
    enrichmentPending: status === 'succeeded' && !job?.enrichment?.embedded,
    ready: status === 'succeeded' && Boolean(job?.enrichment?.embedded),
    error,
  }
}
