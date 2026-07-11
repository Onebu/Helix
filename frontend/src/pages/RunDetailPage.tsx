import { lazy, Suspense } from 'react'
import { useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

const EvolutionDashboard = lazy(() => import('../components/evolution/EvolutionDashboard'))

export default function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>()
  const { t } = useTranslation()

  if (!runId) {
    return <p className="text-muted-foreground">{t('history.invalidRunId')}</p>
  }

  return (
    <div>
      <Suspense fallback={
        <div className="flex items-center justify-center py-20" role="status" aria-label={t('common.loading')}>
          <div aria-hidden="true" className="h-8 w-8 animate-spin rounded-full border-4 border-muted border-t-primary motion-reduce:animate-none" />
        </div>
      }>
        <EvolutionDashboard runId={runId} />
      </Suspense>
    </div>
  )
}
