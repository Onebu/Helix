import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import type { CandidateData, MigrationData, EvolutionStatus } from '../../types/evolution'
import { MUTATION_COLORS } from '../../types/evolution'
import { scoreColor } from '../../lib/scoring'

interface IslandsSummaryProps {
  candidates: CandidateData[]
  migrations: MigrationData[]
  islandCount: number
  status: EvolutionStatus
  seedFitness?: number | null
}

interface IslandStats {
  island: number
  candidateCount: number
  bestFitness: number
  avgFitness: number
  rejectedCount: number
  mutationBreakdown: Map<string, number>
  improvement: number | null
}

export default function IslandsSummary({ candidates, migrations, islandCount, status, seedFitness }: IslandsSummaryProps) {
  const { t } = useTranslation()

  const islands = useMemo<IslandStats[]>(() => {
    const result: IslandStats[] = []
    for (let i = 0; i < islandCount; i++) {
      const islandCandidates = candidates.filter(c => c.island === i)
      if (islandCandidates.length === 0) {
        result.push({
          island: i,
          candidateCount: 0,
          bestFitness: 0,
          avgFitness: 0,
          rejectedCount: 0,
          mutationBreakdown: new Map(),
          improvement: null,
        })
        continue
      }

      const scores = islandCandidates.map(c => c.fitnessScore)
      const best = Math.max(...scores)
      const avg = scores.reduce((a, b) => a + b, 0) / scores.length
      const rejected = islandCandidates.filter(c => c.rejected).length

      const mutations = new Map<string, number>()
      for (const c of islandCandidates) {
        mutations.set(c.mutationType, (mutations.get(c.mutationType) || 0) + 1)
      }

      result.push({
        island: i,
        candidateCount: islandCandidates.length,
        bestFitness: best,
        avgFitness: avg,
        rejectedCount: rejected,
        mutationBreakdown: mutations,
        improvement: seedFitness != null ? best - seedFitness : null,
      })
    }
    return result
  }, [candidates, islandCount, seedFitness])

  const totalMigrations = migrations.length

  if (islandCount === 0) {
    return (
      <div className="rounded-lg border border-border bg-card p-6 text-center text-muted-foreground text-sm">
        {t('evolution.noIslandData')}
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-foreground">{t('evolution.islands')}</h3>
        {totalMigrations > 0 && (
          <span className="text-xs text-muted-foreground">
            {totalMigrations} migration{totalMigrations !== 1 ? 's' : ''}
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2">
        {islands.map((island) => (
          <div
            key={island.island}
            className="rounded-md border border-border/60 bg-background/50 px-3 py-2.5 space-y-1.5"
          >
            {/* Island header */}
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-muted-foreground">
                Island {island.island}
              </span>
              <span className="text-xs text-muted-foreground">
                {island.candidateCount} candidates
              </span>
            </div>

            {island.candidateCount > 0 ? (
              <>
                {/* Best fitness */}
                <div className="flex items-baseline gap-2">
                  <span
                    className="text-lg font-bold tabular-nums"
                    style={{ color: scoreColor(island.bestFitness) }}
                  >
                    {island.bestFitness.toFixed(2)}
                  </span>
                  {island.improvement != null && island.improvement > 0 && (
                    <span className="text-xs text-emerald-500 font-medium">
                      +{island.improvement.toFixed(1)}
                    </span>
                  )}
                </div>

                {/* Avg fitness */}
                <div className="text-xs text-muted-foreground">
                  avg {island.avgFitness.toFixed(2)}
                  {island.rejectedCount > 0 && (
                    <span className="ml-2 text-destructive/70">
                      {island.rejectedCount} rejected
                    </span>
                  )}
                </div>

                {/* Mutation breakdown bar */}
                <div className="flex h-1.5 rounded-full overflow-hidden bg-border/30">
                  {Array.from(island.mutationBreakdown.entries()).map(([type, count]) => (
                    <div
                      key={type}
                      title={`${type}: ${count}`}
                      style={{
                        width: `${(count / island.candidateCount) * 100}%`,
                        backgroundColor: MUTATION_COLORS[type] ?? '#64748b',
                      }}
                    />
                  ))}
                </div>
              </>
            ) : (
              <div className="text-xs text-muted-foreground py-2">
                {status === 'running' ? 'Evaluating...' : 'No data'}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
