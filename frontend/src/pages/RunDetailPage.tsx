import { useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import EvolutionDashboard from '../components/evolution/EvolutionDashboard'

export default function RunDetailPage() {
  const { runId } = useParams<{ runId: string }>()
  const { t } = useTranslation()

  if (!runId) {
    return <p className="text-muted-foreground">{t('history.invalidRunId')}</p>
  }

  return (
    <div>
      <EvolutionDashboard runId={runId} />
    </div>
  )
}
