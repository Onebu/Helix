import { useTranslation } from 'react-i18next'
import { useState, useEffect, useRef, useMemo, lazy, Suspense } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useEvolutionSocket } from '../../hooks/useEvolutionSocket'
import { useRunResults } from '../../hooks/useRunResults'
import { getRunStatusApiEvolutionRunIdStatusGet, acceptVersionApiPromptsPromptIdVersionsAcceptPost, listCasesApiPromptsPromptIdDatasetGet } from '../../client/sdk.gen'
import type { EvolutionRunStatus, PromptVersionResponse } from '../../client/types.gen'
import type { EvolutionStatus, SummaryData, GenerationData, CandidateData, LineageNode } from '../../types/evolution'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import FitnessChart from './FitnessChart'
import SummaryCards from './SummaryCards'
import GenerationTable from './GenerationTable'
import IslandsView from './IslandsView'
import DiffViewer from './DiffViewer'
import MutationStats from './MutationStats'
import CaseResultsGrid from './CaseResultsGrid'
import HyperparameterDisplay from './HyperparameterDisplay'

const Islands3D = lazy(() => import('./Islands3D'))
const Lineage3D = lazy(() => import('./Lineage3D'))

interface EvolutionDashboardProps {
  runId: string
}

function StatusBadge({ status }: { status: EvolutionStatus }) {
  const { t } = useTranslation()
  switch (status) {
    case 'connecting':
      return (
        <Badge className="bg-blue-500/10 text-blue-400 border-blue-500/20">
          <span className="h-2 w-2 rounded-full bg-blue-400 animate-pulse mr-1.5" />
          {t('evolution.connecting')}
        </Badge>
      )
    case 'running':
      return (
        <Badge className="bg-emerald-500/10 text-emerald-400 border-emerald-500/20">
          <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse mr-1.5" />
          {t('evolution.live')}
        </Badge>
      )
    case 'complete':
      return (
        <Badge className="bg-emerald-500/10 text-emerald-400 border-emerald-500/20">
          {t('evolution.complete')}
        </Badge>
      )
    case 'error':
      return (
        <Badge variant="destructive">
          {t('evolution.connectionError')}
        </Badge>
      )
    default:
      return (
        <Badge variant="outline">
          {t('evolution.idle')}
        </Badge>
      )
  }
}

function OverviewContent({
  state,
  hyperparameters,
  lineageEvents,
}: {
  state: ReturnType<typeof useEvolutionSocket>
  hyperparameters?: Record<string, unknown> | null
  lineageEvents?: LineageNode[]
}) {
  const configuredIslands = (hyperparameters?.n_islands as number) || 4
  return (
    <>
      {/* Summary cards */}
      <SummaryCards data={state.summary} />

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        <div className="lg:col-span-3">
          <FitnessChart data={state.generations} isLive={state.status === 'running'} />
        </div>
        <div className="lg:col-span-2">
          <IslandsView
            candidates={state.candidates}
            migrations={state.migrations}
            islandCount={state.islandCount || configuredIslands}
            status={state.status}
            seedFitness={state.summary.seedFitness}
            lineageEvents={lineageEvents}
          />
        </div>
      </div>

      {/* Generation table */}
      <GenerationTable data={state.generations} isLive={state.status === 'running'} />
    </>
  )
}

