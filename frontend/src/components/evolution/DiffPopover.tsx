import { useTranslation } from 'react-i18next'
import { useMemo } from 'react'
import type { LineageNode } from '../../types/evolution'
import { mutationBg, mutationColor } from '../../types/evolution'
import { computePairDiff, computePopoverPosition } from '../../lib/diff-utils'
import type { DiffLine } from '../../lib/diff-utils'

interface DiffPopoverProps {
  candidateId: string
  x: number
  y: number
  containerWidth: number
  containerHeight: number
  lineageIndex: Map<string, LineageNode>
}

function DiffLineRow({ line }: { line: DiffLine }) {
  if (line.type === 'hunk') {
    return <div className="text-diff-hunk mt-1 mb-0.5">{line.content}</div>
  }
  if (line.type === 'add') {
    return (
      <div className="text-diff-add bg-diff-add-bg">+{line.content}</div>
    )
  }
  if (line.type === 'del') {
    return (
      <div className="text-diff-del bg-diff-del-bg line-through opacity-70">
        -{line.content}
      </div>
    )
  }
  return <div className="text-muted-foreground"> {line.content}</div>
}

export function DiffPopover({
  candidateId,
  x,
  y,
  containerWidth,
  containerHeight,
  lineageIndex,
}: DiffPopoverProps) {
  const { t } = useTranslation()
  const candidate = lineageIndex.get(candidateId)
  const { left, top } = computePopoverPosition(x, y, containerWidth, containerHeight)

  // Compute diff (memoized on candidateId since templates are immutable)
  const diffResult = useMemo(() => {
    if (!candidate || candidate.template === undefined) return null
    if (candidate.mutationType === 'seed') return { type: 'seed' as const }

    const parentId = candidate.parentIds[0]
    if (!parentId) return { type: 'no-parent' as const }

    const parent = lineageIndex.get(parentId)
    if (!parent || parent.template === undefined) return { type: 'no-parent-template' as const }

    const pairDiff = computePairDiff(candidate, parent)
    return { type: 'diff' as const, pairDiff }
  }, [candidate, lineageIndex])

  // No template data
  if (!candidate || candidate.template === undefined) {
    return (
      <div
        className="absolute pointer-events-none w-[min(400px,calc(100vw-2rem))] h-[300px] bg-background border border-border rounded-lg shadow-xl z-30 flex items-center justify-center"
        style={{ left: `${left}px`, top: `${top}px` }}
      >
        <p className="text-muted-foreground text-sm">{t('evolution.noTemplateData')}</p>
      </div>
    )
  }

  // Seed node: show full template preview
  if (diffResult?.type === 'seed') {
    return (
      <div
        className="absolute pointer-events-none w-[min(400px,calc(100vw-2rem))] h-[300px] bg-background border border-border rounded-lg shadow-xl z-30 flex flex-col overflow-hidden"
        style={{ left: `${left}px`, top: `${top}px` }}
      >
        <div className="flex items-center gap-2 px-3 py-2 bg-muted border-b border-border shrink-0">
          <span className="font-mono text-foreground text-xs font-bold">
            {candidate.candidateId}
          </span>
          <span
            className="text-[10px] px-1.5 py-0.5 rounded-full"
            style={{
              backgroundColor: mutationBg(candidate.mutationType),
              color: mutationColor(candidate.mutationType),
            }}
          >
            {candidate.mutationType}
          </span>
          <span className="text-score-positive font-bold text-xs ml-auto">
            {candidate.fitnessScore.toFixed(3)}
          </span>
        </div>
        <div className="overflow-y-auto max-h-[260px] px-3 py-2">
          <pre className="font-mono text-xs leading-relaxed text-foreground whitespace-pre-wrap">
            {candidate.template}
          </pre>
        </div>
      </div>
    )
  }

  // Parent template not available
  if (diffResult?.type === 'no-parent' || diffResult?.type === 'no-parent-template') {
    return (
      <div
        className="absolute pointer-events-none w-[min(400px,calc(100vw-2rem))] h-[300px] bg-background border border-border rounded-lg shadow-xl z-30 flex items-center justify-center"
        style={{ left: `${left}px`, top: `${top}px` }}
      >
        <p className="text-muted-foreground text-sm">{t('evolution.parentTemplateNotAvailable')}</p>
      </div>
    )
  }

  // Diff view
  if (diffResult?.type === 'diff') {
    const { pairDiff } = diffResult
    const addCount = pairDiff.lines.filter((l) => l.type === 'add').length
    const delCount = pairDiff.lines.filter((l) => l.type === 'del').length

    return (
      <div
        className="absolute pointer-events-none w-[min(400px,calc(100vw-2rem))] h-[300px] bg-background border border-border rounded-lg shadow-xl z-30 flex flex-col overflow-hidden"
        style={{ left: `${left}px`, top: `${top}px` }}
      >
        {/* Header */}
        <div className="flex items-center gap-2 px-3 py-2 bg-muted border-b border-border shrink-0">
          <span className="font-mono text-foreground text-xs font-bold">
            {candidate.candidateId.slice(0, 8)}
          </span>
          <span
            className="text-[10px] px-1.5 py-0.5 rounded-full"
            style={{
              backgroundColor: mutationBg(candidate.mutationType),
              color: mutationColor(candidate.mutationType),
            }}
          >
            {candidate.mutationType}
          </span>
          <span className="text-score-positive font-bold text-xs">
            {candidate.fitnessScore.toFixed(3)}
          </span>
          {(addCount > 0 || delCount > 0) && (
            <span className="text-xs text-muted-foreground ml-auto font-mono">
              +{addCount} -{delCount}
            </span>
          )}
        </div>

        {/* Diff body */}
        <div className="overflow-y-auto font-mono text-[11px] leading-relaxed px-3 py-2">
          {pairDiff.lines.map((line, i) => (
            <DiffLineRow key={i} line={line} />
          ))}
        </div>
      </div>
    )
  }

  return null
}
