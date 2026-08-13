import { useState } from 'react'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useHub } from '@/store/HubProvider'
import { useRealTemplates } from '@/features/document-library/useRealTemplates'
import { cn, extOf } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { Dialog } from '@/components/ui/dialog'
import { Icon } from '@/components/ui/icon'
import { Avatar, FormatChip } from '@/components/common'

/**
 * The signed-in shell: a fixed brand bar, a tab strip beneath it, and the two
 * pieces of global chrome the app hangs off its root — the toast and the "sent
 * for approval" dialog.
 *
 * No search field up here: Discovery's hero owns the search box, so a second
 * one in the chrome only duplicated it on every page.
 *
 * The design puts navigation across the top rather than down the side, so the
 * old sidebar's collapse toggle now drives a mobile nav drawer; `sidebarOpen`
 * and `toggleSidebar` keep their meaning.
 */
export function AppShell() {
  const { sidebarOpen, toggleSidebar, role, uploads, toast, uploadDialogOpen, closeUploadDialog, lastUpload, logout } =
    useHub()
  const navigate = useNavigate()
  const location = useLocation()
  const [settingsOpen, setSettingsOpen] = useState(false)

  /* The badge counts what the server actually holds. */
  const { templates, loading: templatesLoading } = useRealTemplates()

  const signOut = () => {
    setSettingsOpen(false)
    logout()
    navigate('/')
  }

  const navItems = [
    { to: '/discovery', label: 'Home', badge: '' },
    { to: '/library', label: 'Templates', badge: templatesLoading ? '' : String(templates.length) },
    /* No badge: there is no generated-document backend, so any number here
       would be invented. */
    { to: '/documents', label: 'My Documents', badge: '' },
    { to: '/analytics', label: 'Analytics', badge: 'SOON' },
    ...(role === 'Admin' ? [{ to: '/admin', label: 'Admin', badge: uploads.length ? String(uploads.length) : '' }] : []),
  ]

  /* Discovery owns the library, search, template detail, generate and review
     routes. `/library` has its own tab, so it is excluded here. */
  const isHomeBranch =
    location.pathname === '/discovery' ||
    location.pathname.startsWith('/search') ||
    location.pathname.startsWith('/templates') ||
    location.pathname.startsWith('/generate')

  const currentNav = isHomeBranch
    ? '/discovery'
    : navItems.find((i) => location.pathname.startsWith(i.to) && i.to !== '/discovery')?.to

  return (
    <div className="min-h-screen flex flex-col bg-bg">
      <header className="fixed top-0 inset-x-0 z-40 bg-surface border-b border-divider">
        <div className="h-16 max-w-container mx-auto px-[clamp(16px,3vw,32px)] flex items-center justify-between gap-6">
          <Link to="/discovery" className="flex items-center gap-3 shrink-0 no-underline">
            <div className="w-10 h-10 rounded-md bg-accent2-900 text-white grid place-items-center">
              <Icon name="hub" size={22} />
            </div>
            <span className="font-heading text-headline-md text-accent2-900 tracking-tight hidden sm:block">
              TemplateHub
            </span>
          </Link>

          <div className="flex items-center gap-2 relative">
            <Button
              variant="bare"
              size="icon"
              className="md:hidden hover:bg-neutral-200"
              title="Menu"
              onClick={toggleSidebar}
            >
              <Icon name={sidebarOpen ? 'close' : 'menu'} size={22} />
            </Button>
            <Button variant="bare" size="icon" className="hover:bg-neutral-200 text-neutral-700" title="Notifications">
              <Icon name="notifications" size={22} />
            </Button>
            <button
              type="button"
              className="flex items-center gap-3 ml-1 bg-transparent border-0 cursor-pointer font-[inherit] p-0"
              onClick={() => setSettingsOpen((v) => !v)}
              title="Account"
            >
              <div className="text-right hidden lg:block">
                <div className="text-body-md font-bold text-ink leading-none">Riya Mehta</div>
                <div className="text-label-md text-neutral-700 uppercase mt-[3px]">
                  {role === 'Admin' ? 'Doc control' : 'Consultant'}
                </div>
              </div>
              <Avatar initials="RM" size={32} />
            </button>

            {settingsOpen ? (
              <div className="elev-lg absolute top-[52px] right-0 w-[190px] bg-surface border border-divider rounded-lg p-[6px] z-20">
                <button type="button" className="hub-nav hub-nav-stacked" onClick={signOut}>
                  <Icon name="logout" size={18} />
                  <span className="flex-1 text-left">Log out</span>
                </button>
              </div>
            ) : null}
          </div>
        </div>

        <nav className="bg-surface border-t border-divider">
          <div className="max-w-container mx-auto px-[clamp(16px,3vw,32px)] h-12 hidden md:flex items-center gap-8">
            {navItems.map((item) => (
              /* Plain Link, not NavLink: NavLink applies its own `aria-current`
                 after spreading props, which clobbers the branch mapping above —
                 /search and /templates/* would then highlight nothing. */
              <Link key={item.to} to={item.to} className="hub-nav" aria-current={currentNav === item.to ? 'page' : undefined}>
                {item.label}
                {item.badge ? (
                  <span className="text-[10px] leading-none bg-neutral-300 text-neutral-700 rounded px-[5px] py-[3px]">
                    {item.badge}
                  </span>
                ) : null}
              </Link>
            ))}
          </div>

          {/* Mobile drawer, driven by the same toggle the sidebar used. */}
          {sidebarOpen ? (
            <div className="md:hidden px-[clamp(16px,3vw,32px)] pb-3 flex flex-col gap-1">
              {navItems.map((item) => (
                <Link
                  key={item.to}
                  to={item.to}
                  className="hub-nav hub-nav-stacked"
                  aria-current={currentNav === item.to ? 'page' : undefined}
                  onClick={toggleSidebar}
                >
                  {item.label}
                </Link>
              ))}
            </div>
          ) : null}
        </nav>
      </header>

      <main className={cn('flex-1 w-full', sidebarOpen ? 'pt-16 md:pt-28' : 'pt-16 md:pt-28')}>
        <div className="max-w-container mx-auto px-[clamp(16px,3vw,32px)] py-8">
          <Outlet />
        </div>
      </main>

      <footer className="border-t border-divider bg-surface">
        <div className="max-w-container mx-auto px-[clamp(16px,3vw,32px)] h-14 flex items-center justify-between gap-4 text-label-md text-neutral-600">
          <span>YMSLI Internal Use Only</span>
          <span className="hidden sm:block">© {new Date().getFullYear()} TemplateHub</span>
        </div>
      </footer>

      {toast ? (
        <div className="fixed right-6 bottom-6 z-50 flex items-center gap-3 bg-accent2-900 text-white rounded-lg py-3 px-4 shadow-elev-lg animate-hubfade">
          <Icon name="check_circle" size={20} filled />
          <span className="text-body-md">{toast}</span>
        </div>
      ) : null}

      <Dialog
        open={uploadDialogOpen}
        onOpenChange={closeUploadDialog}
        title="Sent for approval"
        actions={
          <Button variant="primary" onClick={closeUploadDialog}>
            Done
          </Button>
        }
      >
        <div className="dialog-body">
          <div className="flex items-center gap-3 bg-neutral-200 rounded-lg py-3 px-4 mb-4">
            <FormatChip size={34}>{lastUpload?.fmt ?? 'DOC'}</FormatChip>
            <div className="flex-1 min-w-0">
              <div className="text-body-md font-semibold truncate">
                {lastUpload ? `${lastUpload.name}${extOf(lastUpload.fmt)}` : 'Your upload'}
              </div>
              <div className="text-label-md text-neutral-600">{lastUpload?.meta ?? 'uploaded just now'}</div>
            </div>
          </div>
          Doc control has been notified by email and in the hub. Once an admin approves it, the template is published
          to Discovery for everyone.
        </div>
      </Dialog>
    </div>
  )
}
