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
  borderClass: string
}

export default function SummaryCards({ data }: SummaryCardsProps) {
  const { t } = useTranslation()
  // Calculate progress percentage: 0% at seed fitness, 100% at 0 (perfect)
  const progressPct = (data.seedFitness != null && data.bestFitness != null && data.seedFitness < 0)
    ? Math.min(100, Math.round(((data.bestFitness - data.seedFitness) / (0 - data.seedFitness)) * 100))
    : null

  const cards: CardConfig[] = [
    {
      label: t('evolution.bestFitness'),
      value: data.bestFitness != null
        ? `${data.bestFitness.toFixed(2)}${data.bestNormalized != null && !isNaN(data.bestNormalized) ? ` (${data.bestNormalized.toFixed(2)} norm)` : ''}${progressPct !== null ? ` ${progressPct}%` : ''}`
        : '—',
      colorClass: 'text-emerald-400',
      icon: Trophy,
      borderClass: 'border-l-emerald-400',
    },
    {
      label: t('evolution.seedFitness'),
      value: data.seedFitness != null ? data.seedFitness.toFixed(2) : '—',
      colorClass: 'text-amber-400',
      icon: Target,
      borderClass: 'border-l-amber-400',
    },
    {
      label: t('evolution.improvement'),
      value: data.seedFitness != null && data.bestFitness != null && data.improvementDelta != null
        ? `+${data.improvementDelta.toFixed(2)}`
        : '—',
      colorClass: 'text-blue-400',
      icon: TrendingUp,
      borderClass: 'border-l-blue-400',
    },
    {
      label: t('evolution.stopReason'),
      value: (() => {
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
      })(),
      colorClass: data.terminationReason === 'perfect_fitness' ? 'text-emerald-400'
        : data.terminationReason === 'error' ? 'text-red-400'
        : 'text-foreground',
      icon: Clock,
      borderClass: 'border-l-slate-400',
    },
    {
      label: t('evolution.lineageEvents'),
      value: String(data.lineageEventCount),
      colorClass: 'text-blue-400',
      icon: GitBranch,
      borderClass: 'border-l-blue-400',
    },
    {
      label: t('evolution.totalCost'),
      value: `$${(data.totalCostUsd ?? 0).toFixed(4)}`,
      colorClass: 'text-amber-400',
      icon: DollarSign,
      borderClass: 'border-l-amber-400',
    },
  ]

  return (
    <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
      {cards.map((card) => {
        const Icon = card.icon
        const isLongValue = card.value.length > 14
        return (
          <Card key={card.label} className={`border-l-[3px] ${card.borderClass}`}>
            <CardContent className="pt-5 pb-5">
              <div className="flex items-center gap-1.5 text-muted-foreground text-xs uppercase tracking-wider">
                <Icon className="h-3.5 w-3.5" />
                {card.label}
              </div>
              <p className={`${isLongValue ? 'text-lg' : 'text-2xl'} font-bold mt-1 ${card.colorClass} break-words`}>
                {card.value}
              </p>
            </CardContent>
          </Card>
        )
      })}
    </div>
  )
}
