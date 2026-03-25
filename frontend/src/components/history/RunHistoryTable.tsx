import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { listPromptsApiPromptsGet, getHistoryApiHistoryPromptIdGet, listActiveRunsApiEvolutionActiveGet } from '../../client/sdk.gen'
import type { EvolutionRunHistory, EvolutionRunStatus, PromptSummary } from '../../client/types.gen'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/select'
import { History } from 'lucide-react'

function StatusBadge({ status }: { status: string }) {
  const { t } = useTranslation()
  const statusMap: Record<string, string> = {
    completed: t('history.completed'),
    running: t('history.running'),
    failed: t('history.failed'),
    cancelled: t('history.cancelled'),
  }
  const label = statusMap[status] || status
  switch (status) {
    case 'completed':
      return (
        <Badge className="bg-emerald-500/10 text-emerald-400 border-emerald-500/20">
          {label}
        </Badge>
      )
    case 'running':
      return (
        <Badge className="bg-blue-500/10 text-blue-400 border-blue-500/20">
          {label}
        </Badge>
      )
    case 'failed':
      return <Badge variant="destructive">{label}</Badge>
    case 'cancelled':
      return <Badge variant="outline">{label}</Badge>
    default:
      return <Badge variant="outline">{label}</Badge>
  }
}

function relativeTime(date: Date): string {
  const now = Date.now()
  const diffMs = now - date.getTime()
  const diffSec = Math.floor(diffMs / 1000)
  if (diffSec < 60) return `${diffSec}s ago`
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `${diffMin}m ago`
  const diffHr = Math.floor(diffMin / 60)
  if (diffHr < 24) return `${diffHr}h ago`
  const diffDay = Math.floor(diffHr / 24)
  if (diffDay < 30) return `${diffDay} day${diffDay === 1 ? '' : 's'} ago`
  const diffMonth = Math.floor(diffDay / 30)
  if (diffMonth < 12) return `${diffMonth} month${diffMonth === 1 ? '' : 's'} ago`
  const diffYear = Math.floor(diffMonth / 12)
  return `${diffYear} year${diffYear === 1 ? '' : 's'} ago`
}

