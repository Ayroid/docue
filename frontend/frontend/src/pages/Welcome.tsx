import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { PageBody, PageHeading } from '@/components/common'
import { AnalyticsIcon, ApprovalsIcon, LibraryIcon } from '@/components/icons'

const CARDS = [
  { to: '/', label: 'Discovery', body: 'Search the library and generate a document.', icon: <LibraryIcon /> },
  { to: '/admin', label: 'Admin', body: 'Review submissions and manage access.', icon: <ApprovalsIcon /> },
  { to: '/analytics', label: 'Analytics', body: 'See adoption, cost and library gaps.', icon: <AnalyticsIcon /> },
]

export function Welcome() {
  const navigate = useNavigate()

  return (
    <PageBody className="max-w-[720px] mx-auto text-center">
      <div className="w-14 h-14 rounded-pill bg-accent grid place-items-center text-bg font-heading text-[22px] mx-auto mb-4">
        T
      </div>
      <PageHeading center title="Welcome to Template Hub" subtitle="Every YMSLI document template, in one searchable, governed place." />

      <div className="grid gap-[14px] grid-cols-[repeat(auto-fit,minmax(190px,1fr))] mt-7">
        {CARDS.map((c) => (
          <button
            key={c.to}
            type="button"
            className="hub-tcard items-center text-center cursor-pointer border-0 font-[inherit]"
            onClick={() => navigate(c.to)}
          >
            <div className="w-10 h-10 rounded-pill bg-accent-100 text-accent-800 grid place-items-center mx-auto">
              {c.icon}
            </div>
            <div className="font-heading text-[15px]">{c.label}</div>
            <p className="text-[12.5px] opacity-65 m-0">{c.body}</p>
          </button>
        ))}
      </div>

      <Button variant="primary" className="mt-8 whitespace-nowrap" onClick={() => navigate('/')}>
        Get started
      </Button>
    </PageBody>
  )
}
