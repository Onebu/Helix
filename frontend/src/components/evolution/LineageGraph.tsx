import { useMemo, useState, useRef, useCallback } from 'react'
import type { LineageNode } from '../../types/evolution'
import { MUTATION_COLORS, mutationBg, mutationColor, SCORE_POSITIVE } from '../../types/evolution'
import { fitnessColor, REJECTED_OPACITY, ACTIVE_OPACITY, getDotRadius } from '../../lib/scoring'
import { traceWinningPath, deduplicateEvents } from '../../lib/lineage-utils'
import { computePairDiff } from '../../lib/diff-utils'
import type { DiffLine } from '../../lib/diff-utils'

interface LineageGraphProps {
  lineageEvents: LineageNode[]
  bestCandidateId: string | null
}

interface LayoutNode {
  id: string
  parentIds: string[]
  generation: number
  island: number
  fitnessScore: number
  rejected: boolean
  mutationType: string
  isWinning: boolean
  isBest: boolean
  x: number
  y: number
  radius: number
}

interface LayoutEdge {
  sourceId: string
  targetId: string
  isWinning: boolean
  isMigration: boolean
}

// Layout
const ROW_HEIGHT = 80
const NODE_GAP = 44
const PADDING_X = 70
const PADDING_Y = 50
const LABEL_WIDTH = 56

function DiffLineRow({ line }: { line: DiffLine }) {
  if (line.type === 'hunk') {
    return <div className="text-diff-hunk mt-1 mb-0.5">{line.content}</div>
  }
  if (line.type === 'add') {
    return <div className="text-diff-add bg-diff-add-bg">+{line.content}</div>
  }
  if (line.type === 'del') {
    return <div className="text-diff-del bg-diff-del-bg line-through opacity-70">-{line.content}</div>
  }
  return <div className="text-muted-foreground"> {line.content}</div>
}

