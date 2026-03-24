import { useTranslation } from 'react-i18next'
import { useState, useMemo, Fragment } from 'react'
import type { CaseResultData } from '../../types/evolution'
import { scoreColor } from '../../lib/scoring'

interface CaseResultsGridProps {
  caseResults: CaseResultData[]
  seedCaseResults?: CaseResultData[]
  caseNames?: Map<string, string>
}

const TIER_STYLES: Record<string, string> = {
  critical: 'bg-red-500/20 text-red-400',
  normal: 'bg-blue-500/20 text-blue-400',
  low: 'bg-slate-500/20 text-slate-400',
}

const TIER_PRIORITY: Record<string, number> = {
  critical: 0,
  normal: 1,
  low: 2,
}

function truncate(text: string, max: number): string {
  if (text.length <= max) return text
  return text.slice(0, max) + '...'
}

function PassIcon({ caseId }: { caseId: string }) {
  return (
    <svg
      data-testid={`result-pass-${caseId}`}
      className="h-5 w-5 text-emerald-400"
      fill="none"
      viewBox="0 0 24 24"
      strokeWidth={2}
      stroke="currentColor"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
      />
    </svg>
  )
}

function FailIcon({ caseId }: { caseId: string }) {
  return (
    <svg
      data-testid={`result-fail-${caseId}`}
      className="h-5 w-5 text-red-400"
      fill="none"
      viewBox="0 0 24 24"
      strokeWidth={2}
      stroke="currentColor"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M9.75 9.75l4.5 4.5m0-4.5l-4.5 4.5M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
      />
    </svg>
  )
}