export default function EvolutionDashboard({ runId }: EvolutionDashboardProps) {
  const queryClient = useQueryClient()
  const state = useEvolutionSocket(runId)
  // Re-fetch results when WS status transitions to 'complete' (run just finished, DB now has data)
  const [refetchKey, setRefetchKey] = useState(0)
  const prevStatusRef = useRef(state.status)
  useEffect(() => {
    if (prevStatusRef.current !== 'complete' && state.status === 'complete') {
      // Delay refetch slightly to let DB persistence complete
      const timer = setTimeout(() => setRefetchKey(k => k + 1), 2000)
      return () => clearTimeout(timer)
    }
    prevStatusRef.current = state.status
  }, [state.status])
  const { data: results } = useRunResults(runId, refetchKey)
  const [activeTab, setActiveTab] = useState('overview')

  // Fetch run status once on mount for model info / hyperparameters during live runs
  const { data: runStatusResp } = useQuery({
    queryKey: ['evolution-status', runId],
    queryFn: () => getRunStatusApiEvolutionRunIdStatusGet({ path: { run_id: runId } }),
    staleTime: Infinity,   // only fetch once
    retry: 1,
  })
  const runStatus = (runStatusResp?.data ?? null) as EvolutionRunStatus | null

  // Derive model info: prefer results (post-run), fall back to runStatus (live run)
  const modelInfo = useMemo(() => ({
    metaModel: results?.metaModel ?? runStatus?.meta_model ?? null,
    metaProvider: results?.metaProvider ?? runStatus?.meta_provider ?? null,
    targetModel: results?.targetModel ?? runStatus?.target_model ?? null,
    targetProvider: results?.targetProvider ?? runStatus?.target_provider ?? null,
    judgeModel: results?.judgeModel ?? runStatus?.judge_model ?? null,
    judgeProvider: results?.judgeProvider ?? runStatus?.judge_provider ?? null,
  }), [results, runStatus])

  // Derive hyperparameters: prefer results, fall back to runStatus
  const hyperparameters = results?.hyperparameters ?? runStatus?.hyperparameters ?? null

  // Show as complete if WS says so OR if we already have results data (historical run)
  const isComplete = state.status === 'complete' || !!results
  const displayStatus = isComplete ? 'complete' : state.status

  // Accept as new version
  const promptId = results?.promptId ?? null

  // Fetch test case names for the prompt so we can display them instead of UUIDs
  const { data: testCasesResp } = useQuery({
    queryKey: ['dataset-cases', promptId],
    queryFn: () => listCasesApiPromptsPromptIdDatasetGet({ path: { prompt_id: promptId! } }),
    enabled: !!promptId,
    staleTime: 5 * 60 * 1000,
  })
  const caseNames = useMemo(() => {
    const map = new Map<string, string>()
    for (const tc of testCasesResp?.data ?? []) {
      if (tc.name) map.set(tc.id, tc.name)
    }
    return map
  }, [testCasesResp])
  const [acceptedVersion, setAcceptedVersion] = useState<number | null>(null)
  const [acceptError, setAcceptError] = useState<string | null>(null)

  const acceptMutation = useMutation({
    mutationFn: (template: string) =>
      acceptVersionApiPromptsPromptIdVersionsAcceptPost({
        path: { prompt_id: promptId! },
        body: { template },
      }),
    onSuccess: (resp) => {
      const data = resp.data as PromptVersionResponse & { already_existed?: boolean }
      const ver = data?.version
      setAcceptedVersion(ver ?? -1)
      setAcceptError(null)
      // Only invalidate if a new version was actually created
      if (!data?.already_existed) {
        queryClient.invalidateQueries({ queryKey: ['prompt-versions', promptId] })
        queryClient.invalidateQueries({ queryKey: ['prompts', promptId] })
      }
    },
    onError: (err) => {
      setAcceptError(err instanceof Error ? err.message : 'Failed to accept version')
    },
  })

  const canAccept = isComplete && !!results?.bestTemplate && !!promptId && acceptedVersion === null

  // For historical runs, derive summary from results data since WS won't replay
  const historicalSummary = useMemo<SummaryData | null>(() => {
    if (!results || state.summary.lineageEventCount > 0) return null
    const events = results.lineageEvents
    if (events.length === 0) return null

    // Seed fitness: use only actual seed mutation events, not evolved candidates in gen 0
    const seedMutationEvents = events.filter((e) => e.mutationType === 'seed')
    const seedFitness = seedMutationEvents.length > 0
      ? Math.max(...seedMutationEvents.map((e) => e.fitnessScore))
      : 0
    const bestFitness = results.bestFitnessScore ?? Math.max(...events.map((e) => e.fitnessScore))

    return {
      bestFitness,
      bestNormalized: results.bestNormalizedScore ?? null,
      seedFitness,
      improvementDelta: bestFitness - seedFitness,
      terminationReason: results.terminationReason ?? (bestFitness >= 1.0 ? 'perfect_fitness' : 'completed'),
      lineageEventCount: events.length,
      totalCostUsd: results.totalCostUsd,
      generationsCompleted: results.generationsCompleted,
    }
  }, [results, state.summary.lineageEventCount])

  // For historical runs, derive generation data from stored generation_records or lineage events
  const historicalGenerations = useMemo<GenerationData[]>(() => {
    if (!results || state.generations.length > 0) return []

    // Derive from lineage events, separating seeds from evolved candidates
    const events = results.lineageEvents
    if (events.length === 0) {
      // Fall back to stored generation_records if no lineage events
      if (results.generationRecords.length > 0) {
        return results.generationRecords.map((gr) => ({
          generation: gr.generation,
          label: `Gen ${gr.generation}`,
          bestFitness: gr.bestFitness,
          avgFitness: gr.avgFitness,
          bestNormalized: gr.bestNormalized,
          avgNormalized: gr.avgNormalized,
          candidatesEvaluated: gr.candidatesEvaluated,
          costUsd: (gr.costSummary?.total_cost_usd as number) ?? 0,
        }))
      }
      return []
    }

    // Separate seed events from evolved candidates
    const seedEvents = events.filter((e) => e.mutationType === 'seed')
    const evolvedEvents = events.filter((e) => e.mutationType !== 'seed')

    const rows: GenerationData[] = []

    // Add seed row
    if (seedEvents.length > 0) {
      const seedScores = seedEvents.map((e) => e.fitnessScore)
      const seedNormalized = seedEvents.map((e) => e.normalizedScore)
      rows.push({
        generation: -1,
        label: 'Seed',
        bestFitness: Math.max(...seedScores),
        avgFitness: seedScores.reduce((a, b) => a + b, 0) / seedScores.length,
        bestNormalized: Math.max(...seedNormalized),
        avgNormalized: seedNormalized.reduce((a, b) => a + b, 0) / seedNormalized.length,
        candidatesEvaluated: seedEvents.length,
        costUsd: 0,
      })
    }

    // Group evolved candidates by generation
    const byGen = new Map<number, typeof events>()
    for (const e of evolvedEvents) {
      const gen = e.generation
      if (!byGen.has(gen)) byGen.set(gen, [])
      byGen.get(gen)!.push(e)
    }

    for (const [gen, genEvents] of Array.from(byGen.entries()).sort(([a], [b]) => a - b)) {
      const scores = genEvents.map((e) => e.fitnessScore)
      const normalized = genEvents.map((e) => e.normalizedScore)
      rows.push({
        generation: gen,
        label: `Gen ${gen + 1}`,
        bestFitness: Math.max(...scores),
        avgFitness: scores.reduce((a, b) => a + b, 0) / scores.length,
        bestNormalized: Math.max(...normalized),
        avgNormalized: normalized.reduce((a, b) => a + b, 0) / normalized.length,
        candidatesEvaluated: genEvents.length,
        costUsd: 0,
      })
    }

    return rows
  }, [results, state.generations.length])

  // For historical runs, derive candidate data from lineage events
  const historicalCandidates = useMemo<CandidateData[]>(() => {
    if (!results || state.candidates.length > 0) return []
    return results.lineageEvents.map((e) => ({
      candidateId: e.candidateId,
      generation: e.generation,
      fitnessScore: e.fitnessScore,
      normalizedScore: e.normalizedScore,
      rejected: e.rejected,
      mutationType: e.mutationType,
      island: e.island,
    }))
  }, [results, state.candidates.length])

  const effectiveState = useMemo(() => {
    const s = historicalSummary ? { ...state, summary: historicalSummary } : state
    return {
      ...s,
      generations: s.generations.length > 0 ? s.generations : historicalGenerations,
      candidates: s.candidates.length > 0 ? s.candidates : historicalCandidates,
    }
  }, [state, historicalSummary, historicalGenerations, historicalCandidates])

  return (
    <div className="space-y-6">
      {/* Compact header bar: status + models/params + accept */}
      <div className="space-y-2">
        <div className="flex items-center gap-3 flex-wrap">
          <StatusBadge status={displayStatus} />
          {(hyperparameters || modelInfo.metaModel) && (
            <div className="flex-1 min-w-0">
              <HyperparameterDisplay hyperparameters={hyperparameters ?? {}} modelInfo={modelInfo} />
            </div>
          )}
          <div className="flex items-center gap-2 shrink-0">
            {acceptError && (
              <span className="text-red-400 text-xs">{acceptError}</span>
            )}
            {acceptedVersion !== null && (
              <Badge className="bg-emerald-500/10 text-emerald-400 border-emerald-500/20 text-xs">
                v{acceptedVersion} accepted
              </Badge>
            )}
            {canAccept && (
              <Button
                size="sm"
                variant="outline"
                className="border-emerald-600 text-emerald-400 hover:bg-emerald-600 hover:text-white text-xs"
                onClick={() => acceptMutation.mutate(results!.bestTemplate!)}
                disabled={acceptMutation.isPending}
              >
                {acceptMutation.isPending ? 'Accepting...' : 'Accept as New Version'}
              </Button>
            )}
          </div>
        </div>
      </div>

      {/* Sub-navigation: segmented button group */}
      {isComplete ? (
        <div>
          <div className="sticky top-0 z-10 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 pb-4">
            <div className="flex items-center gap-1 border-b border-border">
              {[
                { value: 'overview', label: 'Overview' },
                { value: 'lineage', label: 'Lineage' },
                { value: 'prompt-diffs', label: 'Prompt Diffs' },
                { value: 'mutation-stats', label: 'Mutation Stats' },
                { value: 'case-results', label: 'Case Results' },
                { value: '3d-islands', label: '3D Islands' },
              ].map((tab) => (
                <button
                  key={tab.value}
                  onClick={() => setActiveTab(tab.value)}
                  className={cn(
                    'px-3 py-2 text-xs font-medium transition-colors border-b-2 -mb-px',
                    activeTab === tab.value
                      ? 'border-primary text-foreground'
                      : 'border-transparent text-muted-foreground hover:text-foreground hover:border-muted-foreground/30'
                  )}
                >
                  {tab.label}
                </button>
              ))}
            </div>
          </div>

          {activeTab === 'overview' && (
            <div className="mt-6 space-y-6">
              <OverviewContent state={effectiveState} hyperparameters={hyperparameters as Record<string, unknown> | null} lineageEvents={results?.lineageEvents} />
            </div>
          )}
          {activeTab === 'prompt-diffs' && (
            <div className="mt-6">
              <DiffViewer
                lineageEvents={results?.lineageEvents ?? []}
                bestCandidateId={results?.bestCandidateId ?? null}
              />
            </div>
          )}
          {activeTab === 'mutation-stats' && (
            <div className="mt-6">
              <MutationStats lineageEvents={results?.lineageEvents ?? []} />
            </div>
          )}
          {activeTab === 'case-results' && (
            <div className="mt-6">
              <CaseResultsGrid
                caseResults={results?.caseResults ?? []}
                seedCaseResults={results?.seedCaseResults ?? []}
                caseNames={caseNames}
              />
            </div>
          )}
          {activeTab === '3d-islands' && (
            <div className="mt-6">
              <Suspense fallback={<div className="flex items-center justify-center h-[500px]"><p className="text-slate-400">Loading 3D view...</p></div>}>
                <Islands3D
                  candidates={effectiveState.candidates}
                  migrations={effectiveState.migrations}
                  islandCount={effectiveState.islandCount || (hyperparameters?.n_islands as number) || 4}
                  seedFitness={effectiveState.summary.seedFitness}
                  lineageEvents={results?.lineageEvents}
                />
              </Suspense>
            </div>
          )}
          {activeTab === 'lineage' && (
            <div className="mt-6">
              <Suspense fallback={<div className="flex items-center justify-center h-[500px]"><p className="text-slate-400">Loading 3D view...</p></div>}>
                <Lineage3D
                  lineageEvents={results?.lineageEvents ?? []}
                  bestCandidateId={results?.bestCandidateId ?? null}
                />
              </Suspense>
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-6">
          <OverviewContent state={effectiveState} hyperparameters={hyperparameters as Record<string, unknown> | null} />
        </div>
      )}
    </div>
  )
}
