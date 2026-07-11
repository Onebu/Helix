import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Badge } from '@/components/ui/badge'
import type { EvolutionState, EvolutionStatus, SummaryData } from '@/types/evolution'

interface RunSummaryHeaderProps {
  state: Pick<EvolutionState, 'status'>
  summary: SummaryData
  modelSummary?: string | null
  action?: ReactNode
  feedback?: ReactNode
}

function statusTone(status: EvolutionStatus) {
  if (status === 'failed' || status === 'error') return 'destructive' as const
  return 'outline' as const
}

function StatusBadge({ status }: { status: EvolutionStatus }) {
  const { t } = useTranslation()
  const labels: Record<EvolutionStatus, string> = {
    idle: t('evolution.idle'),
    connecting: t('evolution.connecting'),
    running: t('evolution.live'),
    complete: t('evolution.complete'),
    failed: t('evolution.failed'),
    cancelled: t('evolution.cancelled'),
    budget_exhausted: t('evolution.budgetExhausted'),
    error: t('evolution.connectionError'),
  }
  const active = status === 'connecting' || status === 'running'

  return (
    <Badge
      variant={statusTone(status)}
      className={active || status === 'complete'
        ? 'border-primary/25 bg-primary/10 text-primary'
        : undefined}
    >
      {active && <span aria-hidden="true" className="mr-1.5 size-2 animate-pulse rounded-full bg-current motion-reduce:animate-none" />}
      {labels[status]}
    </Badge>
  )
}

export default function RunSummaryHeader({
  state,
  summary,
  modelSummary,
  action,
  feedback,
}: RunSummaryHeaderProps) {
  const { t } = useTranslation()

  return (
    <header className="border-y border-border/70 py-4">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
        <div className="flex min-w-0 items-center gap-3">
          <StatusBadge status={state.status} />
          {modelSummary && (
            <span className="min-w-0 truncate text-sm text-muted-foreground" title={modelSummary}>
              {modelSummary}
            </span>
          )}
        </div>

        <dl className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm">
          <div>
            <dt className="inline text-muted-foreground">{t('evolution.completedGeneration')} </dt>
            <dd className="inline font-semibold tabular-nums text-foreground">
              {summary.generationsCompleted}
            </dd>
          </div>
          <div>
            <dt className="inline text-muted-foreground">{t('evolution.fullEvaluations')} </dt>
            <dd className="inline font-semibold tabular-nums text-foreground">
              {summary.lineageEventCount}
            </dd>
          </div>
          <div>
            <dt className="inline text-muted-foreground">{t('evolution.totalCost')} </dt>
            <dd className="inline font-semibold tabular-nums text-foreground">
              ${summary.totalCostUsd.toFixed(4)}
            </dd>
          </div>
        </dl>

        {(feedback || action) && (
          <div className="ml-auto flex min-w-0 flex-wrap items-center justify-end gap-2">
            {feedback}
            {action}
          </div>
        )}
      </div>
    </header>
  )
}