export default function LineageGraph({ lineageEvents, bestCandidateId }: LineageGraphProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [tooltip, setTooltip] = useState<{ x: number; y: number; node: LayoutNode } | null>(null)
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)

  // Build lineage index for diff computation
  const lineageIndex = useMemo(() => {
    const map = new Map<string, LineageNode>()
    for (const e of lineageEvents) map.set(e.candidateId, e)
    return map
  }, [lineageEvents])

  // Layout computation
  const { nodes, edges, svgWidth, svgHeight, genLabels } = useMemo(() => {
    const deduped = deduplicateEvents(lineageEvents)
    if (deduped.length === 0) return { nodes: [], edges: [], svgWidth: 400, svgHeight: 200, genLabels: [] }

    const winning = traceWinningPath(deduped, bestCandidateId)

    // Derive depth from parent chain
    const depedIdx = new Map<string, LineageNode>(deduped.map(e => [e.candidateId, e]))
    const depthCache = new Map<string, number>()

    function computeDepth(id: string, visited: Set<string> = new Set()): number {
      if (depthCache.has(id)) return depthCache.get(id)!
      if (visited.has(id)) return 0
      visited.add(id)
      const e = depedIdx.get(id)
      if (!e || e.parentIds.length === 0) { depthCache.set(id, 0); return 0 }
      let maxParentDepth = 0
      for (const pid of e.parentIds) {
        if (depedIdx.has(pid)) maxParentDepth = Math.max(maxParentDepth, computeDepth(pid, visited))
      }
      const parent = e.parentIds.length > 0 ? depedIdx.get(e.parentIds[0]) : null
      const isClone = parent && e.template != null && parent.template != null
        && e.template.trim() === parent.template.trim()
      const d = isClone ? maxParentDepth : maxParentDepth + 1
      depthCache.set(id, d)
      return d
    }
    for (const e of deduped) computeDepth(e.candidateId)

    const byDepth = new Map<number, LineageNode[]>()
    for (const e of deduped) {
      const d = depthCache.get(e.candidateId) ?? 0
      if (!byDepth.has(d)) byDepth.set(d, [])
      byDepth.get(d)!.push(e)
    }
    const sortedDepths = [...byDepth.keys()].sort((a, b) => a - b)

    const nodeMap = new Map<string, LayoutNode>()
    const nodeArray: LayoutNode[] = []

    for (const e of deduped) {
      const depth = depthCache.get(e.candidateId) ?? 0
      const node: LayoutNode = {
        id: e.candidateId,
        parentIds: e.parentIds,
        generation: depth,
        island: e.island,
        fitnessScore: e.fitnessScore,
        rejected: e.rejected,
        mutationType: e.mutationType,
        isWinning: winning.has(e.candidateId),
        isBest: e.candidateId === bestCandidateId,
        x: 0, y: 0,
        radius: getDotRadius(e.fitnessScore),
      }
      nodeMap.set(e.candidateId, node)
      nodeArray.push(node)
    }

    const genLabelsArr: Array<{ label: string; y: number }> = []
    const maxRowSize = Math.max(...[...byDepth.values()].map(g => g.length), 1)

    for (let di = 0; di < sortedDepths.length; di++) {
      const depth = sortedDepths[di]
      const depthNodes = nodeArray.filter(n => n.generation === depth)
      const y = PADDING_Y + di * ROW_HEIGHT

      depthNodes.sort((a, b) => {
        if (a.isWinning !== b.isWinning) return a.isWinning ? -1 : 1
        return avgParentX(a, nodeMap) - avgParentX(b, nodeMap)
      })

      const rowWidth = (depthNodes.length - 1) * NODE_GAP
      const maxWidth = (maxRowSize - 1) * NODE_GAP
      const startX = PADDING_X + LABEL_WIDTH + (maxWidth - rowWidth) / 2

      for (let i = 0; i < depthNodes.length; i++) {
        depthNodes[i].x = startX + i * NODE_GAP
        depthNodes[i].y = y
      }

      const isSeed = depth === 0 && depthNodes.some(n => n.mutationType === 'seed' || n.mutationType === 'seed_variant')
      // Use actual generation numbers from lineage data for labels (not computed depth)
      // to stay in sync with the fitness chart which uses generation_records
      if (isSeed) {
        genLabelsArr.push({ label: 'Seed', y })
      } else {
        const actualGens = depthNodes.map(n => depedIdx.get(n.id)?.generation ?? 0)
        const maxActualGen = Math.max(...actualGens, 0)
        const genNum = maxActualGen + 1
        // Count how many rows already exist for this generation
        const existing = genLabelsArr.filter(l => l.label.startsWith(`Gen ${genNum}`))
        if (existing.length === 0) {
          genLabelsArr.push({ label: `Gen ${genNum}`, y })
        } else {
          // Multiple depth levels within same generation: use a/b/c suffix
          if (existing.length === 1 && !existing[0].label.includes('.')) {
            existing[0].label = `Gen ${genNum}.1`
          }
          genLabelsArr.push({ label: `Gen ${genNum}.${existing.length + 1}`, y })
        }
      }
    }

    const edgeArray: LayoutEdge[] = []
    for (const e of deduped) {
      for (const pid of e.parentIds) {
        if (nodeMap.has(pid)) {
          const parent = nodeMap.get(pid)!
          edgeArray.push({
            sourceId: pid,
            targetId: e.candidateId,
            isWinning: winning.has(pid) && winning.has(e.candidateId),
            isMigration: parent.island !== e.island,
          })
        }
      }
    }

    const maxX = Math.max(...nodeArray.map(n => n.x)) + PADDING_X
    const maxY = Math.max(...nodeArray.map(n => n.y)) + PADDING_Y

    return {
      nodes: nodeArray, edges: edgeArray,
      svgWidth: Math.max(400, maxX + PADDING_X),
      svgHeight: Math.max(200, maxY + PADDING_Y),
      genLabels: genLabelsArr,
    }
  }, [lineageEvents, bestCandidateId])

  // Compute diff for selected node
  const selectedDiff = useMemo(() => {
    if (!selectedNodeId) return null
    const candidate = lineageIndex.get(selectedNodeId)
    if (!candidate || candidate.template === undefined) return null

    if (candidate.mutationType === 'seed' || candidate.parentIds.length === 0) {
      return { type: 'seed' as const, candidate, template: candidate.template }
    }

    const parent = lineageIndex.get(candidate.parentIds[0])
    if (!parent || parent.template === undefined) return { type: 'seed' as const, candidate, template: candidate.template }

    if (candidate.template.trim() === parent.template.trim()) {
      return { type: 'clone' as const, candidate, parent }
    }

    const pairDiff = computePairDiff(candidate, parent)
    return { type: 'diff' as const, candidate, parent, pairDiff }
  }, [selectedNodeId, lineageIndex])

  const handleNodeEnter = useCallback((node: LayoutNode, event: React.MouseEvent) => {
    const container = containerRef.current
    if (!container) return
    const rect = container.getBoundingClientRect()
    setTooltip({ x: event.clientX - rect.left, y: event.clientY - rect.top, node })
  }, [])

  const handleNodeLeave = useCallback(() => { setTooltip(null) }, [])

  const handleNodeClick = useCallback((node: LayoutNode) => {
    setSelectedNodeId(prev => prev === node.id ? null : node.id)
  }, [])

  const nodePos = useMemo(() => {
    const map = new Map<string, { x: number; y: number }>()
    for (const n of nodes) map.set(n.id, { x: n.x, y: n.y })
    return map
  }, [nodes])

  if (lineageEvents.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-card/50 p-8 text-center text-muted-foreground">
        No lineage data
      </div>
    )
  }

  const regularEdges = edges.filter(e => !e.isWinning)
  const winningEdges = edges.filter(e => e.isWinning)

  return (
    <div className="rounded-lg border border-border bg-card">
      {/* Header + Legend */}
      <div className="sticky top-0 z-10 flex items-center gap-4 px-4 py-3 border-b border-border bg-card/95 backdrop-blur-sm text-xs text-muted-foreground">
        <h3 className="text-sm font-semibold text-foreground shrink-0">Evolution Lineage</h3>
        <span className="text-border">|</span>
        {Object.entries(MUTATION_COLORS).map(([type, color]) => (
          <span key={type} className="inline-flex items-center gap-1.5">
            <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ backgroundColor: color }} />
            {type}
          </span>
        ))}
        <span className="ml-auto inline-flex items-center gap-1.5">
          <span className="inline-block w-4 h-0.5 bg-score-positive rounded" />
          winning path
        </span>
      </div>

      {/* Graph area (scrollable) */}
      <div ref={containerRef} className="relative overflow-auto max-h-[min(450px,60vh)]">
        <svg
          width={svgWidth}
          height={svgHeight}
          viewBox={`0 0 ${svgWidth} ${svgHeight}`}
          className="block"
        >
          {/* Generation labels */}
          {genLabels.map((gl, i) => (
            <text key={i} x={PADDING_X - 4} y={gl.y + 4} textAnchor="end" className="fill-muted-foreground text-[11px] font-medium">
              {gl.label}
            </text>
          ))}

          {/* Generation row guides */}
          {genLabels.map((gl, i) => (
            <line key={`guide-${i}`} x1={PADDING_X + LABEL_WIDTH - 20} y1={gl.y} x2={svgWidth - PADDING_X} y2={gl.y}
              stroke="currentColor" className="text-border" strokeWidth={1} opacity={0.3} />
          ))}

          {/* Regular edges */}
          {regularEdges.map((edge, i) => {
            const src = nodePos.get(edge.sourceId)
            const tgt = nodePos.get(edge.targetId)
            if (!src || !tgt) return null
            const midY = (src.y + tgt.y) / 2
            const path = `M ${src.x} ${src.y} C ${src.x} ${midY}, ${tgt.x} ${midY}, ${tgt.x} ${tgt.y}`
            return (
              <path key={`edge-${i}`} d={path} fill="none"
                stroke={edge.isMigration ? MUTATION_COLORS.fresh : 'currentColor'}
                className={edge.isMigration ? '' : 'text-border'}
                strokeWidth={edge.isMigration ? 1.5 : 1}
                strokeDasharray={edge.isMigration ? '4 3' : undefined}
                opacity={0.4} />
            )
          })}

          {/* Winning edges */}
          {winningEdges.map((edge, i) => {
            const src = nodePos.get(edge.sourceId)
            const tgt = nodePos.get(edge.targetId)
            if (!src || !tgt) return null
            const midY = (src.y + tgt.y) / 2
            const path = `M ${src.x} ${src.y} C ${src.x} ${midY}, ${tgt.x} ${midY}, ${tgt.x} ${tgt.y}`
            return (
              <g key={`winning-${i}`}>
                <path d={path} fill="none" stroke={SCORE_POSITIVE} strokeWidth={6} opacity={0.15} strokeLinecap="round" />
                <path d={path} fill="none" stroke={SCORE_POSITIVE} strokeWidth={2.5} opacity={0.9} strokeLinecap="round" />
              </g>
            )
          })}

          {/* Nodes */}
          {nodes.map((node) => {
            const color = mutationColor(node.mutationType)
            const fitColor = fitnessColor(node.fitnessScore) as string
            const opacity = node.rejected ? REJECTED_OPACITY : ACTIVE_OPACITY
            const r = node.radius
            const isSelected = node.id === selectedNodeId

            return (
              <g key={node.id}>
                {node.isWinning && (
                  <circle cx={node.x} cy={node.y} r={r + 5} fill="none" stroke={SCORE_POSITIVE} strokeWidth={2} opacity={0.3} />
                )}
                {node.isBest && (
                  <circle cx={node.x} cy={node.y} r={r + 8} fill="none" stroke={SCORE_POSITIVE} strokeWidth={2.5} strokeDasharray="3 2" opacity={0.6} />
                )}
                {isSelected && (
                  <circle cx={node.x} cy={node.y} r={r + 6} fill="none" stroke="currentColor" className="text-foreground" strokeWidth={2} opacity={0.8} />
                )}
                <circle cx={node.x} cy={node.y} r={r + 2} fill={fitColor} opacity={opacity * 0.25} />
                <circle cx={node.x} cy={node.y} r={r} fill={color} opacity={opacity}
                  stroke={fitColor} strokeWidth={1.5}
                  style={{ cursor: 'pointer' }}
                  onMouseEnter={(e) => handleNodeEnter(node, e)}
                  onMouseLeave={handleNodeLeave}
                  onClick={() => handleNodeClick(node)}
                />
              </g>
            )
          })}
        </svg>

        {/* Tooltip */}
        {tooltip && (
          <div className="absolute pointer-events-none z-20 bg-popover text-popover-foreground text-xs px-3 py-2 rounded-md border border-border shadow-lg whitespace-nowrap"
            style={{ left: tooltip.x + 12, top: tooltip.y - 10 }}>
            <div className="font-mono font-bold">{tooltip.node.id.slice(0, 8)}</div>
            <div className="flex items-center gap-2 mt-1">
              <span className="inline-block w-2 h-2 rounded-full" style={{ backgroundColor: mutationColor(tooltip.node.mutationType) }} />
              <span>{tooltip.node.mutationType}</span>
            </div>
            <div className="mt-1">Fitness: <span className="font-mono font-semibold">{tooltip.node.fitnessScore.toFixed(3)}</span></div>
            <div>Gen {tooltip.node.generation} | Island {tooltip.node.island}</div>
            {tooltip.node.rejected && <div className="text-destructive mt-0.5">Rejected</div>}
            {tooltip.node.isBest && <div className="text-score-positive font-semibold mt-0.5">Best candidate</div>}
            <div className="text-muted-foreground mt-1 border-t border-border pt-1">Click to view diff</div>
          </div>
        )}
      </div>

      {/* Diff panel (below graph, fully interactive and scrollable) */}
      {selectedDiff && (
        <div className="border-t border-border">
          {/* Diff header */}
          <div className="flex items-center gap-3 px-4 py-2 bg-muted">
            <span className="font-mono text-foreground text-xs font-bold">
              {selectedDiff.candidate.candidateId.slice(0, 8)}
            </span>
            <span className="text-[10px] px-1.5 py-0.5 rounded-full"
              style={{
                backgroundColor: mutationBg(selectedDiff.candidate.mutationType),
                color: mutationColor(selectedDiff.candidate.mutationType),
              }}>
              {selectedDiff.candidate.mutationType}
            </span>
            <span className="text-score-positive font-bold text-xs">
              {selectedDiff.candidate.fitnessScore.toFixed(3)}
            </span>
            {selectedDiff.type === 'diff' && (
              <span className="text-xs text-muted-foreground font-mono ml-1">
                +{selectedDiff.pairDiff.lines.filter(l => l.type === 'add').length}{' '}
                -{selectedDiff.pairDiff.lines.filter(l => l.type === 'del').length}
              </span>
            )}
            <button onClick={() => setSelectedNodeId(null)}
              className="ml-auto text-xs text-muted-foreground hover:text-foreground transition-colors px-2 py-1 rounded hover:bg-accent">
              Close
            </button>
          </div>

          {/* Diff body */}
          <div className="px-4 py-3 max-h-[300px] overflow-y-auto">
            {selectedDiff.type === 'seed' && (
              <pre className="font-mono text-xs leading-relaxed text-foreground whitespace-pre-wrap">
                {selectedDiff.template}
              </pre>
            )}
            {selectedDiff.type === 'clone' && (
              <p className="text-sm text-muted-foreground py-4 text-center">
                Identical template to parent {selectedDiff.parent.candidateId.slice(0, 8)} (island distribution clone)
              </p>
            )}
            {selectedDiff.type === 'diff' && (
              <div className="font-mono text-[11px] leading-relaxed">
                {selectedDiff.pairDiff.lines.map((line, i) => (
                  <DiffLineRow key={i} line={line} />
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

function avgParentX(node: LayoutNode, nodeMap: Map<string, LayoutNode>): number {
  const xs: number[] = []
  for (const pid of node.parentIds) {
    const parent = nodeMap.get(pid)
    if (parent) xs.push(parent.x)
  }
  return xs.length > 0 ? xs.reduce((a, b) => a + b, 0) / xs.length : 0
}
