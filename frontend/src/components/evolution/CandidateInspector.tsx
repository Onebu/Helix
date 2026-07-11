import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { computePairDiff } from '@/lib/diff-utils'
import type { CandidateData, LineageNode } from '@/types/evolution'

type InspectableCandidate = CandidateData | LineageNode

interface ModelInfo {
  metaModel: string | null
  metaProvider: string | null
  targetModel: string | null
  targetProvider: string | null
  judgeModel: string | null
  judgeProvider: string | null
}

interface CandidateInspectorProps {
  candidate: InspectableCandidate | null
  parent?: InspectableCandidate | null
  modelInfo: ModelInfo
  embedded?: boolean
}

function modelLabel(provider: string | null, model: string | null) {
  return model ? [provider, model].filter(Boolean).join('/') : null
}

export default function CandidateInspector({
  candidate,
  parent,
  modelInfo,
  embedded = false,
}: CandidateInspectorProps) {
  const { t } = useTranslation()
  const [showDiff, setShowDiff] = useState(false)

  const diffLines = useMemo(() => {
    if (!showDiff || !candidate?.template || !parent?.template) return []
    return computePairDiff(candidate as LineageNode, parent as LineageNode).lines
  }, [candidate, parent, showDiff])

  const models = [
    [t('evolution.targetModel'), modelLabel(modelInfo.targetProvider, modelInfo.targetModel)],
    [t('evolution.metaModel'), modelLabel(modelInfo.metaProvider, modelInfo.metaModel)],
    [t('evolution.judgeModel'), modelLabel(modelInfo.judgeProvider, modelInfo.judgeModel)],
  ].filter((entry): entry is [string, string] => Boolean(entry[1]))

  const Root = embedded ? 'div' : 'aside'

  return (
    <Root
      aria-label={embedded ? undefined : t('evolution.candidateInspector')}
      className={embedded ? 'min-w-0' : 'min-w-0 border-l border-border/70 pl-5'}
    >
      <div className={embedded ? 'min-w-0' : 'sticky top-4'}>
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
          {t('evolution.candidateInspector')}
        </p>

        {!candidate ? (
          <div className="mt-6 border-l-2 border-primary/40 pl-4">
            <p className="font-medium text-foreground">{t('evolution.noCandidateSelected')}</p>
            <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
              {t('evolution.selectCandidateHint')}
            </p>
          </div>
        ) : (
          <div className="mt-4 space-y-6">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h2 className="min-w-0 truncate text-lg font-semibold text-foreground" title={candidate.candidateId}>
                  {candidate.candidateId}
                </h2>
                <Badge
                  variant="outline"
                  className={candidate.rejected
                    ? 'border-destructive/30 text-destructive'
                    : 'border-primary/30 text-primary'}
                >
                  {candidate.rejected ? t('evolution.infeasible') : t('evolution.feasible')}
                </Badge>
              </div>
              <p className="mt-1 break-words text-sm text-muted-foreground">
                {t('evolution.candidateContext', {
                  generation: candidate.generation,
                  island: candidate.island + 1,
                  mutation: candidate.mutationType,
                })}
              </p>
            </div>

            <dl className="grid grid-cols-2 gap-x-4 gap-y-4 border-y border-border/70 py-4 text-sm">
              <div>
                <dt className="text-muted-foreground">{t('evolution.fullFitness')}</dt>
                <dd className="mt-1 font-semibold tabular-nums text-foreground">
                  {candidate.fitnessScore.toFixed(3)}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">{t('evolution.normalizedFitness')}</dt>
                <dd className="mt-1 font-semibold tabular-nums text-foreground">
                  {candidate.normalizedScore.toFixed(3)}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">{t('evolution.fullSuiteCoverage')}</dt>
                <dd className="mt-1 font-semibold tabular-nums text-foreground">
                  {candidate.casesPassed != null && candidate.totalCases != null
                    ? `${candidate.casesPassed} / ${candidate.totalCases}`
                    : t('evolution.notAvailable')}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground">{t('evolution.parents')}</dt>
                <dd className="mt-1 font-semibold tabular-nums text-foreground">
                  {t('evolution.parentCount', { count: candidate.parentIds?.length ?? 0 })}
                </dd>
              </div>
            </dl>

            {models.length > 0 && (
              <div>
                <h3 className="text-sm font-semibold text-foreground">{t('evolution.runModels')}</h3>
                <dl className="mt-2 space-y-2 text-sm">
                  {models.map(([label, value]) => (
                    <div key={label} className="min-w-0">
                      <dt className="text-xs text-muted-foreground">{label}</dt>
                      <dd className="truncate text-foreground" title={value}>{value}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            )}

            <div>
              <h3 className="text-sm font-semibold text-foreground">{t('evolution.promptPreview')}</h3>
              {candidate.template ? (
                <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap break-words border-y border-border/70 py-3 text-xs leading-relaxed text-foreground">
                  {candidate.template}
                </pre>
              ) : (
                <p className="mt-2 text-sm text-muted-foreground">{t('evolution.noTemplateData')}</p>
              )}
            </div>

            {parent?.template && candidate.template && (
              <div>
                <Button
                  type="button"
                  variant="outline"
                  className="w-full"
                  aria-expanded={showDiff}
                  onClick={() => setShowDiff((value) => !value)}
                >
                  {showDiff ? t('evolution.hideParentDiff') : t('evolution.viewParentDiff')}
                </Button>
                {showDiff && (
                  <div className="mt-3 max-h-64 overflow-auto border-y border-border/70 py-3 font-mono text-[11px] leading-relaxed">
                    {diffLines.length > 0 ? diffLines.map((line, index) => (
                      <div
                        key={`${line.type}-${index}`}
                        className={line.type === 'add'
                          ? 'bg-diff-add-bg text-diff-add'
                          : line.type === 'del'
                            ? 'bg-diff-del-bg text-diff-del'
                            : line.type === 'hunk'
                              ? 'text-diff-hunk'
                              : 'text-muted-foreground'}
                      >
                        {line.type === 'add' ? '+' : line.type === 'del' ? '-' : ' '}{line.content}
                      </div>
                    )) : (
                      <p className="font-sans text-sm text-muted-foreground">{t('evolution.noPromptChanges')}</p>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </Root>
  )
}
