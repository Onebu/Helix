import { useTranslation } from 'react-i18next'
import { useMemo, useState } from 'react'
import { createTwoFilesPatch } from 'diff'
import type { LineageNode } from '../../types/evolution'
import { mutationBg, mutationColor } from '../../types/evolution'
import { traceWinningPath, detectIslandTransitions } from '../../lib/lineage-utils'
import { parsePatchLines } from '../../lib/diff-utils'
import type { DiffLine } from '../../lib/diff-utils'

interface DiffViewerProps {
  lineageEvents: LineageNode[]
  bestCandidateId: string | null
}

interface DiffStep {
  parentId: string
  childId: string
  childFitness: number
  parentFitness: number
  mutationType: string
  patch: string
  lines: DiffLine[]
}

export default function DiffViewer({
  lineageEvents,
  bestCandidateId,
}: DiffViewerProps) {
  const { t } = useTranslation()
  const [seedExpanded, setSeedExpanded] = useState(false)

  // Deduplicate events
  const eventIndex = useMemo(() => {
    const map = new Map<string, LineageNode>()
    for (const e of lineageEvents) map.set(e.candidateId, e)
    return map
  }, [lineageEvents])

  // Compute winning path
  const winningPath = useMemo(
    () => traceWinningPath(Array.from(eventIndex.values()), bestCandidateId),
    [eventIndex, bestCandidateId],
  )

  // Order winning path nodes by generation (ascending)
  const orderedWinningPath = useMemo(() => {
    const nodes: LineageNode[] = []
    for (const id of winningPath) {
      const node = eventIndex.get(id)
      if (node) nodes.push(node)
    }
    return nodes.sort((a, b) => a.generation - b.generation)
  }, [winningPath, eventIndex])

  // Filter to nodes with templates; fallback to seed→best if path is broken
  const nodesWithTemplates = useMemo(() => {
    const fromPath = orderedWinningPath.filter((n) => n.template !== undefined)
    if (fromPath.length >= 2) return fromPath

    // Path incomplete — build seed→best fallback
    const seedNode = lineageEvents.find((e) => e.mutationType === 'seed' && e.template)
    const bestNode = bestCandidateId ? eventIndex.get(bestCandidateId) : null
    if (seedNode && bestNode?.template && seedNode.candidateId !== bestNode.candidateId) {
      return [seedNode, bestNode]
    }
    // If only one of them exists, return whatever we have
    return fromPath.length > 0 ? fromPath : (seedNode ? [seedNode] : [])
  }, [orderedWinningPath, lineageEvents, eventIndex, bestCandidateId])

  // Detect island transitions in the winning path
  const islandTransitions = useMemo(() => {
    return detectIslandTransitions(nodesWithTemplates)
  }, [nodesWithTemplates])

  const transitionMap = useMemo(() => {
    const map = new Map<string, { fromIsland: number; toIsland: number }>()
    for (const t of islandTransitions) {
      map.set(t.atCandidateId, { fromIsland: t.fromIsland, toIsland: t.toIsland })
    }
    return map
  }, [islandTransitions])

  // Compute diff steps
  const diffSteps = useMemo<DiffStep[]>(() => {
    if (nodesWithTemplates.length < 2) return []

    const steps: DiffStep[] = []
    for (let i = 1; i < nodesWithTemplates.length; i++) {
      const parent = nodesWithTemplates[i - 1]
      const child = nodesWithTemplates[i]

      const patch = createTwoFilesPatch(
        `${parent.candidateId.slice(0, 8)} (fit=${parent.fitnessScore.toFixed(3)})`,
        `${child.candidateId.slice(0, 8)} (fit=${child.fitnessScore.toFixed(3)})`,
        parent.template ?? '',
        child.template ?? '',
        '',
        '',
        { context: 3 },
      )

      steps.push({
        parentId: parent.candidateId,
        childId: child.candidateId,
        childFitness: child.fitnessScore,
        parentFitness: parent.fitnessScore,
        mutationType: child.mutationType,
        patch,
        lines: parsePatchLines(patch),
      })
    }

    return steps
  }, [nodesWithTemplates])

  // Seed template info
  const seedNode = nodesWithTemplates.length > 0 ? nodesWithTemplates[0] : null
  const seedTemplate = seedNode?.template ?? ''
  const seedLineCount = seedTemplate.split('\n').length
  const defaultSeedExpanded = seedLineCount <= 20

  if (nodesWithTemplates.length < 2) {
    return (
      <div className="rounded-lg border border-border bg-card/50 p-8 text-center">
        <p className="text-muted-foreground">{t('evolution.noDiffData')}</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Seed / Initial Template */}
      {seedNode && (
        <div className="bg-card border border-border rounded-lg overflow-hidden">
          <div className="flex items-center gap-3 px-4 py-3 bg-muted">
            <span className="font-bold text-foreground">{t('evolution.initialTemplate')}</span>
            <span className="font-mono text-muted-foreground text-sm">
              {seedNode.candidateId.slice(0, 8)}
            </span>
            <span
              className="text-xs px-2 py-0.5 rounded-full"
              style={{
                backgroundColor: mutationBg(seedNode.mutationType),
                color: mutationColor(seedNode.mutationType),
              }}
            >
              {seedNode.mutationType}
            </span>
            <span className="text-score-positive font-bold ml-auto">
              {seedNode.fitnessScore.toFixed(3)}
            </span>
          </div>
          <div className="px-4 py-3">
            <button
              onClick={() => setSeedExpanded(!seedExpanded)}
              className="text-xs text-muted-foreground hover:text-foreground mb-2"
            >
              {seedExpanded || defaultSeedExpanded
                ? 'Collapse'
                : `Expand (${seedLineCount} lines)`}
            </button>
            {(seedExpanded || defaultSeedExpanded) && (
              <pre className="font-mono text-xs leading-relaxed text-muted-foreground overflow-x-auto whitespace-pre-wrap">
                {seedTemplate}
              </pre>
            )}
          </div>
        </div>
      )}

      {/* Diff Steps */}
      {diffSteps.map((step, i) => {
        const delta = step.childFitness - step.parentFitness
        return (
          <div key={step.childId} className="space-y-2">
            {transitionMap.has(step.childId) && (
              <div className="flex items-center gap-2 px-4 py-2 text-xs text-mutation-fresh bg-mutation-fresh/10 rounded-lg border border-mutation-fresh/20">
                <span>Migrated from Island {transitionMap.get(step.childId)!.fromIsland}</span>
                <span className="text-muted-foreground">&rarr;</span>
                <span>Island {transitionMap.get(step.childId)!.toIsland}</span>
              </div>
            )}
          <div
            className="bg-card border border-border rounded-lg overflow-hidden"
          >
            {/* Step header */}
            <div className="flex items-center gap-3 px-4 py-3 bg-muted flex-wrap">
              <span className="font-bold text-foreground">{t('evolution.step', { number: i + 1 })}</span>
              <span className="font-mono text-muted-foreground text-sm">
                {step.childId.slice(0, 8)}
              </span>
              <span
                className="text-xs px-2 py-0.5 rounded-full"
                style={{
                  backgroundColor: mutationBg(step.mutationType),
                  color: mutationColor(step.mutationType),
                }}
              >
                {step.mutationType}
              </span>
              <span className="text-score-positive font-bold ml-auto">
                {step.childFitness.toFixed(3)}
              </span>
              <span
                className={`text-xs font-mono ${delta >= 0 ? 'text-score-positive' : 'text-score-negative'}`}
              >
                {delta >= 0 ? '+' : ''}
                {delta.toFixed(3)}
              </span>
            </div>

            {/* Diff content */}
            <div className="font-mono text-xs leading-relaxed px-4 py-3 overflow-x-auto whitespace-pre-wrap">
              {step.lines.map((line, j) => {
                if (line.type === 'hunk') {
                  return (
                    <div
                      key={j}
                      data-diff-type="hunk"
                      className="text-diff-hunk mt-2 mb-1"
                    >
                      {line.content}
                    </div>
                  )
                }
                if (line.type === 'add') {
                  return (
                    <div
                      key={j}
                      data-diff-type="add"
                      className="text-diff-add bg-diff-add-bg"
                    >
                      +{line.content}
                    </div>
                  )
                }
                if (line.type === 'del') {
                  return (
                    <div
                      key={j}
                      data-diff-type="del"
                      className="text-diff-del bg-diff-del-bg line-through opacity-70"
                    >
                      -{line.content}
                    </div>
                  )
                }
                return (
                  <div key={j} data-diff-type="context" className="text-muted-foreground">
                    {' '}
                    {line.content}
                  </div>
                )
              })}
            </div>
          </div>
          </div>
        )
      })}
    </div>
  )
}
