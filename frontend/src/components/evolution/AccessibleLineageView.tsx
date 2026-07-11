import { useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { deduplicateEvents } from '@/lib/lineage-utils'
import type { LineageNode } from '@/types/evolution'
import LineageGraph from './LineageGraph'

interface AccessibleLineageViewProps {
  nodes: LineageNode[]
  selectedId: string | null
  bestCandidateId: string | null
  onSelect: (candidateId: string) => void
}

export default function AccessibleLineageView({
  nodes,
  selectedId,
  bestCandidateId,
  onSelect,
}: AccessibleLineageViewProps) {
  const { t } = useTranslation()
  const [view, setView] = useState('graph')
  const treeItemRefs = useRef(new Map<string, HTMLButtonElement>())
  const orderedNodes = useMemo(() => (
    deduplicateEvents(nodes).sort((left, right) => (
      left.generation - right.generation
      || left.island - right.island
      || left.candidateId.localeCompare(right.candidateId)
    ))
  ), [nodes])
  const [focusedTreeId, setFocusedTreeId] = useState<string | null>(null)
  const selectedExists = selectedId && orderedNodes.some((node) => node.candidateId === selectedId)
  const focusedExists = focusedTreeId && orderedNodes.some((node) => node.candidateId === focusedTreeId)
  const rovingTreeId = focusedExists
    ? focusedTreeId
    : selectedExists
      ? selectedId
      : orderedNodes[0]?.candidateId ?? null

  const handleTreeKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>, candidateId: string) => {
    const currentIndex = orderedNodes.findIndex((node) => node.candidateId === candidateId)
    if (currentIndex < 0) return

    const nextIndex = event.key === 'ArrowDown'
      ? Math.min(currentIndex + 1, orderedNodes.length - 1)
      : event.key === 'ArrowUp'
        ? Math.max(currentIndex - 1, 0)
        : event.key === 'Home'
          ? 0
          : event.key === 'End'
            ? orderedNodes.length - 1
            : null
    if (nextIndex === null) return
    event.preventDefault()
    if (nextIndex === currentIndex) return
    const nextId = orderedNodes[nextIndex]?.candidateId
    if (!nextId) return
    setFocusedTreeId(nextId)
    treeItemRefs.current.get(nextId)?.focus()
  }

  return (
    <Tabs value={view} onValueChange={setView} className="min-w-0">
      <TabsList aria-label={t('evolution.lineageViewMode')} className="mb-3 h-11 w-full justify-start overflow-x-auto whitespace-nowrap">
        <TabsTrigger className="min-h-11 shrink-0" value="graph">{t('evolution.graphView')}</TabsTrigger>
        <TabsTrigger className="min-h-11 shrink-0" value="list">{t('evolution.listView')}</TabsTrigger>
      </TabsList>
      <TabsContent value="graph" className="mt-0">
        <LineageGraph
          lineageEvents={orderedNodes}
          bestCandidateId={bestCandidateId}
          selectedId={selectedId}
          onSelect={onSelect}
        />
      </TabsContent>
      <TabsContent value="list" className="mt-0">
        <ul role="tree" aria-label={t('evolution.lineageList')} className="divide-y divide-border/70 border-y border-border/70">
          {orderedNodes.map((node) => {
            const context = t('evolution.candidateContext', {
              generation: node.generation + 1,
              island: node.island + 1,
              mutation: node.mutationType,
            })
            return (
              <li key={node.candidateId} role="none" className="min-w-0">
                <button
                  type="button"
                  ref={(element) => {
                    if (element) treeItemRefs.current.set(node.candidateId, element)
                    else treeItemRefs.current.delete(node.candidateId)
                  }}
                  role="treeitem"
                  tabIndex={node.candidateId === rovingTreeId ? 0 : -1}
                  aria-level={Math.max(1, node.generation + 1)}
                  aria-selected={node.candidateId === selectedId}
                  aria-label={[
                    t('evolution.selectCandidate', { candidate: node.candidateId }),
                    context,
                    `${t('evolution.fullFitness')} ${node.fitnessScore.toFixed(3)}`,
                    node.rejected ? t('evolution.infeasible') : t('evolution.feasible'),
                  ].join(', ')}
                  className="flex min-h-11 w-full min-w-0 items-center gap-3 px-3 py-2 text-start outline-none transition-colors hover:bg-muted/60 focus-visible:bg-muted focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring aria-selected:bg-muted/50 motion-reduce:transition-none"
                  onFocus={() => setFocusedTreeId(node.candidateId)}
                  onKeyDown={(event) => handleTreeKeyDown(event, node.candidateId)}
                  onClick={() => onSelect(node.candidateId)}
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium text-foreground" title={node.candidateId}>
                      {node.candidateId}
                    </span>
                    <span className="block truncate text-xs text-muted-foreground" title={context}>
                      {context}
                    </span>
                  </span>
                  <span className="shrink-0 text-end text-xs tabular-nums text-muted-foreground">
                    <span className="block font-semibold text-foreground">{node.fitnessScore.toFixed(3)}</span>
                    <span>{node.rejected ? t('evolution.infeasible') : t('evolution.feasible')}</span>
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      </TabsContent>
    </Tabs>
  )
}
