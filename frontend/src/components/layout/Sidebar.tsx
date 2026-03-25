import { useState, useEffect } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { FileText, ChevronLeft, ChevronRight, Wand2, Dna, Settings, Globe, Menu, X, Sun, Moon, Monitor } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { useTheme } from '@/hooks/useTheme'

const LANGUAGES = [
  { value: 'en', label: 'English' },
  { value: 'zh', label: '\u4E2D\u6587' },
  { value: 'es', label: 'Espa\u00F1ol' },
] as const

function CollapsedLink({ to, label, children }: { to: string; label: string; children: React.ReactNode }) {
  const { pathname } = useLocation()
  const isActive = pathname === to || pathname.startsWith(to + '/')

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <NavLink
          to={to}
          className={cn(
            'flex h-10 w-10 items-center justify-center rounded-md transition-colors',
            isActive
              ? 'bg-primary/15 text-primary ring-1 ring-primary/30'
              : 'text-muted-foreground hover:text-foreground hover:bg-accent/50'
          )}
        >
          {children}
        </NavLink>
      </TooltipTrigger>
      <TooltipContent side="right">{label}</TooltipContent>
    </Tooltip>
  )
}

function SidebarContent({ collapsed, setCollapsed, onNavClick }: { collapsed: boolean; setCollapsed: (v: boolean) => void; onNavClick?: () => void }) {
  const { t, i18n } = useTranslation()
  const { theme, setTheme } = useTheme()

  const currentLangIndex = LANGUAGES.findIndex((l) => l.value === i18n.language) ?? 0

  function cycleLanguage() {
    const nextIndex = (currentLangIndex + 1) % LANGUAGES.length
    i18n.changeLanguage(LANGUAGES[nextIndex].value)
  }

  function cycleTheme() {
    const order: Array<'light' | 'dark' | 'system'> = ['light', 'dark', 'system']
    const idx = order.indexOf(theme)
    setTheme(order[(idx + 1) % order.length])
  }

  const themeIcon = theme === 'dark' ? Moon : theme === 'light' ? Sun : Monitor
  const ThemeIcon = themeIcon

  const currentLangLabel = LANGUAGES.find((l) => l.value === i18n.language)?.label ?? 'English'

  return (
    <>
      {/* Header */}
      <div className={cn(
        'flex h-14 items-center',
        collapsed ? 'justify-center' : 'px-3'
      )}>
        {!collapsed && (
          <span className="flex items-center gap-2 text-lg font-semibold text-sidebar-foreground truncate">
            <Dna className="h-5 w-5 text-primary shrink-0" aria-hidden="true" />
            Helix
          </span>
        )}
        {collapsed && (
          <Dna className="h-5 w-5 text-primary" aria-hidden="true" />
        )}
      </div>

      {/* Toggle button (desktop only) */}
      <div className={cn('hidden md:flex', collapsed ? 'justify-center' : 'justify-end px-2')}>
        <Button
          variant="ghost"
          size="icon"
          onClick={() => setCollapsed(!collapsed)}
          aria-label={collapsed ? t('sidebar.expand') : t('sidebar.collapse')}
          className="h-8 w-8 text-muted-foreground hover:text-foreground"
        >
          {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
        </Button>
      </div>

      {/* Navigation */}
      <nav className={cn('flex-1 py-2', collapsed ? '' : 'px-2')} aria-label="Main navigation">
        <ul className={cn('flex flex-col', collapsed ? 'items-center gap-2' : 'gap-1')}>
          <li>
            {collapsed ? (
              <CollapsedLink to="/prompts" label={t('sidebar.prompts')}>
                <FileText className="h-5 w-5" />
              </CollapsedLink>
            ) : (
              <NavLink
                to="/prompts"
                onClick={onNavClick}
                className={({ isActive }) =>
                  cn(
                    'flex h-10 items-center gap-3 rounded-md px-3 text-sm font-medium transition-colors',
                    isActive
                      ? 'bg-primary/15 text-primary ring-1 ring-primary/30'
                      : 'text-muted-foreground hover:text-foreground hover:bg-accent/50'
                  )
                }
              >
                <FileText className="h-4 w-4" aria-hidden="true" />
                {t('sidebar.prompts')}
              </NavLink>
            )}
          </li>
          <li>
            {collapsed ? (
              <CollapsedLink to="/wizard" label={t('sidebar.wizard')}>
                <Wand2 className="h-5 w-5" />
              </CollapsedLink>
            ) : (
              <NavLink
                to="/wizard"
                onClick={onNavClick}
                className={({ isActive }) =>
                  cn(
                    'flex h-10 items-center gap-3 rounded-md px-3 text-sm font-medium transition-colors',
                    isActive
                      ? 'bg-primary/15 text-primary ring-1 ring-primary/30'
                      : 'text-muted-foreground hover:text-foreground hover:bg-accent/50'
                  )
                }
              >
                <Wand2 className="h-4 w-4" aria-hidden="true" />
                {t('sidebar.wizard')}
              </NavLink>
            )}
          </li>
        </ul>
      </nav>

      {/* Bottom section: Theme + Language + Settings */}
      <div className={cn('pb-3', collapsed ? '' : 'px-2')}>
        <Separator className={cn('mb-2', collapsed && 'mx-auto w-10')} />

        {/* Theme toggle */}
        <div className={cn('mb-1', collapsed && 'flex justify-center')}>
          {collapsed ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  onClick={cycleTheme}
                  aria-label={`Theme: ${theme}`}
                  className="flex h-10 w-10 items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-accent/50 transition-colors"
                >
                  <ThemeIcon className="h-5 w-5" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="right">
                Theme: {theme}
              </TooltipContent>
            </Tooltip>
          ) : (
            <button
              onClick={cycleTheme}
              className="flex h-10 w-full items-center gap-3 rounded-md px-3 text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-accent/50 transition-colors"
            >
              <ThemeIcon className="h-4 w-4 shrink-0" aria-hidden="true" />
              <span className="capitalize">{theme}</span>
            </button>
          )}
        </div>

        {/* Language selector */}
        <div className={cn('mb-1', collapsed && 'flex justify-center')}>
          {collapsed ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  onClick={cycleLanguage}
                  aria-label={`${t('sidebar.language')}: ${currentLangLabel}`}
                  className="flex h-10 w-10 items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-accent/50 transition-colors"
                >
                  <Globe className="h-5 w-5" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="right">
                {t('sidebar.language')}: {currentLangLabel}
              </TooltipContent>
            </Tooltip>
          ) : (
            <div className="flex h-10 items-center gap-3 rounded-md px-3">
              <Globe className="h-4 w-4 text-muted-foreground shrink-0" aria-hidden="true" />
              <Select
                value={i18n.language}
                onValueChange={(value) => i18n.changeLanguage(value)}
              >
                <SelectTrigger className="h-8 flex-1 text-sm border-0 bg-transparent px-0 shadow-none focus:ring-0">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {LANGUAGES.map((lang) => (
                    <SelectItem key={lang.value} value={lang.value}>
                      {lang.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
        </div>

        {/* Settings link */}
        <div className={cn(collapsed && 'flex justify-center')}>
          {collapsed ? (
            <CollapsedLink to="/settings" label={t('sidebar.settings')}>
              <Settings className="h-5 w-5" />
            </CollapsedLink>
          ) : (
            <NavLink
              to="/settings"
              onClick={onNavClick}
              className={({ isActive }) =>
                cn(
                  'flex h-10 items-center gap-3 rounded-md px-3 text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-primary/15 text-primary ring-1 ring-primary/30'
                    : 'text-muted-foreground hover:text-foreground hover:bg-accent/50'
                )
              }
            >
              <Settings className="h-4 w-4" aria-hidden="true" />
              {t('sidebar.settings')}
            </NavLink>
          )}
        </div>
      </div>
    </>
  )
}

export function Sidebar() {
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const location = useLocation()

  // Close mobile sidebar on route change
  useEffect(() => {
    setMobileOpen(false)
  }, [location.pathname])

  return (
    <TooltipProvider delayDuration={0}>
      {/* Mobile hamburger button */}
      <Button
        variant="ghost"
        size="icon"
        onClick={() => setMobileOpen(true)}
        aria-label="Open navigation menu"
        className="fixed top-3 left-3 z-50 md:hidden h-10 w-10"
      >
        <Menu className="h-5 w-5" />
      </Button>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-background/80 backdrop-blur-sm md:hidden"
          onClick={() => setMobileOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Mobile sidebar drawer */}
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-50 flex w-56 flex-col border-r border-sidebar-border bg-sidebar transition-transform duration-200 ease-in-out md:hidden',
          mobileOpen ? 'translate-x-0' : '-translate-x-full'
        )}
      >
        <div className="absolute top-3 right-3">
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setMobileOpen(false)}
            aria-label="Close navigation menu"
            className="h-8 w-8 text-muted-foreground hover:text-foreground"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
        <SidebarContent collapsed={false} setCollapsed={setCollapsed} onNavClick={() => setMobileOpen(false)} />
      </aside>

      {/* Desktop sidebar */}
      <aside
        className={cn(
          'hidden md:flex flex-col border-r border-sidebar-border bg-sidebar transition-[width] duration-200 ease-in-out',
          collapsed ? 'w-14' : 'w-56'
        )}
      >
        <SidebarContent collapsed={collapsed} setCollapsed={setCollapsed} />
      </aside>
    </TooltipProvider>
  )
}
