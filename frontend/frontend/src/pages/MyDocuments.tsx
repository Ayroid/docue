import { useNavigate } from 'react-router-dom'
import { statusClass } from '@/data/catalog'
import { useHub } from '@/store/HubProvider'
import { Button } from '@/components/ui/button'
import { Table, TableCard } from '@/components/ui/table'
import { DemoBadge, EmptyState, FormatChip, PageBody, PageHeading } from '@/components/common'

/**
 * Documents produced by the generation walkthrough, plus its saved drafts.
 *
 * Both lists start empty and only fill as someone runs the walkthrough — the
 * page used to open with seven invented documents that had never been
 * generated and no file behind them. Nothing here is stored on the server, so
 * a reload legitimately clears it.
 */
export function MyDocuments() {
  const { documents, drafts } = useHub()
  const navigate = useNavigate()

  if (!documents.length && !drafts.length) {
    return (
      <PageBody>
        <PageHeading title="My documents" subtitle="Documents you've generated from a template." />
        <EmptyState
          title="No generated documents yet"
          body="Pick a document in the library and choose Generate to walk through creating one. Note that generation is a demonstration — nothing is written to the server yet."
          action={{ label: 'Browse the library', onClick: () => navigate('/discovery') }}
        />
      </PageBody>
    )
  }

  return (
    <PageBody>
      <div className="flex items-start gap-3 flex-wrap mb-[22px]">
        <PageHeading
          title="My documents"
          subtitle={`${documents.length} generated · ${drafts.length} in-progress draft${drafts.length === 1 ? '' : 's'}`}
          className="mb-0"
        />
        <DemoBadge className="mt-[10px]" />
      </div>

      <p className="text-[12.5px] opacity-60 -mt-[10px] mb-[22px] max-w-[70ch]">
        Created by the generation walkthrough and held in this tab only — there is no generated-document service yet,
        so nothing here survives a reload.
      </p>

      {drafts.length ? (
        <div className="mb-9">
          <h4 className="mb-[14px]">Drafts</h4>
          <div className="flex flex-col gap-3">
            {drafts.map((d) => (
              <div key={d.id} className="bg-surface rounded-card py-4 px-[18px] flex items-center gap-4 flex-wrap">
                <FormatChip size={38}>{d.fmt}</FormatChip>
                <div className="flex-[1_1_200px] min-w-[170px]">
                  <div className="font-semibold">{d.title}</div>
                  <div className="text-[12px] opacity-55">{d.saved}</div>
                </div>
                <Button
                  variant="primary"
                  size="sm"
                  className="ml-auto whitespace-nowrap"
                  onClick={() => navigate(`/templates/${d.templateId}/generate?session=d${d.id}`)}
                >
                  Resume
                </Button>
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {documents.length ? (
        <>
          <h4 className="mb-[14px]">Generated documents</h4>
          <TableCard>
            <Table className="hub-mydocs">
              <thead>
                <tr>
                  <th>Document</th>
                  <th>Template</th>
                  <th>Created</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {documents.map((d) => (
                  <tr key={d.id}>
                    <td>
                      <div
                        className="flex items-center gap-[11px] cursor-pointer min-w-0"
                        onClick={() => navigate(`/documents/${d.id}`)}
                      >
                        <FormatChip size={30}>{d.fmt}</FormatChip>
                        <span className="font-semibold truncate">{d.name}</span>
                      </div>
                    </td>
                    <td className="opacity-75">
                      {d.template} · v{d.version}
                    </td>
                    <td className="opacity-75 whitespace-nowrap">{d.created}</td>
                    <td>
                      <span className={statusClass(d.status)}>{d.status}</span>
                    </td>
                    <td>
                      <div className="flex gap-2 justify-end flex-wrap">
                        <Button
                          variant="secondary"
                          size="xs"
                          className="whitespace-nowrap"
                          onClick={() => navigate(`/documents/${d.id}`)}
                        >
                          Open
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </TableCard>
        </>
      ) : null}
    </PageBody>
  )
}
