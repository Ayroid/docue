import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Tag } from '@/components/ui/tag'
import { SearchIcon } from '@/components/icons'
import { cn } from '@/lib/utils'

const STEPS = [
  {
    n: 1,
    tone: 'accent' as const,
    title: 'Ask in plain English',
    body: 'Semantic search understands "test script for a payment API" without you knowing the folder, the owner or the file name.',
  },
  {
    n: 2,
    tone: 'accent2' as const,
    title: 'Pick the approved version',
    body: 'Every template carries its version history and its owner, so the copy you open is the copy the organisation stands behind.',
  },
  {
    n: 3,
    tone: 'accent' as const,
    title: 'Answer few questions',
    body: 'The agent asks for the context it needs, fills the placeholders and hands back a ready Word, Excel or PowerPoint file.',
  },
]

const CATEGORIES = [
  { kicker: 'Functional', title: 'Minutes of Meeting', body: 'Client, internal and steering-committee formats.' },
  { kicker: 'Functional', title: 'Plans & proposals', body: 'Estimation sheets, SOWs and delivery plans.' },
  { kicker: 'Technical', title: 'Design documents', body: 'HLD, LLD, integration and architecture notes.' },
  { kicker: 'Technical', title: 'Test scripts & API specs', body: 'Test cases, UAT sign-off and API contracts.' },
]

const WHY_POINTS = [
  { title: 'One approved version, always', body: 'Version history per template, with the owner on record.' },
  { title: 'Discovery on day one', body: 'Natural-language search means new joiners find what they need without asking around.' },
  { title: 'Drafts, not blank pages', body: 'The agent fills placeholders from project context and exports to Word, Excel or PowerPoint.' },
]

const FOOTER_COLUMNS = [
  { heading: 'Product', links: [{ label: 'Template library', href: '#cats' }, { label: 'AI auto-fill', href: '#how' }, { label: 'Version history', href: '#how' }] },
  { heading: 'Resources', links: [{ label: 'New joiner guide', href: '#how' }, { label: 'Contribute a template', href: '#cats' }, { label: 'Governance policy', href: '#why' }] },
  { heading: 'Support', links: [{ label: 'Help centre', href: '#why' }, { label: 'Contact an admin', href: '#why' }] },
]