function HistoryTableSkeleton({ withPromptColumn }: { withPromptColumn: boolean }) {
  const { t } = useTranslation()
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t('history.id')}</TableHead>
          {withPromptColumn && <TableHead>{t('history.prompt')}</TableHead>}
          <TableHead>{t('history.date')}</TableHead>
          <TableHead>{t('history.status')}</TableHead>
          <TableHead>{t('history.bestFitness')}</TableHead>
          <TableHead>{t('history.cost')}</TableHead>
          <TableHead>{t('history.gens')}</TableHead>
          <TableHead>{t('history.models')}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {[1, 2, 3].map((i) => (
          <TableRow key={i}>
            <TableCell><Skeleton className="h-4 w-[80px]" /></TableCell>
            {withPromptColumn && <TableCell><Skeleton className="h-4 w-[100px]" /></TableCell>}
            <TableCell><Skeleton className="h-4 w-[140px]" /></TableCell>
            <TableCell><Skeleton className="h-5 w-[70px] rounded-full" /></TableCell>
            <TableCell><Skeleton className="h-4 w-[60px]" /></TableCell>
            <TableCell><Skeleton className="h-4 w-[50px]" /></TableCell>
            <TableCell><Skeleton className="h-4 w-[30px]" /></TableCell>
            <TableCell><Skeleton className="h-4 w-[120px]" /></TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

interface RunHistoryTableProps {
  promptId?: string
}

export default function RunHistoryTable({ promptId: propPromptId }: RunHistoryTableProps = {}) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { promptId: _routePromptId } = useParams<{ promptId: string }>()
  const [selectedPromptId, setSelectedPromptId] = useState<string>(propPromptId ?? '')

  const { data: prompts, isLoading: promptsLoading } = useQuery({
    queryKey: ['prompts'],
    queryFn: () => listPromptsApiPromptsGet(),
    enabled: !propPromptId,
  })

  const { data: history, isLoading: historyLoading } = useQuery({
    queryKey: ['history', selectedPromptId],
    queryFn: () => getHistoryApiHistoryPromptIdGet({ path: { prompt_id: selectedPromptId } }),
    enabled: !!selectedPromptId,
  })

  // Poll active runs every 5 seconds
  const { data: activeRunsResp } = useQuery({
    queryKey: ['active-runs'],
    queryFn: () => listActiveRunsApiEvolutionActiveGet(),
    refetchInterval: 5000,
    refetchIntervalInBackground: false,
  })
  const allActiveRuns: EvolutionRunStatus[] = (activeRunsResp?.data as EvolutionRunStatus[] | undefined) ?? []
  // Filter active runs to only those matching the selected prompt (if one is selected)
  const activeRuns = selectedPromptId
    ? allActiveRuns.filter((r) => r.prompt_id === selectedPromptId)
    : allActiveRuns

  const promptList: PromptSummary[] = (prompts?.data as PromptSummary[] | undefined) ?? []
  const runs: EvolutionRunHistory[] = (history?.data as EvolutionRunHistory[] | undefined) ?? []

  // Sort by date descending
  const sortedRuns = [...runs].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  )

  return (
    <div className="space-y-4">
      {/* Prompt selector -- hidden when promptId is provided via prop */}
      {!propPromptId && (
        <div>
          <label className="block text-sm font-medium text-foreground mb-1">
            {t('history.prompt')}
          </label>
          <Select
            value={selectedPromptId}
            onValueChange={setSelectedPromptId}
          >
            <SelectTrigger className="max-w-md">
              <SelectValue placeholder={promptsLoading ? t('history.loadingPrompts') : t('history.selectPromptPlaceholder')} />
            </SelectTrigger>
            <SelectContent>
              {promptList.map((p) => (
                <SelectItem key={p.id} value={p.id}>
                  {p.id} -- {p.purpose}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}

      {/* Active runs banner */}
      {activeRuns.length > 0 && (
        <div className="space-y-2">
          {activeRuns.map((run) => (
            <div
              key={run.run_id}
              onClick={() => {
                navigate(`/prompts/${run.prompt_id}/evolution?run=${run.run_id}`)
              }}
              className="flex items-center gap-3 rounded-lg border border-blue-500/30 bg-blue-500/5 px-4 py-3 cursor-pointer hover:bg-blue-500/10 transition-colors"
            >
              <StatusBadge status={run.status} />
              <span className="font-mono text-xs text-foreground">{run.run_id.slice(0, 8)}</span>
              <span className="text-sm text-muted-foreground">{run.prompt_id}</span>
              <span className="text-xs text-muted-foreground">
                {t('history.started')} {new Date(run.started_at).toLocaleTimeString()}
              </span>
              {run.target_model && (
                <span className="ml-auto text-xs text-muted-foreground font-mono">
                  {run.target_model}
                </span>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Table or state messages */}
      {!selectedPromptId && (
        <p className="text-muted-foreground">{t('history.selectPrompt')}</p>
      )}

      {selectedPromptId && historyLoading && (
        <HistoryTableSkeleton withPromptColumn={!propPromptId} />
      )}

      {selectedPromptId && !historyLoading && sortedRuns.length === 0 && (
        <div className="flex flex-col items-center justify-center py-16">
          <div className="rounded-xl border-2 border-dashed border-border p-8 text-center max-w-md">
            <History className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
            <h3 className="text-lg font-semibold text-foreground mb-2">{t('history.noRunsYet')}</h3>
            <p className="text-sm text-muted-foreground">
              {t('history.noRunsDescription')}
            </p>
          </div>
        </div>
      )}

      {selectedPromptId && !historyLoading && sortedRuns.length > 0 && (
        <div className="rounded-lg border border-border bg-card overflow-hidden">
          <div className="px-4 py-3 border-b border-border">
            <h3 className="text-sm font-semibold text-foreground">{t('history.runHistory', 'Run History')}</h3>
          </div>
          <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('history.id')}</TableHead>
                {!propPromptId && <TableHead>{t('history.prompt')}</TableHead>}
                <TableHead>{t('history.date')}</TableHead>
                <TableHead>{t('history.status')}</TableHead>
                <TableHead>{t('history.bestFitness')}</TableHead>
                <TableHead>{t('history.cost')}</TableHead>
                <TableHead>{t('history.gens')}</TableHead>
                <TableHead>{t('history.models')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sortedRuns.map((run) => {
                const createdDate = new Date(run.created_at)
                return (
                  <TableRow
                    key={run.id}
                    tabIndex={0}
                    role="link"
                    onClick={() => navigate(propPromptId ? `${run.id}` : `/history/${run.id}`)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        navigate(propPromptId ? `${run.id}` : `/history/${run.id}`)
                      }
                    }}
                    className="cursor-pointer hover:bg-muted/50 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                  >
                    <TableCell className="font-mono text-xs">{run.id}</TableCell>
                    {!propPromptId && <TableCell>{run.prompt_id}</TableCell>}
                    <TableCell className="whitespace-nowrap">
                      <span>{createdDate.toLocaleString()}</span>
                      <span className="ml-2 text-xs text-muted-foreground">· {relativeTime(createdDate)}</span>
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={run.status} />
                    </TableCell>
                    <TableCell className="font-mono">
                      {run.best_fitness_score !== null ? run.best_fitness_score.toFixed(3) : '--'}
                    </TableCell>
                    <TableCell className="font-mono">
                      ${run.total_cost_usd.toFixed(2)}
                    </TableCell>
                    <TableCell className="text-center">{run.generations_completed}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {run.meta_model} / {run.target_model}
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
          </div>
        </div>
      )}
    </div>
  )
}
