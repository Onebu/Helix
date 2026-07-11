import { useState, useEffect } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { FileText, ChevronLeft, ChevronRight, Wand2, Dna, Settings, Globe, Menu, Sun, Moon, Monitor } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { cn } from '@/lib/utils'
import { useTheme } from '@/hooks/useTheme'
import { useMediaQuery } from '@/hooks/useMediaQuery'

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
          aria-label={label}
          className={cn(
            'flex h-11 w-11 items-center justify-center rounded-md transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none',
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
  const themeLabel = t(`sidebar.${theme}`)

  // i18n.language can include region (e.g. "en-GB") — normalize to base code for matching
  const baseLang = LANGUAGES.find((l) => l.value === i18n.language)
    ? i18n.language
    : LANGUAGES.find((l) => i18n.language.startsWith(l.value))?.value ?? 'en'
  const currentLangLabel = LANGUAGES.find((l) => l.value === baseLang)?.label ?? 'English'

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
          className="h-11 w-11 text-muted-foreground hover:text-foreground"
        >
          {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
        </Button>
      </div>

      {/* Navigation */}
      <nav className={cn('flex-1 py-2', collapsed ? '' : 'px-2')} aria-label={t('sidebar.mainNavigation')}>
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
                    'flex min-h-11 items-center gap-3 rounded-md px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none',
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
                    'flex min-h-11 items-center gap-3 rounded-md px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none',
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
                  aria-label={t('sidebar.currentTheme', { theme: themeLabel })}
                  className="flex h-11 w-11 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none"
                >
                  <ThemeIcon className="h-5 w-5" aria-hidden="true" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="right">
                {t('sidebar.currentTheme', { theme: themeLabel })}
              </TooltipContent>
            </Tooltip>
          ) : (
            <button
              onClick={cycleTheme}
              aria-label={t('sidebar.currentTheme', { theme: themeLabel })}
              className="flex min-h-11 w-full items-center gap-3 rounded-md px-3 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none"
            >
              <ThemeIcon className="h-4 w-4 shrink-0" aria-hidden="true" />
              <span>{themeLabel}</span>
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
                  className="flex h-11 w-11 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none"
                >
                  <Globe className="h-5 w-5" aria-hidden="true" />
                </button>
              </TooltipTrigger>
              <TooltipContent side="right">
                {t('sidebar.language')}: {currentLangLabel}
              </TooltipContent>
            </Tooltip>
          ) : (
            <div className="flex min-h-11 items-center gap-3 rounded-md px-3">
              <Globe className="h-4 w-4 text-muted-foreground shrink-0" aria-hidden="true" />
              <Select
                value={baseLang}
                onValueChange={(value) => i18n.changeLanguage(value)}
              >
                <SelectTrigger aria-label={t('sidebar.language')} className="h-10 flex-1 text-sm border-0 bg-transparent px-0 shadow-none focus:ring-2 focus:ring-ring">
                  <SelectValue placeholder={currentLangLabel} />
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
                  'flex min-h-11 items-center gap-3 rounded-md px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none',
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
  const { t } = useTranslation()
  const [collapsed, setCollapsed] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const location = useLocation()
  const isDesktop = useMediaQuery('(min-width: 768px)')

  // Close mobile sidebar on route change
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMobileOpen(false)
  }, [location.pathname])

  useEffect(() => {
    if (isDesktop) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setMobileOpen(false)
    }
  }, [isDesktop])

  return (
    <TooltipProvider delayDuration={0}>
      {!isDesktop && <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
        <SheetTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            aria-label={t('sidebar.openNavigation')}
            className="fixed start-3 top-3 z-40 size-11 md:hidden"
          >
            <Menu className="h-5 w-5" aria-hidden="true" />
          </Button>
        </SheetTrigger>
        <SheetContent
          side="left"
          closeLabel={t('sidebar.closeNavigation')}
          className="flex w-64 max-w-[16rem] flex-col bg-sidebar p-0 motion-reduce:transition-none motion-reduce:animate-none md:hidden"
        >
          <SheetHeader className="sr-only">
            <SheetTitle>{t('sidebar.navigation')}</SheetTitle>
            <SheetDescription>{t('sidebar.navigationDescription')}</SheetDescription>
          </SheetHeader>
          <SidebarContent collapsed={false} setCollapsed={setCollapsed} onNavClick={() => setMobileOpen(false)} />
        </SheetContent>
      </Sheet>}

      {/* Desktop sidebar */}
      <aside
        className={cn(
          'hidden md:flex flex-col border-r border-sidebar-border bg-sidebar transition-[width] duration-200 ease-in-out motion-reduce:transition-none',
          collapsed ? 'w-14' : 'w-56'
        )}
      >
        <SidebarContent collapsed={collapsed} setCollapsed={setCollapsed} />
      </aside>
    </TooltipProvider>
  )
}
