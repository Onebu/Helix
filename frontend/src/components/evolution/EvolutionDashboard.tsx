import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  acceptVersionApiPromptsPromptIdVersionsAcceptPost,
  getRunStatusApiEvolutionRunIdStatusGet,
  listCasesApiPromptsPromptIdDatasetGet,
} from '../../client/sdk.gen'
import type { EvolutionRunStatus, PromptVersionResponse } from '../../client/types.gen'
import { useEvolutionSocket } from '../../hooks/useEvolutionSocket'
import { useRunResults } from '../../hooks/useRunResults'
import type {
  CandidateData,
  EvolutionStatus,
  GenerationData,
  LineageNode,
  SummaryData,
} from '../../types/evolution'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { useMediaQuery } from '@/hooks/useMediaQuery'
import AccessibleLineageView from './AccessibleLineageView'
import CandidateInspector from './CandidateInspector'
import CaseResultsGrid from './CaseResultsGrid'
import EvolutionWorkspace from './EvolutionWorkspace'
import FitnessChart from './FitnessChart'
import GenerationTable from './GenerationTable'
import IslandsSummary from './IslandsSummary'
import RunSummaryHeader from './RunSummaryHeader'

interface EvolutionDashboardProps {
  runId: string
}

const PERSISTED_TERMINAL_STATUSES = new Set<EvolutionStatus>([
  'complete',
  'budget_exhausted',
  'cancelled',
  'failed',
])

function statusFromResults(reason: string | null): EvolutionStatus {
  if (reason === 'cancelled') return 'cancelled'
  if (reason === 'budget_exhausted') return 'budget_exhausted'
  if (reason === 'error' || reason === 'failed') return 'failed'
  return 'complete'
}

function toLineageNode(candidate: CandidateData | LineageNode): LineageNode {
  return {
    ...candidate,
    parentIds: candidate.parentIds ?? [],
    survived: 'survived' in candidate ? candidate.survived : true,
  }
}

