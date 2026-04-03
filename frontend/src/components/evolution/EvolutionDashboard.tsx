import { useTranslation } from 'react-i18next'
import { useState, useEffect, useRef, useMemo } from 'react'
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
import GenerationTable from './GenerationTable'
import IslandsSummary from './IslandsSummary'
import DiffViewer from './DiffViewer'
import CaseResultsGrid from './CaseResultsGrid'
import LineageGraph from './LineageGraph'
import type { CaseResultData } from '../../types/evolution'

interface EvolutionDashboardProps {
  runId: string
}

function StatusBadge({ status }: { status: EvolutionStatus }) {
  const { t } = useTranslation()
  switch (status) {
    case 'connecting':
      return (
        <Badge className="bg-info/10 text-info border-info/20">
          <span className="h-2 w-2 rounded-full bg-info animate-pulse mr-1.5" />
          {t('evolution.connecting')}
        </Badge>
      )
    case 'running':
      return (
        <Badge className="bg-success/10 text-success border-success/20">
          <span className="h-2 w-2 rounded-full bg-success animate-pulse mr-1.5" />
          {t('evolution.live')}
        </Badge>
      )
    case 'complete':
      return (
        <Badge className="bg-success/10 text-success border-success/20">
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

function CompactSummary({ data }: { data: SummaryData }) {
  const { t } = useTranslation()
  const stopLabel = (() => {
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

  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 text-sm">
      <span className="font-semibold text-foreground">
        Best: <span className="text-score-positive tabular-nums">{data.bestFitness?.toFixed(2) ?? '—'}</span>
      </span>
      {data.improvementDelta != null && data.improvementDelta > 0 && (
        <span className="text-score-positive font-medium">+{data.improvementDelta.toFixed(1)} improvement</span>
      )}
      <span className="text-muted-foreground">Seed: {data.seedFitness?.toFixed(2) ?? '—'}</span>
      <span className="text-muted-foreground">
        {stopLabel}
      </span>
      <span className="text-muted-foreground">{data.lineageEventCount} events</span>
      <span className="text-muted-foreground">${(data.totalCostUsd ?? 0).toFixed(4)}</span>
    </div>
  )
}

function OverviewContent({
  state,
  hyperparameters,
  lineageEvents,
  bestCandidateId,
  caseResults,
  seedCaseResults,
  caseNames,
}: {
  state: ReturnType<typeof useEvolutionSocket>
  hyperparameters?: Record<string, unknown> | null
  lineageEvents?: LineageNode[]
  bestCandidateId?: string | null
  caseResults?: CaseResultData[]
  seedCaseResults?: CaseResultData[]
  caseNames?: Map<string, string>
}) {
  const configuredIslands = (hyperparameters?.n_islands as number) || 4
  return (
    <>
      {/* Compact summary stats */}
      <CompactSummary data={state.summary} />

      {/* Charts row */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-6 items-stretch">
        <div className="md:col-span-2 lg:col-span-3">
          <FitnessChart data={state.generations} isLive={state.status === 'running'} />
        </div>
        <div className="md:col-span-2 lg:col-span-2 flex">
          <IslandsSummary
            candidates={state.candidates}
            migrations={state.migrations}
            islandCount={state.islandCount || configuredIslands}
            status={state.status}
            seedFitness={state.summary.seedFitness}
          />
        </div>
      </div>

      {/* Lineage graph (post-run only, when lineage data exists) */}
      {lineageEvents && lineageEvents.length > 0 && (
        <LineageGraph
          lineageEvents={lineageEvents}
          bestCandidateId={bestCandidateId ?? null}
        />
      )}

      {/* Generation table */}
      <GenerationTable data={state.generations} isLive={state.status === 'running'} />

      {/* Case results (post-run) */}
      {caseResults && caseResults.length > 0 && (
        <CaseResultsGrid
          caseResults={caseResults}
          seedCaseResults={seedCaseResults}
          caseNames={caseNames}
        />
      )}
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

  // Compact model summary for sticky bar
  const modelSummary = modelInfo.targetModel
    ? `${modelInfo.targetProvider ?? ''}/${modelInfo.targetModel}`.replace(/^\//, '')
    : null
  const paramSummary = hyperparameters
    ? [
        hyperparameters.generations != null && `${hyperparameters.generations} gen`,
        hyperparameters.n_islands != null && `${hyperparameters.n_islands} islands`,
        hyperparameters.budget_cap_usd != null && `$${hyperparameters.budget_cap_usd} budget`,
      ].filter(Boolean).join(' · ')
    : null

  return (
    <div className="space-y-4">
      {/* Compact sticky bar: status + model + tabs + CTA */}
      {isComplete ? (
        <div>
          <div className="sticky top-0 z-10 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
            <div className="flex items-center gap-3 border-b border-border py-2">
              {/* Left: status + run context */}
              <StatusBadge status={displayStatus} />
              {modelSummary && (
                <span className="text-xs text-muted-foreground font-mono hidden sm:inline">{modelSummary}</span>
              )}
              {paramSummary && (
                <span className="text-xs text-muted-foreground hidden md:inline">· {paramSummary}</span>
              )}

              {/* Center: tabs */}
              <div className="flex items-center gap-1 ml-4" role="tablist" aria-label="Evolution results">
                {[
                  { value: 'overview', label: 'Overview' },
                  { value: 'winning-path', label: 'Winning Path' },
                ].map((tab) => (
                  <button
                    key={tab.value}
                    role="tab"
                    aria-selected={activeTab === tab.value}
                    aria-controls={`panel-${tab.value}`}
                    onClick={() => setActiveTab(tab.value)}
                    className={cn(
                      'px-3 py-1.5 text-sm font-medium transition-colors rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                      activeTab === tab.value
                        ? 'bg-secondary text-foreground'
                        : 'text-muted-foreground hover:text-foreground hover:bg-muted/50'
                    )}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>

              {/* Right: CTA */}
              <div className="ml-auto flex items-center gap-2">
                {acceptError && (
                  <span className="text-score-negative text-xs">{acceptError}</span>
                )}
                {acceptedVersion !== null && (
                  <Badge className="bg-success/10 text-success border-success/20 text-xs">
                    v{acceptedVersion}
                  </Badge>
                )}
                {canAccept && (
                  <Button
                    size="sm"
                    onClick={() => acceptMutation.mutate(results!.bestTemplate!)}
                    disabled={acceptMutation.isPending}
                  >
                    {acceptMutation.isPending ? 'Accepting...' : 'Accept as New Version'}
                  </Button>
                )}
              </div>
            </div>
          </div>

          {activeTab === 'overview' && (
            <div className="mt-6 space-y-6">
              <OverviewContent
                state={effectiveState}
                hyperparameters={hyperparameters as Record<string, unknown> | null}
                lineageEvents={results?.lineageEvents}
                bestCandidateId={results?.bestCandidateId}
                caseResults={results?.caseResults}
                seedCaseResults={results?.seedCaseResults}
                caseNames={caseNames}
              />
            </div>
          )}
          {activeTab === 'winning-path' && (
            <div className="mt-6">
              <p className="text-sm text-muted-foreground mb-4">Step-by-step mutations from seed to best candidate</p>
              <DiffViewer
                lineageEvents={results?.lineageEvents ?? []}
                bestCandidateId={results?.bestCandidateId ?? null}
              />
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <StatusBadge status={displayStatus} />
            {modelSummary && (
              <span className="text-xs text-muted-foreground font-mono">{modelSummary}</span>
            )}
          </div>
          <OverviewContent state={effectiveState} hyperparameters={hyperparameters as Record<string, unknown> | null} />
        </div>
      )}
    </div>
  )
}
