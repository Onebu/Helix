import { useTranslation } from 'react-i18next'
import { useMemo } from 'react'
import type { LineageNode, MutationStat } from '../../types/evolution'
import { mutationBg, mutationColor, SCORE_POSITIVE, SCORE_NEGATIVE, SCORE_NEUTRAL } from '../../types/evolution'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table'

interface MutationStatsProps {
  lineageEvents: LineageNode[]
}

/**
 * Port of Python lineage/renderer.py:compute_mutation_stats.
 * Computes per-mutation-type effectiveness from lineage events.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function computeMutationStats(
  events: LineageNode[],
): Map<string, MutationStat> {
  const index = new Map(events.map((e) => [e.candidateId, e]))
  const stats = new Map<
    string,
    { count: number; improved: number; totalDelta: number }
  >()

  for (const event of events) {
    if (event.mutationType === 'seed') continue

    const mtype = event.mutationType
    if (!stats.has(mtype))
      stats.set(mtype, { count: 0, improved: 0, totalDelta: 0 })
    const s = stats.get(mtype)!
    s.count++

    const parentFitnesses = event.parentIds
      .filter((pid) => index.has(pid))
      .map((pid) => index.get(pid)!.fitnessScore)
    const delta =
      parentFitnesses.length > 0
        ? event.fitnessScore - Math.max(...parentFitnesses)
        : 0
    s.totalDelta += delta
    if (delta > 0) s.improved++
  }

  const result = new Map<string, MutationStat>()
  for (const [mtype, s] of stats) {
    result.set(mtype, {
      count: s.count,
      improved: s.improved,
      avgDelta: s.count > 0 ? s.totalDelta / s.count : 0,
    })
  }
  return result
}

export default function MutationStats({ lineageEvents }: MutationStatsProps) {
  const { t } = useTranslation()
  const stats = useMemo(
    () => computeMutationStats(lineageEvents),
    [lineageEvents],
  )

  const entries = useMemo(() => Array.from(stats.entries()), [stats])
  const totalCount = useMemo(
    () => entries.reduce((sum, [, s]) => sum + s.count, 0),
    [entries],
  )

  if (entries.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-card/50 p-8 text-center text-muted-foreground">
        {t('evolution.noMutationData')}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Distribution bar */}
      <div className="rounded-lg border border-border bg-card p-4">
        <p className="mb-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
          {t('evolution.mutationDistribution')}
        </p>
        <div className="flex h-4 overflow-hidden rounded-full">
          {entries.map(([mtype, s]) => {
            const pct = totalCount > 0 ? (s.count / totalCount) * 100 : 0
            return (
              <div
                key={mtype}
                title={`${mtype}: ${s.count} (${pct.toFixed(1)}%)`}
                style={{
                  width: `${pct}%`,
                  backgroundColor: mutationColor(mtype),
                }}
              />
            )
          })}
        </div>
        <div className="mt-2 flex flex-wrap gap-3 text-xs text-muted-foreground">
          {entries.map(([mtype, s]) => (
            <span key={mtype} className="flex items-center gap-1">
              <span
                className="inline-block h-2 w-2 rounded-full"
                style={{
                  backgroundColor: mutationColor(mtype),
                }}
              />
              {mtype}: {s.count}
            </span>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="overflow-hidden rounded-lg border border-border bg-card">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted">
              <TableHead>{t('evolution.mutationType')}</TableHead>
              <TableHead className="text-right">Count</TableHead>
              <TableHead className="text-right">Improved</TableHead>
              <TableHead className="text-right">Improvement Rate</TableHead>
              <TableHead className="text-right">Avg Delta</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {entries.map(([mtype, s]) => {
              const rate = s.count > 0 ? (s.improved / s.count) * 100 : 0
              const deltaColor =
                s.avgDelta > 0
                  ? SCORE_POSITIVE
                  : s.avgDelta < 0
                    ? SCORE_NEGATIVE
                    : SCORE_NEUTRAL

              return (
                <TableRow key={mtype}>
                  <TableCell>
                    <span
                      className="inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold"
                      style={{
                        background: mutationBg(mtype),
                        color: mutationColor(mtype),
                      }}
                    >
                      {mtype}
                    </span>
                  </TableCell>
                  <TableCell className="text-right">{s.count}</TableCell>
                  <TableCell className="text-right">{s.improved}</TableCell>
                  <TableCell className="text-right">{rate.toFixed(1)}%</TableCell>
                  <TableCell
                    className="text-right font-mono"
                    style={{ color: deltaColor }}
                  >
                    {s.avgDelta >= 0 ? '+' : ''}
                    {s.avgDelta.toFixed(4)}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