export function Landing() {
  const navigate = useNavigate()
  const goLogin = () => navigate('/login')

  return (
    <div className="animate-hubfade">
      <header className="flex items-center gap-6 py-5 px-[clamp(20px,5vw,72px)] max-w-[1440px] mx-auto flex-wrap">
        <div className="flex items-center gap-[10px] mr-auto">
          <div className="w-8 h-8 rounded-pill bg-accent grid place-items-center text-bg font-heading text-[15px]">T</div>
          <span className="font-heading text-[18px]">YMSLI Template Hub</span>
        </div>
        <nav className="flex gap-[22px] text-[14px] flex-wrap">
          <a href="#how" className="text-ink opacity-70">How it works</a>
          <a href="#cats" className="text-ink opacity-70">Templates</a>
          <a href="#why" className="text-ink opacity-70">Why it matters</a>
        </nav>
        <Button variant="primary" className="whitespace-nowrap" onClick={goLogin}>
          Get started
        </Button>
      </header>

      <section className="max-w-[1440px] mx-auto px-[clamp(20px,5vw,72px)] pt-[clamp(32px,6vw,72px)]">
        <div className="max-w-[720px] text-center mx-auto">
          <Tag variant="accent2">One approved source for every document</Tag>
          <h1 className="text-[clamp(38px,5.6vw,64px)] leading-[1.05] my-[18px]">
            Every template. One shelf. Filled in for you.
          </h1>
          <div className="flex gap-3 flex-wrap justify-center mt-[30px]">
            <Button variant="primary" size="lg" className="whitespace-nowrap" onClick={goLogin}>
              Get started
            </Button>
          </div>

          <div className="relative w-full max-w-[560px] mx-auto mt-[clamp(36px,5vw,56px)]">
            <div className="absolute -right-[7%] -top-[11%] w-[min(250px,58%)] aspect-square rounded-pill bg-accent-200 opacity-60" />
            <div className="absolute -left-[6%] -bottom-[9%] w-[112px] aspect-square rounded-pill bg-accent2-200 opacity-75" />
            <div className="elev-lg relative bg-neutral-100 rounded-card p-[18px] flex flex-col gap-3 text-center">
              <div className="flex items-center justify-center gap-[9px] bg-bg border border-divider rounded-[10px] py-[10px] px-[15px] text-[13.5px] opacity-85">
                <SearchIcon width={15} height={15} />
                <span className="whitespace-nowrap overflow-hidden text-ellipsis">
                  MOM template for a client kickoff call
                </span>
              </div>
              <div className="flex items-center gap-[11px] bg-surface rounded-[12px] py-3 px-[15px] text-left">
                <div className="w-8 h-8 flex-none rounded-pill bg-accent-200 grid place-items-center text-[9.5px] font-heading text-accent-800">
                  DOC
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-[13.5px] font-semibold">Minutes of Meeting — Client</div>
                  <div className="text-[11.5px] opacity-55">v4.2 · Delivery PMO · used 214 times</div>
                </div>
                <Tag variant="accent2" className="whitespace-nowrap">
                  Approved
                </Tag>
              </div>
              <div className="bg-accent-100 rounded-[12px] py-[15px] px-4">
                <div className="text-[10.5px] tracking-[.1em] uppercase text-accent-700 mb-[7px]">
                  AI auto-fill · question 1 of 4
                </div>
                <div className="text-[14.5px] leading-[1.5]">
                  Which client and project is this for, and who attended?
                </div>
                <div className="flex gap-2 mt-3 flex-wrap justify-center">
                  <Tag variant="neutral" className="whitespace-nowrap">
                    18 placeholders
                  </Tag>
                  <Tag variant="outline" className="whitespace-nowrap">
                    Outputs .docx
                  </Tag>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="how" className="max-w-[1440px] mx-auto px-[clamp(20px,5vw,72px)] pt-[clamp(64px,9vw,118px)]">
        <h2 className="text-[clamp(28px,3.6vw,40px)] mb-[14px] text-center">
          Three steps to a finished document
        </h2>
        <p className="max-w-[56ch] opacity-70 mx-auto mb-11 text-center">
          The hub replaces the SharePoint hunt, the forwarded email and the personal copy that quietly drifted out
          of date.
        </p>
        <div className="grid gap-[30px] grid-cols-[repeat(auto-fit,minmax(258px,1fr))]">
          {STEPS.map((s) => (
            <div key={s.n} className="flex flex-col gap-[14px] items-center text-center">
              <div
                className={cn(
                  'w-16 h-16 rounded-pill grid place-items-center font-heading text-[24px]',
                  s.tone === 'accent' ? 'bg-accent-200 text-accent-800' : 'bg-accent2-200 text-accent2-800',
                )}
              >
                {s.n}
              </div>
              <h4 className="m-0">{s.title}</h4>
              <p className="text-[14.5px] opacity-70 m-0 text-pretty">{s.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section id="cats" className="max-w-[1440px] mx-auto px-[clamp(20px,5vw,72px)] pt-[clamp(64px,9vw,110px)]">
        <h2 className="text-[clamp(28px,3.6vw,40px)] text-center mb-[30px]">What's inside</h2>
        <div className="grid gap-5 grid-cols-[repeat(auto-fit,minmax(210px,1fr))]">
          {CATEGORIES.map((c) => (
            <div key={c.title} className="card elev-sm text-center items-center">
              <span className="card-kicker">{c.kicker}</span>
              <div className="card-title">{c.title}</div>
              <p className="card-body">{c.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section id="why" className="max-w-[1440px] mx-auto px-[clamp(20px,5vw,72px)] pt-[clamp(64px,9vw,110px)]">
        <div className="bg-accent2-900 text-neutral-100 rounded-[16px] p-[clamp(30px,5vw,58px)] grid grid-cols-[repeat(auto-fit,minmax(280px,1fr))] gap-[clamp(28px,4vw,56px)]">
          <div>
            <h2 className="text-[clamp(26px,3.2vw,36px)] mb-4 text-neutral-100 text-center">
              The problem it removes
            </h2>
            <p className="opacity-80 mx-auto max-w-[44ch] text-pretty text-center">
              Dozens of reusable templates sit scattered across SharePoint, laptops and email. New joiners take
              weeks to discover them, and experienced consultants keep personal copies that drift from the
              approved version.
            </p>
          </div>
          <div className="flex flex-col gap-5">
            {WHY_POINTS.map((p) => (
              <div key={p.title} className="flex gap-[14px] items-start">
                <div className="w-[10px] h-[10px] rounded-pill bg-accent-400 mt-[7px] flex-none" />
                <div>
                  <div className="font-semibold">{p.title}</div>
                  <div className="text-[14px] opacity-70">{p.body}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="max-w-[1440px] mx-auto px-[clamp(20px,5vw,72px)] pt-[clamp(64px,9vw,110px)] pb-[clamp(64px,9vw,110px)] text-center">
        <h2 className="text-[clamp(30px,4.4vw,52px)] mx-auto mb-[18px] max-w-[18ch]">
          Your next document is already half written.
        </h2>
        <Button variant="primary" size="lg" className="whitespace-nowrap" onClick={goLogin}>
          Get started
        </Button>
      </section>

      <footer className="max-w-[1440px] mx-auto px-[clamp(20px,5vw,72px)] pt-[clamp(56px,7vw,96px)] pb-12 grid gap-8 grid-cols-[repeat(auto-fit,minmax(180px,1fr))] text-center justify-items-center">
        <div>
          <div className="flex items-center gap-[10px] mb-[10px] justify-center">
            <div className="w-7 h-7 rounded-pill bg-accent grid place-items-center text-bg font-heading text-[13px]">
              T
            </div>
            <span className="font-heading text-[16px]">YMSLI Template Hub</span>
          </div>
          <div className="text-[13px] opacity-55">AI Hackathon 2026 · PS-08</div>
        </div>
        {FOOTER_COLUMNS.map((col) => (
          <div key={col.heading} className="flex flex-col gap-[9px] text-[14px] items-center">
            <div className="font-semibold mb-[2px]">{col.heading}</div>
            {col.links.map((l) => (
              <a key={l.label} href={l.href} className="opacity-70 text-ink">
                {l.label}
              </a>
            ))}
          </div>
        ))}
      </footer>
    </div>
  )
}
