import { Outlet } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Sidebar } from './Sidebar'
import { AppBreadcrumbs } from './Breadcrumbs'

export default function AppShell() {
  const { t } = useTranslation()

  return (
    <div className="flex h-dvh min-h-0 bg-background text-foreground">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:p-4 focus:bg-primary focus:text-primary-foreground focus:rounded-md focus:m-2"
      >
        {t('layout.skipToMain')}
      </a>
      <Sidebar />
      <main id="main-content" className="min-w-0 flex-1 overflow-auto">
        <div className="px-4 pb-6 pt-16 md:p-6">
          <AppBreadcrumbs />
          <Outlet />
        </div>
      </main>
    </div>
  )
}
