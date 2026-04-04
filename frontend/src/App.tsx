import { lazy, Suspense, useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ErrorBoundary } from './components/layout/ErrorBoundary'
import AppShell from './components/layout/AppShell'
import { PromptLayout } from './components/layout/PromptLayout'
import PromptsPage from './pages/PromptsPage'
import { isAuthenticated } from './lib/auth'
import { getApiBaseUrl } from './lib/api-config'

// Route-based code splitting: each page loads only when navigated to
const PromptTemplatePage = lazy(() => import('./pages/PromptTemplatePage'))
const PromptDatasetPage = lazy(() => import('./pages/PromptDatasetPage'))
const PromptEvolutionPage = lazy(() => import('./pages/PromptEvolutionPage'))
const PromptConfigPage = lazy(() => import('./pages/PromptConfigPage'))
const PromptHistoryPage = lazy(() => import('./pages/PromptHistoryPage'))
const RunDetailPage = lazy(() => import('./pages/RunDetailPage'))
const PromptPlaygroundPage = lazy(() => import('./pages/PromptPlaygroundPage'))
const WizardPage = lazy(() => import('./pages/WizardPage'))
const SettingsPage = lazy(() => import('./pages/SettingsPage'))
const LoginPage = lazy(() => import('./pages/LoginPage'))

const queryClient = new QueryClient()

/**
 * Auth guard that checks /api/auth/status to determine if login is required.
 * When auth is disabled on the backend, all routes are accessible without login.
 */
function RequireAuth({ children }: { children: React.ReactNode }) {
  const location = useLocation()
  const [authRequired, setAuthRequired] = useState<boolean | null>(null)

  useEffect(() => {
    fetch(`${getApiBaseUrl()}/api/auth/status`)
      .then(r => r.json())
      .then(data => setAuthRequired(data.auth_required))
      .catch(() => setAuthRequired(false))
  }, [])

  // Still loading auth status
  if (authRequired === null) return null

  // Auth not required by backend — allow through
  if (!authRequired) return <>{children}</>

  // Auth required but user not logged in — redirect to login
  if (!isAuthenticated()) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  return <>{children}</>
}

function PageFallback() {
  return (
    <div className="flex items-center justify-center py-20">
      <div className="h-8 w-8 animate-spin rounded-full border-4 border-muted border-t-primary" />
    </div>
  )
}

export default function App() {
  return (
    <ErrorBoundary>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Suspense fallback={<PageFallback />}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<RequireAuth><AppShell /></RequireAuth>}>
            <Route path="/prompts" element={<PromptsPage />} />
            <Route path="/wizard" element={<WizardPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="/prompts/:promptId" element={<PromptLayout />}>
              <Route index element={<Navigate to="template" replace />} />
              <Route path="template" element={<PromptTemplatePage />} />
              <Route path="dataset" element={<PromptDatasetPage />} />
              <Route path="config" element={<PromptConfigPage />} />
              <Route path="evolution" element={<PromptEvolutionPage />} />
              <Route path="history" element={<PromptHistoryPage />} />
              <Route path="history/:runId" element={<RunDetailPage />} />
              <Route path="playground" element={<PromptPlaygroundPage />} />
            </Route>
            {/* Redirects from old routes */}
            <Route path="/datasets" element={<Navigate to="/prompts" replace />} />
            <Route path="/evolution" element={<Navigate to="/prompts" replace />} />
            <Route path="/history" element={<Navigate to="/prompts" replace />} />
            <Route path="/history/:runId" element={<Navigate to="/prompts" replace />} />
            <Route path="/" element={<Navigate to="/prompts" replace />} />
          </Route>
        </Routes>
        </Suspense>
      </BrowserRouter>
    </QueryClientProvider>
    </ErrorBoundary>
  )
}
