import { useTranslation } from 'react-i18next'
import { useId, useMemo } from 'react'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
} from 'recharts'
import type { GenerationData } from '../../types/evolution'
import { MUTATION_COLORS, SCORE_POSITIVE } from '../../types/evolution'

interface FitnessChartProps {
  data: GenerationData[]
}

function generationNumber(label: string): string | null {
  const trimmed = label.trim()
  if (/^\d+$/.test(trimmed)) return trimmed
  return /^Gen\s+(\d+)$/i.exec(trimmed)?.[1] ?? null
}

export default function FitnessChart({ data, isLive = false }: FitnessChartProps & { isLive?: boolean }) {
  const { t } = useTranslation()
  const titleId = useId()
  const summaryId = useId()
  // Filter out data points with NaN, undefined, or Infinity values
  const cleanData = useMemo(() =>
    data.filter(d =>
      Number.isFinite(d.bestFitness) &&
      Number.isFinite(d.avgFitness)
    ), [data])

  // Compute left Y-axis domain from actual fitness data, always including 0
  const [fitnessMin, fitnessMax] = useMemo(() => {
    if (cleanData.length === 0) return [0, 0]
    const min = Math.min(...cleanData.map(d => Math.min(d.bestFitness, d.avgFitness)))
    const max = Math.max(...cleanData.map(d => Math.max(d.bestFitness, d.avgFitness)))
    return [Math.min(min, 0), Math.max(max, 0)]
  }, [cleanData])

  // Compute right Y-axis domain for normalized scores from actual data
  const normalizedValues = useMemo(() =>
    cleanData.map(d => d.bestNormalized).filter(Number.isFinite),
    [cleanData])

  const showNormalized = normalizedValues.length > 0
  const [normalizedMin, normalizedMax] = useMemo(() => {
    if (normalizedValues.length === 0) return [-1, 0]
    return [
      Math.min(...normalizedValues, -1),
      Math.max(...normalizedValues, 0),
    ]
  }, [normalizedValues])

  // Add small padding to fitness domain to prevent lines sitting on axis edges
  const fitnessPadding = (fitnessMax - fitnessMin) * 0.05 || 0.1
  const fitnessDomain: [number, number] = [fitnessMin - fitnessPadding, fitnessMax + fitnessPadding]

  const summary = useMemo(() => {
    if (cleanData.length === 0) return null
    const start = cleanData[0].bestFitness
    const best = Math.max(...cleanData.map((generation) => generation.bestFitness))
    const final = cleanData[cleanData.length - 1].bestFitness
    return t('evolution.fitnessSummary', {
      start: start.toFixed(2),
      best: best.toFixed(2),
      final: final.toFixed(2),
    })
  }, [cleanData, t])

  const localizedData = useMemo(() => cleanData.map((generation) => ({
    ...generation,
    displayLabel: generation.generation < 0 || generation.label.trim().toLowerCase() === 'seed'
      ? t('evolution.seed')
      : generationNumber(generation.label) == null
        ? generation.label
        : t('evolution.generationLabel', { generation: generationNumber(generation.label) }),
  })), [cleanData, t])

  return (
    <div
      role="figure"
      aria-labelledby={titleId}
      aria-describedby={summary ? summaryId : undefined}
      className="min-w-0 overflow-hidden rounded-lg border border-border bg-card"
    >
      <div className="px-4 py-3 border-b border-border">
        <h3 id={titleId} className="text-sm font-semibold text-foreground">{t('evolution.fitnessProgression')}</h3>
        {summary && <p id={summaryId} className="sr-only">{summary}</p>}
      </div>
      <div className="p-4">
      {cleanData.length === 0 ? (
        <div className="flex h-72 flex-col items-center justify-center gap-3 sm:h-[22rem] lg:h-[25rem]">
          {isLive ? (
            <>
              <div className="flex items-center gap-2">
                <span className="relative flex h-3 w-3">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75 motion-reduce:animate-none"></span>
                  <span className="relative inline-flex rounded-full h-3 w-3 bg-primary"></span>
                </span>
                <p className="text-muted-foreground">{t('evolution.evaluatingFirstGeneration')}</p>
              </div>
              <p className="text-muted-foreground text-xs">{t('evolution.evaluatingFirstGenerationHint')}</p>
            </>
          ) : (
            <p className="text-muted-foreground">{t('evolution.noDataYet')}</p>
          )}
        </div>
      ) : (
        <div className="h-72 min-w-0 sm:h-[22rem] lg:h-[25rem]">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={localizedData}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
            <XAxis dataKey="displayLabel" stroke="var(--color-muted-foreground)" />
            <YAxis yAxisId="left" domain={fitnessDomain} stroke="var(--color-muted-foreground)" tickFormatter={(v: number) => v.toFixed(1)} />
            <YAxis yAxisId="normalized" orientation="right" domain={[normalizedMin, normalizedMax]} stroke={MUTATION_COLORS.fresh} tickFormatter={(v: number) => v.toFixed(1)} />
            <ReferenceLine
              yAxisId="left"
              y={0}
              stroke={SCORE_POSITIVE}
              strokeDasharray="6 3"
              strokeWidth={1.5}
              label={{
                value: t('evolution.perfectFitnessBaseline'),
                position: 'right',
                fill: SCORE_POSITIVE,
                fontSize: 11,
              }}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: 'var(--color-card)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-foreground)',
                borderRadius: '0.5rem',
              }}
              labelStyle={{ color: 'var(--color-foreground)' }}
              formatter={(value) => typeof value === 'number' ? value.toFixed(2) : String(value ?? '')}
            />
            <Legend />
            <Line
              yAxisId="left"
              type="monotone"
              dataKey="bestFitness"
              stroke={MUTATION_COLORS.rcc}
              strokeWidth={3}
              dot={{ fill: MUTATION_COLORS.rcc }}
              name={t('evolution.bestFitness')}
              isAnimationActive={false}
              connectNulls={true}
            />
            <Line
              yAxisId="left"
              type="monotone"
              dataKey="avgFitness"
              stroke={MUTATION_COLORS.migrated}
              strokeWidth={3}
              dot={{ fill: MUTATION_COLORS.migrated }}
              name={t('evolution.avgFitness')}
              isAnimationActive={false}
              connectNulls={true}
            />
            {showNormalized && (
              <Line
                yAxisId="normalized"
                type="monotone"
                dataKey="bestNormalized"
                stroke={MUTATION_COLORS.fresh}
                strokeWidth={2}
                strokeDasharray="5 3"
                dot={{ fill: MUTATION_COLORS.fresh }}
                name={t('evolution.bestNorm')}
                isAnimationActive={false}
                connectNulls={true}
              />
            )}
          </LineChart>
        </ResponsiveContainer>
        </div>
      )}
      </div>
    </div>
  )
}
