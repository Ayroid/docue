import { useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useHub } from '@/store/HubProvider'
import { NOTIFICATIONS, QUEUE } from '@/data/mock'
import { extOf } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { Avatar, FormatChip } from '@/components/common'
import {
  AnalyticsIcon,
  ApprovalsIcon,
  BellIcon,
  CheckIcon,
  DocsIcon,
  LibraryIcon,
  LogoutIcon,
  SettingsIcon,
  SidebarIcon,
  UploadIcon,
} from '@/components/icons'

/**
 * The signed-in shell: sticky sidebar, sticky header, and the two pieces of
 * global chrome the prototype hangs off the app root — the download toast and
 * the "sent for approval" dialog.
 */
export function AppShell() {
  const {
    sidebarOpen,
    toggleSidebar,
    role,
    templates,
    documents,
    drafts,
    uploads,
    toast,
    uploadDialogOpen,
    closeUploadDialog,
    lastUpload,
    logout,
  } = useHub()
  const navigate = useNavigate()
  const location = useLocation()
  const [notifsOpen, setNotifsOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)

  const signOut = () => {
    setSettingsOpen(false)
    logout()
    navigate('/')
  }

  const publishedCount = templates.length - 12
  const navItems = [
    { to: '/discovery', label: 'Discovery', icon: <LibraryIcon />, badge: String(128 + publishedCount) },
    { to: '/documents', label: 'My documents', icon: <DocsIcon />, badge: String(documents.length + drafts.length) },
    { to: '/analytics', label: 'Analytics', icon: <AnalyticsIcon />, badge: '' },
    ...(role === 'Admin'
      ? [
          {
            to: '/admin',
            label: 'Admin',
            icon: <ApprovalsIcon />,
            badge: String(uploads.length + QUEUE.filter((x) => x.kind === 'In process').length),
          },
        ]
      : []),
  ]

  /* Discovery owns the search, template detail, generate and review routes —
     they all read as "browsing the library" in the sidebar. */
  const isDiscoveryBranch =
    location.pathname === '/discovery' ||
    location.pathname.startsWith('/search') ||
    location.pathname.startsWith('/templates') ||
    location.pathname.startsWith('/generate')

  const currentNav = isDiscoveryBranch
    ? '/discovery'
    : navItems.find((i) => location.pathname.startsWith(i.to) && i.to !== '/discovery')?.to

  return (
    <div className="flex min-h-screen items-stretch">
      {sidebarOpen ? (
        <aside className="w-[250px] flex-none bg-surface py-5 px-4 flex flex-col gap-[6px] sticky top-0 h-screen">
          <Button
            className="flex items-center gap-[10px] justify-start py-[6px] px-2 mb-[14px]"
            onClick={() => navigate('/')}
          >
            <div className="w-[30px] h-[30px] rounded-pill bg-accent grid place-items-center text-bg font-heading text-[14px]">
              T
            </div>
            <span className="font-heading text-[15px]">Template Hub</span>
          </Button>

          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className="hub-nav"
              aria-current={currentNav === item.to ? 'page' : undefined}
              onClick={() => setNotifsOpen(false)}
            >
              <span className="flex w-[18px] h-[18px] flex-none">{item.icon}</span>
              <span className="flex-1">{item.label}</span>
              <span className="text-[11px] opacity-55">{item.badge}</span>
            </NavLink>
          ))}

          <div className="mt-auto pt-4">
            <Button
              variant="primary"
              className="justify-start gap-[9px] py-[10px] px-[14px] w-full"
              onClick={() => navigate('/upload')}
            >
              <UploadIcon width={16} height={16} />
              Upload template
            </Button>
          </div>

          <div className="pt-4 border-t border-divider flex items-center gap-[10px] relative">
            <Avatar initials="RM" />
            <div className="flex-1 min-w-0">
              <div className="text-[13.5px] font-semibold truncate">Riya Mehta</div>
              <div className="text-[11.5px] opacity-55">
                {role === 'Admin' ? 'Delivery · Doc control admin' : 'Delivery · Consultant'}
              </div>
            </div>
            <Button
              variant="bare"
              size="icon"
              title="Settings"
              onClick={() => setSettingsOpen((v) => !v)}
            >
              <SettingsIcon width={17} height={17} />
            </Button>

            {settingsOpen ? (
              <div className="elev-lg absolute bottom-[46px] right-0 w-[180px] bg-neutral-100 rounded-[12px] p-[6px] z-20">
                <button
                  type="button"
                  className="hub-nav"
                  onClick={signOut}
                >
                  <span className="flex w-[18px] h-[18px] flex-none">
                    <LogoutIcon width={17} height={17} />
                  </span>
                  <span className="flex-1 text-left">Log out</span>
                </button>
              </div>
            ) : null}
          </div>
        </aside>
      ) : null}

      <main className="flex-1 min-w-0 flex flex-col">
        <header className="flex items-center gap-4 py-[18px] px-[clamp(18px,3vw,36px)] sticky top-0 bg-bg z-[5]">
          <Button
            variant="secondary"
            size="icon"
            className="flex-none"
            title={sidebarOpen ? 'Hide sidebar' : 'Show sidebar'}
            onClick={toggleSidebar}
          >
            <SidebarIcon width={17} height={17} />
          </Button>

          <div className="ml-auto flex items-center gap-[10px] relative">
            <Button
              variant="secondary"
              size="icon"
              title="Notifications"
              onClick={() => setNotifsOpen((v) => !v)}
            >
              <BellIcon width={17} height={17} />
            </Button>
            <span className="absolute left-[24px] top-[2px] w-[9px] h-[9px] rounded-pill bg-accent border-2 border-bg" />
            <Avatar initials="RM" />

            {notifsOpen ? (
              <div className="elev-lg absolute top-[46px] right-0 w-[340px] bg-neutral-100 rounded-[12px] p-[14px] z-20">
                <div className="flex items-baseline justify-between mb-2 px-[6px]">
                  <span className="font-heading text-[15px]">Notifications</span>
                  <span className="text-[11.5px] opacity-55">5 new</span>
                </div>
                {NOTIFICATIONS.map((n) => (
                  <div key={n.text} className="flex gap-[11px] p-[10px] rounded-[10px]">
                    <div className="w-2 h-2 rounded-pill bg-accent mt-[6px] flex-none" />
                    <div className="flex-1 min-w-0">
                      <div className="text-[13.5px] leading-[1.4]">{n.text}</div>
                      <div className="text-[11.5px] opacity-50 mt-[2px]">{n.time}</div>
                    </div>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </header>

        <Outlet />
      </main>

      {toast ? (
        <div className="fixed right-6 bottom-6 z-30 flex items-center gap-[11px] bg-accent-100 text-accent-900 rounded-[12px] py-[13px] px-4 shadow-elev-lg animate-hubfade">
          <CheckIcon width={17} height={17} />
          <span className="text-[13.5px]">{toast}</span>
        </div>
      ) : null}

      <Dialog open={uploadDialogOpen} onOpenChange={closeUploadDialog} title="Sent for approval"
        actions={
          <Button variant="primary" onClick={closeUploadDialog}>
            Done
          </Button>
        }
      >
        <div className="dialog-body">
          <div className="flex items-center gap-3 bg-surface rounded-[12px] py-[13px] px-[15px] mb-4">
            <FormatChip size={34}>{lastUpload?.fmt ?? 'DOC'}</FormatChip>
            <div className="flex-1 min-w-0">
              <div className="text-[13.5px] font-semibold truncate">
                {lastUpload ? `${lastUpload.name}${extOf(lastUpload.fmt)}` : 'Vendor Assessment Checklist.docx'}
              </div>
              <div className="text-[11.5px] opacity-55">{lastUpload?.meta ?? '148 KB · uploaded just now'}</div>
            </div>
          </div>
          Doc control has been notified by email and in the hub. Once an admin approves it, the template is
          published to Discovery for everyone.
        </div>
      </Dialog>
    </div>
  )
}