function DetailPanel({
  caseResult,
  seedResult,
}: {
  caseResult: CaseResultData
  seedResult?: CaseResultData
}) {
  const { t } = useTranslation()
  return (
    <div className="grid gap-4 p-4 md:grid-cols-2">
      {/* Expected */}
      <div>
        <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-400">
          {t('evolution.expected')}
        </p>
        <pre className="max-h-48 overflow-auto rounded bg-slate-900/60 p-3 text-xs text-slate-300">
          {caseResult.expected
            ? JSON.stringify(caseResult.expected, null, 2)
            : '(none)'}
        </pre>
      </div>

      {/* Actual */}
      <div>
        <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-400">
          {t('evolution.actual')}
        </p>
        {caseResult.actualContent && (
          <pre className="mb-2 max-h-48 overflow-auto rounded bg-slate-900/60 p-3 text-xs text-slate-300">
            {caseResult.actualContent}
          </pre>
        )}
        {caseResult.actualToolCalls && caseResult.actualToolCalls.length > 0 && (
          <pre className="max-h-48 overflow-auto rounded bg-slate-900/60 p-3 text-xs text-slate-300">
            {JSON.stringify(caseResult.actualToolCalls, null, 2)}
          </pre>
        )}
        {!caseResult.actualContent &&
          (!caseResult.actualToolCalls ||
            caseResult.actualToolCalls.length === 0) && (
            <p className="text-xs text-slate-500">{t('evolution.noActualOutput')}</p>
          )}
      </div>

      {/* Seed comparison if available */}
      {seedResult && (
        <div className="md:col-span-2">
          <div className="mb-2 flex items-center gap-3">
            <p className="text-xs font-semibold uppercase tracking-wider text-amber-400">
              {t('evolution.seedVsEvolved')}
            </p>
            {/* Show improvement badge */}
            {caseResult.score > seedResult.score ? (
              <span className="rounded-full bg-emerald-500/20 px-2 py-0.5 text-xs font-semibold text-emerald-400">
                Improved ({(caseResult.score - seedResult.score).toFixed(1)})
              </span>
            ) : caseResult.score === seedResult.score ? (
              <span className="rounded-full bg-slate-500/20 px-2 py-0.5 text-xs font-semibold text-slate-400">
                No change
              </span>
            ) : (
              <span className="rounded-full bg-red-500/20 px-2 py-0.5 text-xs font-semibold text-red-400">
                Regressed ({(caseResult.score - seedResult.score).toFixed(1)})
              </span>
            )}
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            {/* Seed column */}
            <div className="rounded border border-slate-700/50 bg-slate-900/40 p-2">
              <p className="mb-1 text-xs font-semibold text-slate-500">{t('evolution.seedOriginalPrompt')}</p>
              <div className="flex items-center gap-2">
                <span className={`text-xs font-semibold ${seedResult.passed ? 'text-emerald-400' : 'text-red-400'}`}>
                  {seedResult.passed ? 'PASS' : 'FAIL'}
                </span>
                <span className="text-xs font-mono" style={{ color: scoreColor(seedResult.score) }}>
                  {seedResult.score.toFixed(3)}
                </span>
              </div>
              <p className="mt-1 text-xs text-slate-400">{seedResult.reason}</p>
            </div>
            {/* Evolved column */}
            <div className="rounded border border-slate-700/50 bg-slate-900/40 p-2">
              <p className="mb-1 text-xs font-semibold text-slate-500">{t('evolution.evolvedBestCandidate')}</p>
              <div className="flex items-center gap-2">
                <span className={`text-xs font-semibold ${caseResult.passed ? 'text-emerald-400' : 'text-red-400'}`}>
                  {caseResult.passed ? 'PASS' : 'FAIL'}
                </span>
                <span className="text-xs font-mono" style={{ color: scoreColor(caseResult.score) }}>
                  {caseResult.score.toFixed(3)}
                </span>
              </div>
              <p className="mt-1 text-xs text-slate-400">{caseResult.reason}</p>
            </div>
          </div>
        </div>
      )}

      {/* Behavior Criteria Breakdown */}
      {caseResult.criteriaResults && caseResult.criteriaResults.length > 0 && (
        <div className="md:col-span-2">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-slate-400">
            {t('datasets.personaBehaviorCriteria')}
          </p>
          <div className="space-y-1">
            {caseResult.criteriaResults.map((cr, i) => (
              <div key={i} className="flex items-start gap-2 text-xs">
                <span className={cr.passed ? 'text-emerald-400' : 'text-red-400'}>
                  {cr.passed ? '\u2713' : '\u2717'}
                </span>
                <span className="text-slate-300 font-medium">{cr.criterion}:</span>
                <span className="text-slate-400">{cr.reason}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default function CaseResultsGrid({
  caseResults,
  seedCaseResults = [],
  caseNames,
}: CaseResultsGridProps) {
  const { t } = useTranslation()
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set())

  const seedMap = useMemo(() => {
    const map = new Map<string, CaseResultData>()
    for (const sr of seedCaseResults) {
      map.set(sr.caseId, sr)
    }
    return map
  }, [seedCaseResults])

  // Sort: failed first, then by tier priority, then alphabetical
  const sorted = useMemo(() => {
    return [...caseResults].sort((a, b) => {
      // Failed first
      if (a.passed !== b.passed) return a.passed ? 1 : -1
      // Then tier priority
      const tierA = TIER_PRIORITY[a.tier] ?? 99
      const tierB = TIER_PRIORITY[b.tier] ?? 99
      if (tierA !== tierB) return tierA - tierB
      // Then alphabetical
      return a.caseId.localeCompare(b.caseId)
    })
  }, [caseResults])

  const passedCount = caseResults.filter((c) => c.passed).length
  const failedCount = caseResults.length - passedCount
  const passRate =
    caseResults.length > 0 ? (passedCount / caseResults.length) * 100 : 0

  function toggleExpand(caseId: string) {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      if (next.has(caseId)) {
        next.delete(caseId)
      } else {
        next.add(caseId)
      }
      return next
    })
  }

  if (caseResults.length === 0) {
    return (
      <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-8 text-center text-slate-400">
        {t('evolution.noCaseResults')}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Summary stats bar */}
      <div className="rounded-lg border border-slate-700 bg-slate-800 p-4">
        <div className="mb-2 flex items-center gap-4 text-sm">
          <span className="text-slate-400">
            {t('evolution.totalCases', { count: caseResults.length })}
          </span>
          <span className="text-emerald-400">{t('evolution.passedCount', { count: passedCount })}</span>
          <span className="text-red-400">{t('evolution.failedCount', { count: failedCount })}</span>
        </div>
        <div className="flex h-2 overflow-hidden rounded-full bg-slate-700">
          <div
            className="bg-emerald-500 transition-all"
            style={{ width: `${passRate}%` }}
          />
          <div
            className="bg-red-500 transition-all"
            style={{ width: `${100 - passRate}%` }}
          />
        </div>
      </div>

      {/* Table */}
      <div className="overflow-hidden rounded-lg border border-slate-700 bg-slate-800">
        <table className="w-full">
          <thead>
            <tr className="bg-slate-700/50">
              <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-slate-400">
                {t('evolution.caseId')}
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-slate-400">
                {t('datasets.tier')}
              </th>
              <th className="px-4 py-3 text-center text-xs font-medium uppercase tracking-wider text-slate-400">
                {t('evolution.result')}
              </th>
              <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wider text-slate-400">
                {t('evolution.fitness')}
              </th>
              <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-slate-400">
                {t('evolution.reason')}
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((c, idx) => {
              const isExpanded = expandedIds.has(c.caseId)
              const tierClass = TIER_STYLES[c.tier] ?? TIER_STYLES.normal

              return (
                <Fragment key={c.caseId}>
                  <tr
                    onClick={() => toggleExpand(c.caseId)}
                    className={`cursor-pointer ${
                      idx % 2 === 0 ? 'bg-slate-800/50' : 'bg-slate-900/30'
                    } hover:bg-slate-700/30`}
                  >
                    <td className="px-4 py-3 text-sm text-slate-300" title={c.caseId}>
                      {caseNames?.get(c.caseId) ?? c.caseId}
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold ${tierClass}`}
                      >
                        {c.tier}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-center">
                      {c.passed ? (
                        <PassIcon caseId={c.caseId} />
                      ) : (
                        <FailIcon caseId={c.caseId} />
                      )}
                    </td>
                    <td
                      className="px-4 py-3 text-right font-mono text-sm"
                      style={{ color: scoreColor(c.score) }}
                    >
                      {c.score.toFixed(3)}
                    </td>
                    <td className="px-4 py-3 text-sm text-slate-400" title={c.reason}>
                      <span className={`mr-1 font-semibold ${c.passed ? 'text-emerald-400' : 'text-red-400'}`}>
                        {c.passed ? '[PASS]' : '[FAIL]'}
                      </span>
                      {truncate(c.reason, 50)}
                    </td>
                  </tr>
                  {isExpanded && (
                    <tr>
                      <td
                        colSpan={5}
                        className="border-t border-slate-700/50 bg-slate-900/40"
                      >
                        <DetailPanel
                          caseResult={c}
                          seedResult={seedMap.get(c.caseId)}
                        />
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
