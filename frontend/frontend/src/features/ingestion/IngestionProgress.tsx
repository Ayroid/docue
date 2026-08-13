import { stageLabel, type IngestionProgress } from './useIngestionJob'

/**
 * What the backend is doing with a file that has just been uploaded.
 *
 * The three states are not decoration — they map to genuinely different
 * outcomes, and collapsing them into "success/failure" would tell the user
 * something untrue:
 *
 * - **failed** — no region map, but the file is stored and downloadable.
 * - **indexed pending** — regions are ready and the template works; the model
 *   pass that makes it searchable hasn't produced a vector. Normal during the
 *   run, and the resting state if Bedrock was unavailable.
 * - **ready** — regions detected and searchable by meaning.
 */
export function IngestionProgressPanel({ progress }: { progress: IngestionProgress }) {
  const { job, active, failed, enrichmentPending, ready, error } = progress
  if (!job && !error) return null

  const percent = job?.progress ?? 0

  return (
    <div className="rounded-[12px] border border-divider p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3">
        <div className="text-[13.5px] font-semibold">
          {failed ? 'Region detection failed' : ready ? 'Ready' : stageLabel(job?.stage ?? null)}
        </div>
        <div className="text-[11.5px] opacity-55 tabular-nums">{percent}%</div>
      </div>

      <div className="h-[6px] rounded-pill bg-accent-100 overflow-hidden">
        <div
          className={`h-full rounded-pill transition-[width] duration-500 ${failed ? 'bg-red-500' : 'bg-accent-800'}`}
          style={{ width: `${failed ? 100 : percent}%` }}
        />
      </div>

      {active && (
        <p className="text-[11.5px] opacity-55 m-0">
          Detection takes a few seconds; describing and indexing the document takes up to a minute.
        </p>
      )}

      {job?.regions_detected != null && (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-1 m-0 text-[11.5px]">
          <dt className="opacity-55">Regions found</dt>
          <dd className="m-0 tabular-nums">
            {job.regions_detected}
            {job.regions_writable != null && ` (${job.regions_writable} writable)`}
          </dd>
          {job.form_id && (
            <>
              <dt className="opacity-55">Form ID</dt>
              <dd className="m-0">{job.form_id}</dd>
            </>
          )}
          {job.house_pattern_matched && (
            <>
              <dt className="opacity-55">House pattern</dt>
              <dd className="m-0">{job.house_pattern_matched}</dd>
            </>
          )}
          {job.in_doc_version && (
            <>
              <dt className="opacity-55">Version in document</dt>
              <dd className="m-0">{job.in_doc_version}</dd>
            </>
          )}
        </dl>
      )}

      {job?.enrichment && (
        <div className="flex flex-col gap-1 text-[11.5px]">
          <div className="opacity-55">
            {job.enrichment.regions_labelled} regions described
            {job.enrichment.regions_write_refused > 0 &&
              ` · ${job.enrichment.regions_write_refused} marked do-not-write`}
          </div>
          {job.enrichment.tags.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {job.enrichment.tags.slice(0, 8).map((tag) => (
                <span key={tag} className="rounded-pill bg-accent-100 text-accent-800 px-2 py-[2px]">
                  {tag}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Succeeded without an embedding is a normal resting state, not a
          failure: the model pass runs after the structural result is committed
          and is not allowed to fail it. */}
      {enrichmentPending && !active && (
        <p className="text-[11.5px] opacity-55 m-0">
          Saved with its region map. It isn’t searchable by meaning yet — the description step
          didn’t finish, which usually means the model service was unavailable.
        </p>
      )}

      {failed && (
        <p className="text-[11.5px] m-0 text-red-600">
          {job?.error ?? 'Detection failed.'} The file is stored and can still be downloaded.
        </p>
      )}

      {job?.warnings?.length ? (
        <ul className="m-0 pl-4 text-[11.5px] opacity-55">
          {job.warnings.slice(0, 4).map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      ) : null}

      {error && <p className="text-[11.5px] m-0 opacity-55">{error}</p>}
    </div>
  )
}