function EvolutionDashboardRun({ runId }: EvolutionDashboardProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const state = useEvolutionSocket(runId)
  const [refetchKey, setRefetchKey] = useState(0)
  const prevStatusRef = useRef(state.status)

  useEffect(() => {
    const becamePersistedTerminal = !PERSISTED_TERMINAL_STATUSES.has(prevStatusRef.current)
      && PERSISTED_TERMINAL_STATUSES.has(state.status)
    prevStatusRef.current = state.status
    if (becamePersistedTerminal) {
      const timer = setTimeout(() => setRefetchKey((key) => key + 1), 2000)
      return () => clearTimeout(timer)
    }
  }, [state.status])

  const { data: results } = useRunResults(runId, refetchKey)
  const { data: runStatusResp } = useQuery({
    queryKey: ['evolution-status', runId],
    queryFn: () => getRunStatusApiEvolutionRunIdStatusGet({ path: { run_id: runId } }),
    staleTime: Infinity,
    retry: 1,
  })
  const runStatus = (runStatusResp?.data ?? null) as EvolutionRunStatus | null

  const modelInfo = useMemo(() => ({
    metaModel: results?.metaModel ?? runStatus?.meta_model ?? null,
    metaProvider: results?.metaProvider ?? runStatus?.meta_provider ?? null,
    targetModel: results?.targetModel ?? runStatus?.target_model ?? null,
    targetProvider: results?.targetProvider ?? runStatus?.target_provider ?? null,
    judgeModel: results?.judgeModel ?? runStatus?.judge_model ?? null,
    judgeProvider: results?.judgeProvider ?? runStatus?.judge_provider ?? null,
  }), [results, runStatus])

  const hyperparameters = results?.hyperparameters ?? runStatus?.hyperparameters ?? null
  const displayStatus = results ? statusFromResults(results.terminationReason) : state.status
  const promptId = results?.promptId ?? null

  const { data: testCasesResp } = useQuery({
    queryKey: ['dataset-cases', promptId],
    queryFn: () => listCasesApiPromptsPromptIdDatasetGet({ path: { prompt_id: promptId! } }),
    enabled: !!promptId,
    staleTime: 5 * 60 * 1000,
  })
  const caseNames = useMemo(() => {
    const names = new Map<string, string>()
    for (const testCase of testCasesResp?.data ?? []) {
      if (testCase.name) names.set(testCase.id, testCase.name)
    }
    return names
  }, [testCasesResp])

  const [acceptedVersion, setAcceptedVersion] = useState<number | null>(null)
  const [acceptError, setAcceptError] = useState<string | null>(null)
  const acceptMutation = useMutation({
    mutationFn: async (template: string) => {
      const response = await acceptVersionApiPromptsPromptIdVersionsAcceptPost({
        path: { prompt_id: promptId! },
        body: { template },
        throwOnError: true,
      })
      const data = response.data as (PromptVersionResponse & { already_existed?: boolean }) | undefined
      if (data?.version == null) throw new Error(t('evolution.acceptFailed'))
      return data
    },
    onSuccess: (data) => {
      setAcceptedVersion(data.version)
      setAcceptError(null)
      if (!data.already_existed) {
        queryClient.invalidateQueries({ queryKey: ['prompt-versions', promptId] })
        queryClient.invalidateQueries({ queryKey: ['prompts', promptId] })
      }
    },
    onError: (error) => {
      setAcceptError(error instanceof Error ? error.message : t('evolution.acceptFailed'))
    },
  })

  const canAccept = !!results?.bestTemplate && !!promptId && acceptedVersion === null

  const historicalSummary = useMemo<SummaryData | null>(() => {
    if (!results || state.summary.lineageEventCount > 0) return null
    const events = results.lineageEvents
    const seeds = events.filter((event) => event.mutationType === 'seed')
    const seedFitness = seeds.length > 0
      ? Math.max(...seeds.map((event) => event.fitnessScore))
      : null
    const bestFitness = results.bestFitnessScore
      ?? (events.length > 0 ? Math.max(...events.map((event) => event.fitnessScore)) : null)

    return {
      bestFitness,
      bestNormalized: results.bestNormalizedScore,
      seedFitness,
      improvementDelta: seedFitness != null && bestFitness != null ? bestFitness - seedFitness : 0,
      terminationReason: results.terminationReason,
      lineageEventCount: events.length,
      totalCostUsd: results.totalCostUsd,
      generationsCompleted: results.generationsCompleted,
    }
  }, [results, state.summary.lineageEventCount])

  const historicalGenerations = useMemo<GenerationData[]>(() => {
    if (!results || state.generations.length > 0) return []
    if (results.generationRecords.length > 0) {
      return results.generationRecords.map((record) => ({
        generation: record.generation,
        label: t('evolution.generationLabel', { generation: record.generation + 1 }),
        bestFitness: record.bestFitness,
        avgFitness: record.avgFitness,
        bestNormalized: record.bestNormalized,
        avgNormalized: record.avgNormalized,
        candidatesEvaluated: record.candidatesEvaluated,
        costUsd: (record.costSummary?.total_cost_usd as number) ?? 0,
      }))
    }

    const seeds = results.lineageEvents.filter((event) => event.mutationType === 'seed')
    const evolved = results.lineageEvents.filter((event) => event.mutationType !== 'seed')
    const rows: GenerationData[] = []
    if (seeds.length > 0) {
      const scores = seeds.map((event) => event.fitnessScore)
      const normalized = seeds.map((event) => event.normalizedScore)
      rows.push({
        generation: -1,
        label: t('evolution.seed'),
        bestFitness: Math.max(...scores),
        avgFitness: scores.reduce((sum, value) => sum + value, 0) / scores.length,
        bestNormalized: Math.max(...normalized),
        avgNormalized: normalized.reduce((sum, value) => sum + value, 0) / normalized.length,
        candidatesEvaluated: seeds.length,
        costUsd: 0,
      })
    }

    const byGeneration = new Map<number, LineageNode[]>()
    for (const event of evolved) {
      const generation = byGeneration.get(event.generation) ?? []
      generation.push(event)
      byGeneration.set(event.generation, generation)
    }
    for (const [generation, events] of [...byGeneration.entries()].sort(([a], [b]) => a - b)) {
      const scores = events.map((event) => event.fitnessScore)
      const normalized = events.map((event) => event.normalizedScore)
      rows.push({
        generation,
        label: t('evolution.generationLabel', { generation: generation + 1 }),
        bestFitness: Math.max(...scores),
        avgFitness: scores.reduce((sum, value) => sum + value, 0) / scores.length,
        bestNormalized: Math.max(...normalized),
        avgNormalized: normalized.reduce((sum, value) => sum + value, 0) / normalized.length,
        candidatesEvaluated: events.length,
        costUsd: 0,
      })
    }
    return rows
  }, [results, state.generations.length, t])

  const persistedCandidates = useMemo<LineageNode[]>(() => {
    if (!results) return []
    const bestCoverage = results.caseResults.length > 0
      ? {
          casesPassed: results.caseResults.filter((result) => result.passed).length,
          totalCases: results.caseResults.length,
        }
      : null
    const seedCoverage = results.seedCaseResults.length > 0
      ? {
          casesPassed: results.seedCaseResults.filter((result) => result.passed).length,
          totalCases: results.seedCaseResults.length,
        }
      : null
    return results.lineageEvents.map((event) => ({
      ...event,
      casesPassed: event.candidateId === results.bestCandidateId
        ? bestCoverage?.casesPassed
        : event.mutationType === 'seed'
          ? seedCoverage?.casesPassed
          : undefined,
      totalCases: event.candidateId === results.bestCandidateId
        ? bestCoverage?.totalCases
        : event.mutationType === 'seed'
          ? seedCoverage?.totalCases
          : undefined,
    }))
  }, [results])

  const effectiveState = useMemo(() => {
    const withSummary = historicalSummary ? { ...state, summary: historicalSummary } : state
    return {
      ...withSummary,
      status: displayStatus,
      generations: withSummary.generations.length > 0
        ? withSummary.generations
        : historicalGenerations,
      candidates: results ? persistedCandidates : withSummary.candidates,
    }
  }, [displayStatus, historicalGenerations, historicalSummary, persistedCandidates, results, state])

  const candidatePool = useMemo<Array<CandidateData | LineageNode>>(
    () => results ? persistedCandidates : effectiveState.candidates,
    [effectiveState.candidates, persistedCandidates, results],
  )
  const defaultCandidateId = useMemo(() => {
    if (results?.bestCandidateId && candidatePool.some(
      (candidate) => candidate.candidateId === results.bestCandidateId,
    )) return results.bestCandidateId
    let best: CandidateData | LineageNode | null = null
    for (const candidate of candidatePool) {
      if (candidate.rejected) continue
      if (!best || candidate.fitnessScore >= best.fitnessScore) best = candidate
    }
    return best?.candidateId ?? null
  }, [candidatePool, results])
  const selectionScope = `${runId}:${results ? 'persisted' : 'live'}`
  const [candidateSelection, setCandidateSelection] = useState<{
    scope: string
    candidateId: string
  } | null>(null)
  const selectedCandidateId = candidateSelection?.scope === selectionScope
    ? candidateSelection.candidateId
    : null
  const selectedCandidate = candidatePool.find(
    (candidate) => candidate.candidateId === selectedCandidateId,
  ) ?? candidatePool.find((candidate) => candidate.candidateId === defaultCandidateId) ?? null
  const selectedParent = selectedCandidate?.parentIds?.[0]
    ? candidatePool.find((candidate) => candidate.candidateId === selectedCandidate.parentIds?.[0]) ?? null
    : null
  const lineageNodes = useMemo(() => candidatePool.map(toLineageNode), [candidatePool])
  const desktopInspector = useMediaQuery('(min-width: 1280px)')
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const inspectorActivatorRef = useRef<HTMLElement | SVGElement | null>(null)

  const selectCandidate = (candidateId: string) => {
    setCandidateSelection({ scope: selectionScope, candidateId })
    if (!desktopInspector) {
      const activeElement = document.activeElement
      inspectorActivatorRef.current = (activeElement instanceof HTMLElement || activeElement instanceof SVGElement)
        && activeElement !== document.body
        ? activeElement
        : null
      setInspectorOpen(true)
    } else {
      inspectorActivatorRef.current = null
      setInspectorOpen(false)
    }
  }

  const configuredIslands = (hyperparameters?.n_islands as number) || 4
  const progressView = (
    <div className="space-y-6">
      <div className="grid items-stretch gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(16rem,2fr)]">
        <FitnessChart data={effectiveState.generations} isLive={effectiveState.status === 'running'} />
        <IslandsSummary
          candidates={effectiveState.candidates}
          migrations={effectiveState.migrations}
          islandCount={effectiveState.islandCount || configuredIslands}
          status={effectiveState.status}
          seedFitness={effectiveState.summary.seedFitness}
        />
      </div>
      <GenerationTable data={effectiveState.generations} isLive={effectiveState.status === 'running'} />
    </div>
  )

  const lineageView = lineageNodes.length > 0 ? (
    <AccessibleLineageView
      nodes={lineageNodes}
      selectedId={selectedCandidate?.candidateId ?? null}
      bestCandidateId={results?.bestCandidateId ?? defaultCandidateId}
      onSelect={selectCandidate}
    />
  ) : (
    <p className="border-l-2 border-primary/40 py-2 pl-4 text-sm text-muted-foreground">
      {t('evolution.noLineageData')}
    </p>
  )

  const casesView = results?.caseResults.length ? (
    <CaseResultsGrid
      caseResults={results.caseResults}
      seedCaseResults={results.seedCaseResults}
      caseNames={caseNames}
    />
  ) : (
    <p className="border-l-2 border-primary/40 py-2 pl-4 text-sm text-muted-foreground">
      {t('evolution.noCaseResults')}
    </p>
  )

  const modelSummary = modelInfo.targetModel
    ? [modelInfo.targetProvider, modelInfo.targetModel].filter(Boolean).join('/')
    : null
  const feedback = acceptError ? (
    <span role="alert" className="text-xs text-destructive">{acceptError}</span>
  ) : acceptedVersion !== null ? (
    <Badge variant="outline" className="border-primary/25 text-primary">
      {t('evolution.acceptedVersion', { version: acceptedVersion })}
    </Badge>
  ) : null
  const action = canAccept ? (
    <Button
      size="sm"
      onClick={() => acceptMutation.mutate(results!.bestTemplate!)}
      disabled={acceptMutation.isPending}
    >
      {acceptMutation.isPending ? t('evolution.accepting') : t('evolution.acceptAsVersion')}
    </Button>
  ) : null

  return (
    <div className="space-y-4">
      <RunSummaryHeader
        state={effectiveState}
        summary={effectiveState.summary}
        modelSummary={modelSummary}
        action={action}
        feedback={feedback}
      />
      <div className="grid min-w-0 gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <EvolutionWorkspace progress={progressView} lineage={lineageView} cases={casesView} />
        {desktopInspector && (
          <CandidateInspector
            key={selectedCandidate?.candidateId ?? 'empty'}
            candidate={selectedCandidate}
            parent={selectedParent}
            modelInfo={modelInfo}
          />
        )}
      </div>
      {!desktopInspector && (
        <Sheet open={inspectorOpen} onOpenChange={setInspectorOpen}>
          <SheetContent
            side="right"
            closeLabel={t('common.close')}
            className="w-full max-w-[28rem] overflow-y-auto motion-reduce:transition-none motion-reduce:animate-none [&>button]:grid [&>button]:size-11 [&>button]:place-items-center"
            onCloseAutoFocus={(event) => {
              event.preventDefault()
              const activator = inspectorActivatorRef.current
              inspectorActivatorRef.current = null
              if (activator?.isConnected) activator.focus()
            }}
          >
            <SheetHeader className="pe-12 text-start">
              <SheetTitle>{t('evolution.candidateInspector')}</SheetTitle>
              <SheetDescription>{t('evolution.selectCandidateHint')}</SheetDescription>
            </SheetHeader>
            <CandidateInspector
              key={selectedCandidate?.candidateId ?? 'empty'}
              candidate={selectedCandidate}
              parent={selectedParent}
              modelInfo={modelInfo}
              embedded
            />
          </SheetContent>
        </Sheet>
      )}
    </div>
  )
}

export default function EvolutionDashboard({ runId }: EvolutionDashboardProps) {
  return <EvolutionDashboardRun key={runId} runId={runId} />
}
