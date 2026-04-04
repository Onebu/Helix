import { useState, useEffect, lazy, Suspense } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import RunConfigForm from '@/components/evolution/RunConfigForm'

const EvolutionDashboard = lazy(() => import('@/components/evolution/EvolutionDashboard'))

function DashboardFallback() {
  return (
    <div className="flex items-center justify-center py-20">
      <div className="h-8 w-8 animate-spin rounded-full border-4 border-muted border-t-primary" />
    </div>
  )
}

export default function PromptEvolutionPage() {
  const { promptId } = useParams<{ promptId: string }>()
  const [searchParams, setSearchParams] = useSearchParams()
  const [activeRunId, setActiveRunId] = useState<string | null>(searchParams.get('run'))
  const { t } = useTranslation()

  // Pick up ?run= param from History navigation
  useEffect(() => {
    const runParam = searchParams.get('run')
    if (runParam && runParam !== activeRunId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setActiveRunId(runParam)
      setSearchParams({}, { replace: true })
    }
  }, [searchParams, activeRunId, setSearchParams])

  if (!promptId) {
    return <p className="text-muted-foreground">{t('evolution.noPromptSelected')}</p>
  }

  if (activeRunId) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-bold text-foreground">{t('evolution.dashboard')}</h2>
          <button
            onClick={() => setActiveRunId(null)}
            className="px-4 py-2 rounded bg-secondary text-secondary-foreground hover:bg-secondary/80 text-sm"
          >
            {t('evolution.startNewRun')}
          </button>
        </div>
        <Suspense fallback={<DashboardFallback />}>
          <EvolutionDashboard runId={activeRunId} />
        </Suspense>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div className="max-w-2xl">
        <RunConfigForm promptId={promptId} onRunStarted={setActiveRunId} />
      </div>
    </div>
  )
}
