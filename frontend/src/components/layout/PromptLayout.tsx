import { useState } from 'react'
import { Outlet, useParams, useLocation, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  getPromptApiPromptsPromptIdGet,
  updatePromptApiPromptsPromptIdPatch,
} from '@/client/sdk.gen'
import type { PromptDetail } from '@/client/types.gen'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Pencil, Check, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { cn } from '@/lib/utils'

const TAB_VALUES = ['template', 'dataset', 'config', 'evolution', 'history', 'playground'] as const

function getActiveTab(pathname: string, promptId: string): string {
  const segments = pathname.split('/')
  const promptIndex = segments.indexOf(promptId)
  if (promptIndex >= 0 && promptIndex + 1 < segments.length) {
    const nextSegment = segments[promptIndex + 1]
    if ((TAB_VALUES as readonly string[]).includes(nextSegment)) {
      return nextSegment
    }
  }
  return 'template'
}

function PromptHeader({ detail, promptId }: { detail: PromptDetail; promptId: string }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [editingPurpose, setEditingPurpose] = useState(false)
  const [purposeDraft, setPurposeDraft] = useState('')

  const savePurpose = async () => {
    const trimmed = purposeDraft.trim()
    if (!trimmed || trimmed === detail.purpose) {
      setEditingPurpose(false)
      return
    }
    await updatePromptApiPromptsPromptIdPatch({
      path: { prompt_id: promptId },
      body: { purpose: trimmed },
    })
    await queryClient.invalidateQueries({ queryKey: ['prompts', promptId] })
    await queryClient.invalidateQueries({ queryKey: ['prompts'] })
    setEditingPurpose(false)
  }

  return (
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-xl font-bold text-foreground">{detail.id}</h1>
        {editingPurpose ? (
          <div className="flex items-center gap-1 mt-0.5">
            <Input
              value={purposeDraft}
              onChange={(e) => setPurposeDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') savePurpose(); if (e.key === 'Escape') setEditingPurpose(false) }}
              className="h-7 text-sm"
              autoFocus
            />
            <button onClick={savePurpose} className="text-primary hover:text-primary/80 p-1">
              <Check className="h-3.5 w-3.5" />
            </button>
            <button onClick={() => setEditingPurpose(false)} className="text-muted-foreground hover:text-foreground p-1">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ) : (
          <button
            onClick={() => { setPurposeDraft(detail.purpose); setEditingPurpose(true) }}
            className="group flex items-center gap-1 mt-0.5 text-left"
          >
            <p className="text-sm text-muted-foreground">{detail.purpose}</p>
            <Pencil className="h-3 w-3 text-muted-foreground/0 group-hover:text-muted-foreground transition-opacity" />
          </button>
        )}
      </div>
      <div className="flex gap-2 shrink-0 mt-1">
        <Badge variant="secondary" className="text-xs">
          {t('promptLayout.vars', { count: detail.template_variables.length })}
        </Badge>
        <Badge variant="outline" className="text-xs">
          {t('promptLayout.anchors', { count: detail.anchor_variables.length })}
        </Badge>
      </div>
    </div>
  )
}

export function PromptLayout() {
  const { promptId } = useParams<{ promptId: string }>()
  const location = useLocation()
  const navigate = useNavigate()
  const { t } = useTranslation()

  const { data: prompt, isLoading } = useQuery({
    queryKey: ['prompts', promptId],
    queryFn: () =>
      getPromptApiPromptsPromptIdGet({
        path: { prompt_id: promptId! },
      }),
    enabled: !!promptId,
  })

  const detail = prompt?.data as PromptDetail | undefined
  const activeTab = getActiveTab(location.pathname, promptId ?? '')

  // Detect if we're on a deep sub-route (run detail) where prompt context is redundant
  const isDeepRoute = location.pathname.includes('/history/') && location.pathname.split('/').length > 5

  if (!promptId) {
    return <p className="text-destructive">{t('promptLayout.missingId')}</p>
  }

  return (
    <div className="space-y-4">
      {/* Prompt header — compact on deep routes */}
      {!isDeepRoute && (
        <div>
          {isLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-7 w-[280px]" />
              <Skeleton className="h-4 w-[400px]" />
            </div>
          ) : detail ? (
            <PromptHeader detail={detail} promptId={promptId} />
          ) : (
            <p className="text-muted-foreground">{t('promptLayout.notFound')}</p>
          )}
        </div>
      )}

      {/* Tab navigation — underline style */}
      <nav className="border-b border-border" aria-label="Prompt sections">
        <div className="flex gap-0.5 -mb-px">
          {TAB_VALUES.map((tabValue) => (
            <button
              key={tabValue}
              onClick={() => navigate(`/prompts/${promptId}/${tabValue}`)}
              className={cn(
                'px-3 py-2 text-sm font-medium transition-colors border-b-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 rounded-t-sm',
                activeTab === tabValue
                  ? 'border-primary text-foreground'
                  : 'border-transparent text-muted-foreground hover:text-foreground hover:border-border'
              )}
            >
              {t(`promptLayout.${tabValue}`)}
            </button>
          ))}
        </div>
      </nav>

      {/* Child route content */}
      <Outlet />
    </div>
  )
}
