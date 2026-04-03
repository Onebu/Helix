import { useTranslation } from 'react-i18next'
import { SCORE_POSITIVE, SCORE_NEGATIVE, SCORE_NEUTRAL, MUTATION_COLORS } from '../../types/evolution'

interface FitnessLegendProps {
  x: number
  y: number
  /** Unique SVG gradient ID to avoid collisions when multiple legends render in the same page. */
  gradientId?: string
  /** Minimum fitness value for the legend label. Defaults to -10. */
  minValue?: number
}

/**
 * SVG `<g>` element showing a gradient color legend for penalty-based fitness scores.
 * Designed to be placed inside an existing `<svg>` container (not a full SVG itself).
 */
export function FitnessLegend({ x, y, gradientId = 'fitness-gradient', minValue = -10 }: FitnessLegendProps) {
  const { t } = useTranslation()
  return (
    <g transform={`translate(${x}, ${y})`}>
      <defs>
        <linearGradient id={gradientId} x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor={SCORE_NEGATIVE} />
          <stop offset="50%" stopColor={MUTATION_COLORS.structural} />
          <stop offset="100%" stopColor={SCORE_POSITIVE} />
        </linearGradient>
      </defs>
      {/* Title */}
      <text x={0} y={0} fontSize={10} fill={SCORE_NEUTRAL}>
        {t('evolution.fitness')}
      </text>
      {/* Gradient bar */}
      <rect x={0} y={4} width={80} height={8} rx={2} fill={`url(#${gradientId})`} />
      {/* Labels */}
      <text x={0} y={22} fontSize={9} fill={SCORE_NEUTRAL}>
        {minValue}
      </text>
      <text x={80} y={22} fontSize={9} fill={SCORE_NEUTRAL} textAnchor="end">
        0
      </text>
    </g>
  )
}
