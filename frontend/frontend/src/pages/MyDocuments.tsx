import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { DOC_FILTERS, statusClass } from '@/data/mock'
import { useHub } from '@/store/HubProvider'
import { Button } from '@/components/ui/button'
import { FilterTag } from '@/components/ui/tag'
import { Table, TableCard } from '@/components/ui/table'
import { EmptyState, FormatChip, PageBody, PageHeading } from '@/components/common'
import { DownloadIcon } from '@/components/icons'

export function MyDocuments() {
  const { documents, drafts, fireToast } = useHub()
  const navigate = useNavigate()
  const [filter, setFilter] = useState('All')

  const filtered = useMemo(
    () =>
      documents.filter((d) => {
        if (filter === 'All') return true
        if (filter === 'Draft' || filter === 'Approved') return d.status === filter
        return d.kind === filter
      }),
    [documents, filter],
  )

  return (
    <PageBody>
      <PageHeading title="My documents" subtitle={`${documents.length} generated · ${drafts.length} in-progress drafts`} />

      <div className="flex gap-[9px] flex-wrap mb-[22px]">
        {DOC_FILTERS.map((f) => (
          <FilterTag key={f} selected={filter === f} onClick={() => setFilter(f)}>
            {f}
          </FilterTag>
        ))}
      </div>

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

      <h4 className="mb-[14px]">Generated documents</h4>
      {filtered.length ? (
        <TableCard>
          <Table className="hub-mydocs">
            <thead>
              <tr>
                <th>Document</th>
                <th>Template</th>
                <th>Size</th>
                <th>Created</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {filtered.map((d) => (
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
                  <td className="opacity-75">{d.template} · v{d.version}</td>
                  <td className="opacity-75 whitespace-nowrap">{d.size}</td>
                  <td className="opacity-75 whitespace-nowrap">{d.created}</td>
                  <td>
                    <span className={statusClass(d.status)}>{d.status}</span>
                  </td>
                  <td>
                    <div className="flex gap-2 justify-end flex-wrap">
                      <Button
                        variant="ghost"
                        size="xs"
                        className="gap-[6px] whitespace-nowrap"
                        onClick={() => fireToast(`Downloaded ${d.name}${d.ext}`)}
                      >
                        <DownloadIcon width={13} height={13} />
                        Download
                      </Button>
                      <Button variant="secondary" size="xs" className="whitespace-nowrap" onClick={() => navigate(`/documents/${d.id}`)}>
                        Open
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        </TableCard>
      ) : (
        <EmptyState
          title="No documents yet"
          body="Generate your first document from a template in Discovery."
          action={{ label: 'Go to Discovery', onClick: () => navigate('/discovery') }}
        />
      )}
    </PageBody>
  )
}
