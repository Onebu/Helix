import { useMemo, useState, useRef, useEffect, useCallback } from 'react'
import type { LineageNode } from '../../types/evolution'
import { MUTATION_COLORS } from '../../types/evolution'
import { fitnessColor, REJECTED_OPACITY, ACTIVE_OPACITY, getDotRadius } from '../../lib/scoring'
import { traceWinningPath, deduplicateEvents } from '../../lib/lineage-utils'
import { DiffPopover } from './DiffPopover'

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
const PADDING_X = 60
const PADDING_Y = 50
const LABEL_WIDTH = 48

export default function LineageGraph({ lineageEvents, bestCandidateId }: LineageGraphProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [containerDims, setContainerDims] = useState({ width: 800, height: 500 })
  const [tooltip, setTooltip] = useState<{ x: number; y: number; node: LayoutNode } | null>(null)

  // DiffPopover hover state
  const hoverTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [hoverTarget, setHoverTarget] = useState<{ candidateId: string; x: number; y: number } | null>(null)

  const lineageIndex = useMemo(() => {
    const map = new Map<string, LineageNode>()
    for (const e of lineageEvents) map.set(e.candidateId, e)
    return map
  }, [lineageEvents])

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const ro = new ResizeObserver(() => {
      setContainerDims({ width: el.clientWidth, height: el.clientHeight })
    })
    ro.observe(el)
    setContainerDims({ width: el.clientWidth, height: el.clientHeight })
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    return () => { if (hoverTimerRef.current) clearTimeout(hoverTimerRef.current) }
  }, [])

  // Layout computation
  const { nodes, edges, svgWidth, svgHeight, genLabels } = useMemo(() => {
    const deduped = deduplicateEvents(lineageEvents)
    if (deduped.length === 0) return { nodes: [], edges: [], svgWidth: 400, svgHeight: 200, genLabels: [] }

    const winning = traceWinningPath(deduped, bestCandidateId)

    // Derive depth from parent chain (the `generation` field may be flat/0 for all events)
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
      // Clones (identical template to parent) stay at the same depth as parent
      // This collapses island-distribution clones into the same generation row
      const parent = e.parentIds.length > 0 ? depedIdx.get(e.parentIds[0]) : null
      const isClone = parent && e.template !== undefined && parent.template !== undefined
        && e.template.trim() === parent.template.trim()
      const d = isClone ? maxParentDepth : maxParentDepth + 1
      depthCache.set(id, d)
      return d
    }
    for (const e of deduped) computeDepth(e.candidateId)

    // Group by depth
    const byDepth = new Map<number, LineageNode[]>()
    for (const e of deduped) {
      const d = depthCache.get(e.candidateId) ?? 0
      if (!byDepth.has(d)) byDepth.set(d, [])
      byDepth.get(d)!.push(e)
    }
    const sortedDepths = [...byDepth.keys()].sort((a, b) => a - b)

    // Build node map first for parent-position alignment
    const nodeMap = new Map<string, LayoutNode>()
    const nodeArray: LayoutNode[] = []

    // First pass: create nodes with placeholder x
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
        x: 0,
        y: 0,
        radius: getDotRadius(e.fitnessScore),
      }
      nodeMap.set(e.candidateId, node)
      nodeArray.push(node)
    }

    // Second pass: compute positions depth by depth
    const genLabelsArr: Array<{ label: string; y: number }> = []
    const maxRowSize = Math.max(...[...byDepth.values()].map(g => g.length), 1)

    for (let di = 0; di < sortedDepths.length; di++) {
      const depth = sortedDepths[di]
      const depthNodes = nodeArray.filter(n => n.generation === depth)
      const y = PADDING_Y + di * ROW_HEIGHT

      // Sort: winning nodes toward center, then by parent X average
      depthNodes.sort((a, b) => {
        if (a.isWinning !== b.isWinning) return a.isWinning ? -1 : 1
        const aParentX = avgParentX(a, nodeMap)
        const bParentX = avgParentX(b, nodeMap)
        return aParentX - bParentX
      })

      const rowWidth = (depthNodes.length - 1) * NODE_GAP
      const maxWidth = (maxRowSize - 1) * NODE_GAP
      const startX = PADDING_X + LABEL_WIDTH + (maxWidth - rowWidth) / 2

      for (let i = 0; i < depthNodes.length; i++) {
        depthNodes[i].x = startX + i * NODE_GAP
        depthNodes[i].y = y
      }

      const isSeed = depth === 0 && depthNodes.some(n => n.mutationType === 'seed' || n.mutationType === 'seed_variant')
      genLabelsArr.push({ label: isSeed ? 'Seed' : `Gen ${depth}`, y })
    }

    // Build edges
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

    // Compute SVG dimensions
    const maxX = Math.max(...nodeArray.map(n => n.x)) + PADDING_X
    const maxY = Math.max(...nodeArray.map(n => n.y)) + PADDING_Y
    const width = Math.max(400, maxX + PADDING_X)
    const height = Math.max(200, maxY + PADDING_Y)

    return { nodes: nodeArray, edges: edgeArray, svgWidth: width, svgHeight: height, genLabels: genLabelsArr }
  }, [lineageEvents, bestCandidateId])

  const handleNodeEnter = useCallback((node: LayoutNode, event: React.MouseEvent) => {
    const container = containerRef.current
    if (!container) return
    const rect = container.getBoundingClientRect()
    const x = event.clientX - rect.left
    const y = event.clientY - rect.top

    setTooltip({ x, y, node })
    if (hoverTimerRef.current) clearTimeout(hoverTimerRef.current)
    if (lineageIndex.has(node.id)) {
      hoverTimerRef.current = setTimeout(() => {
        setHoverTarget({ candidateId: node.id, x, y })
      }, 300)
    }
  }, [lineageIndex])

  const handleNodeLeave = useCallback(() => {
    setTooltip(null)
    if (hoverTimerRef.current) clearTimeout(hoverTimerRef.current)
    setHoverTarget(null)
  }, [])

  // Node position lookup
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

  // Separate edges: winning on top
  const regularEdges = edges.filter(e => !e.isWinning)
  const winningEdges = edges.filter(e => e.isWinning)

  return (
    <div ref={containerRef} className="rounded-lg border border-border bg-card relative overflow-auto" style={{ maxHeight: 600 }}>
      {/* Legend */}
      <div className="sticky top-0 z-10 flex items-center gap-4 px-4 py-2 border-b border-border bg-card/95 backdrop-blur-sm text-xs text-muted-foreground">
        <span className="font-medium text-foreground">Mutation types:</span>
        {Object.entries(MUTATION_COLORS).map(([type, color]) => (
          <span key={type} className="inline-flex items-center gap-1.5">
            <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ backgroundColor: color }} />
            {type}
          </span>
        ))}
        <span className="ml-auto inline-flex items-center gap-1.5">
          <span className="inline-block w-4 h-0.5 bg-emerald-500 rounded" />
          winning path
        </span>
      </div>

      <svg
        width={svgWidth}
        height={svgHeight}
        viewBox={`0 0 ${svgWidth} ${svgHeight}`}
        className="block"
      >
        {/* Generation labels */}
        {genLabels.map((gl, i) => (
          <text
            key={i}
            x={PADDING_X - 4}
            y={gl.y + 4}
            textAnchor="end"
            className="fill-muted-foreground text-[11px] font-medium"
          >
            {gl.label}
          </text>
        ))}

        {/* Generation row guides */}
        {genLabels.map((gl, i) => (
          <line
            key={`guide-${i}`}
            x1={PADDING_X + LABEL_WIDTH - 20}
            y1={gl.y}
            x2={svgWidth - PADDING_X}
            y2={gl.y}
            stroke="currentColor"
            className="text-border"
            strokeWidth={1}
            opacity={0.3}
          />
        ))}

        {/* Regular edges (drawn first, behind winning) */}
        {regularEdges.map((edge, i) => {
          const src = nodePos.get(edge.sourceId)
          const tgt = nodePos.get(edge.targetId)
          if (!src || !tgt) return null

          const midY = (src.y + tgt.y) / 2
          const path = `M ${src.x} ${src.y} C ${src.x} ${midY}, ${tgt.x} ${midY}, ${tgt.x} ${tgt.y}`

          return (
            <path
              key={`edge-${i}`}
              d={path}
              fill="none"
              stroke={edge.isMigration ? '#8b5cf6' : 'currentColor'}
              className={edge.isMigration ? '' : 'text-border'}
              strokeWidth={edge.isMigration ? 1.5 : 1}
              strokeDasharray={edge.isMigration ? '4 3' : undefined}
              opacity={0.4}
            />
          )
        })}

        {/* Winning edges (drawn on top) */}
        {winningEdges.map((edge, i) => {
          const src = nodePos.get(edge.sourceId)
          const tgt = nodePos.get(edge.targetId)
          if (!src || !tgt) return null

          const midY = (src.y + tgt.y) / 2
          const path = `M ${src.x} ${src.y} C ${src.x} ${midY}, ${tgt.x} ${midY}, ${tgt.x} ${tgt.y}`

          return (
            <g key={`winning-${i}`}>
              {/* Glow */}
              <path
                d={path}
                fill="none"
                stroke="#22c55e"
                strokeWidth={6}
                opacity={0.15}
                strokeLinecap="round"
              />
              {/* Main stroke */}
              <path
                d={path}
                fill="none"
                stroke="#22c55e"
                strokeWidth={2.5}
                opacity={0.9}
                strokeLinecap="round"
              />
            </g>
          )
        })}

        {/* Nodes */}
        {nodes.map((node) => {
          const color = MUTATION_COLORS[node.mutationType] ?? '#64748b'
          const fitColor = fitnessColor(node.fitnessScore) as string
          const opacity = node.rejected ? REJECTED_OPACITY : ACTIVE_OPACITY
          const r = node.radius

          return (
            <g key={node.id}>
              {/* Winning glow ring */}
              {node.isWinning && (
                <circle
                  cx={node.x}
                  cy={node.y}
                  r={r + 5}
                  fill="none"
                  stroke="#22c55e"
                  strokeWidth={2}
                  opacity={0.3}
                />
              )}
              {/* Best candidate highlight */}
              {node.isBest && (
                <circle
                  cx={node.x}
                  cy={node.y}
                  r={r + 8}
                  fill="none"
                  stroke="#22c55e"
                  strokeWidth={2.5}
                  strokeDasharray="3 2"
                  opacity={0.6}
                />
              )}
              {/* Fitness outer ring */}
              <circle
                cx={node.x}
                cy={node.y}
                r={r + 2}
                fill={fitColor}
                opacity={opacity * 0.25}
              />
              {/* Main node */}
              <circle
                cx={node.x}
                cy={node.y}
                r={r}
                fill={color}
                opacity={opacity}
                stroke={fitColor}
                strokeWidth={1.5}
                style={{ cursor: 'pointer' }}
                onMouseEnter={(e) => handleNodeEnter(node, e)}
                onMouseLeave={handleNodeLeave}
              />
            </g>
          )
        })}
      </svg>

      {/* Tooltip overlay */}
      {tooltip && (
        <div
          className="absolute pointer-events-none z-20 bg-popover text-popover-foreground text-xs px-3 py-2 rounded-md border border-border shadow-lg whitespace-nowrap"
          style={{
            left: tooltip.x + 12,
            top: tooltip.y - 10,
          }}
        >
          <div className="font-mono font-bold">{tooltip.node.id.slice(0, 8)}</div>
          <div className="flex items-center gap-2 mt-1">
            <span
              className="inline-block w-2 h-2 rounded-full"
              style={{ backgroundColor: MUTATION_COLORS[tooltip.node.mutationType] ?? '#64748b' }}
            />
            <span>{tooltip.node.mutationType}</span>
          </div>
          <div className="mt-1">Fitness: <span className="font-mono font-semibold">{tooltip.node.fitnessScore.toFixed(3)}</span></div>
          <div>Gen {tooltip.node.generation} | Island {tooltip.node.island}</div>
          {tooltip.node.rejected && <div className="text-destructive mt-0.5">Rejected</div>}
          {tooltip.node.isBest && <div className="text-emerald-500 font-semibold mt-0.5">Best candidate</div>}
        </div>
      )}

      {/* DiffPopover */}
      {hoverTarget && lineageEvents.length > 0 && (
        <DiffPopover
          candidateId={hoverTarget.candidateId}
          x={hoverTarget.x}
          y={hoverTarget.y}
          containerWidth={containerDims.width}
          containerHeight={containerDims.height}
          lineageIndex={lineageIndex}
        />
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
