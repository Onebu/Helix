import { useTranslation } from 'react-i18next'
import type { SummaryData } from '../../types/evolution'
import { Card, CardContent } from '@/components/ui/card'
import { Trophy, Target, TrendingUp, Clock, GitBranch, DollarSign } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

interface SummaryCardsProps {
  data: SummaryData
}

interface CardConfig {
  label: string
  value: string
  colorClass: string
  icon: LucideIcon
  primary?: boolean
}

export default function SummaryCards({ data }: SummaryCardsProps) {
  const { t } = useTranslation()
  // Calculate progress percentage: 0% at seed fitness, 100% at 0 (perfect)
  const progressPct = (data.seedFitness != null && data.bestFitness != null && data.seedFitness < 0)
    ? Math.min(100, Math.round(((data.bestFitness - data.seedFitness) / (0 - data.seedFitness)) * 100))
    : null

  const stopReasonValue = (() => {
    const r = data.terminationReason
    if (!r) return t('evolution.running')
    const labels: Record<string, string> = {
      perfect_fitness: t('evolution.perfect'),
      generations_complete: t('evolution.maxGens'),
      budget_exhausted: t('evolution.budgetCap'),
      error: t('common.error'),
      cancelled: t('evolution.cancelled'),
    }
    return labels[r] ?? r.replace(/_/g, ' ')
  })()

  const stopReasonColor = data.terminationReason === 'perfect_fitness' ? 'text-score-positive'
    : data.terminationReason === 'error' ? 'text-score-negative'
    : 'text-foreground'

  // Primary cards: the headline metrics
  const primaryCards: CardConfig[] = [
    {
      label: t('evolution.bestFitness'),
      value: data.bestFitness != null
        ? `${data.bestFitness.toFixed(2)}${data.bestNormalized != null && !isNaN(data.bestNormalized) ? ` (${data.bestNormalized.toFixed(2)} norm)` : ''}${progressPct !== null ? ` ${progressPct}%` : ''}`
        : '\u2014',
      colorClass: 'text-score-positive',
      icon: Trophy,
      primary: true,
    },
    {
      label: t('evolution.improvement'),
      value: data.seedFitness != null && data.bestFitness != null && data.improvementDelta != null
        ? `+${data.improvementDelta.toFixed(2)}`
        : '\u2014',
      colorClass: 'text-info',
      icon: TrendingUp,
      primary: true,
    },
  ]

  // Secondary cards: supporting details
  const secondaryCards: CardConfig[] = [
    {
      label: t('evolution.seedFitness'),
      value: data.seedFitness != null ? data.seedFitness.toFixed(2) : '\u2014',
      colorClass: 'text-warning',
      icon: Target,
    },
    {
      label: t('evolution.stopReason'),
      value: stopReasonValue,
      colorClass: stopReasonColor,
      icon: Clock,
    },
    {
      label: t('evolution.lineageEvents'),
      value: String(data.lineageEventCount),
      colorClass: 'text-info',
      icon: GitBranch,
    },
    {
      label: t('evolution.totalCost'),
      value: `$${(data.totalCostUsd ?? 0).toFixed(4)}`,
      colorClass: 'text-warning',
      icon: DollarSign,
    },
  ]

  return (
    <div className="space-y-3">
      {/* Primary metrics: large and prominent */}
      <div className="grid grid-cols-2 gap-4">
        {primaryCards.map((card) => {
          const Icon = card.icon
          return (
            <Card key={card.label}>
              <CardContent className="pt-4 pb-4">
                <div className="flex items-center gap-1.5 text-muted-foreground text-xs uppercase tracking-wider">
                  <Icon className="h-3.5 w-3.5" />
                  {card.label}
                </div>
                <p className={`text-2xl font-bold mt-1 ${card.colorClass} break-words`}>
                  {card.value}
                </p>
              </CardContent>
            </Card>
          )
        })}
      </div>

      {/* Secondary metrics: compact inline row */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 px-1">
        {secondaryCards.map((card, i) => {
          const Icon = card.icon
          return (
            <span key={card.label} className="inline-flex items-center gap-1.5 text-sm">
              {i > 0 && <span className="text-muted-foreground/30 mr-1">&middot;</span>}
              <Icon className="h-3 w-3 text-muted-foreground" />
              <span className="text-muted-foreground">{card.label}</span>
              <span className={`font-medium ${card.colorClass}`}>{card.value}</span>
            </span>
          )
        })}
      </div>
    </div>
  )
}
