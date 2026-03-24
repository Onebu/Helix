import { Outlet, useParams, useLocation, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getPromptApiPromptsPromptIdGet } from '@/client/sdk.gen'
import type { PromptDetail } from '@/client/types.gen'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { useTranslation } from 'react-i18next'

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

  if (!promptId) {
    return <p className="text-destructive">{t('promptLayout.missingId')}</p>
  }

  return (
    <div className="space-y-6">
      {/* Prompt header */}
      <div>
        {isLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-8 w-[280px]" />
            <Skeleton className="h-5 w-[400px]" />
            <div className="flex gap-2 mt-3">
              <Skeleton className="h-5 w-20 rounded-full" />
              <Skeleton className="h-5 w-20 rounded-full" />
            </div>
          </div>
        ) : detail ? (
          <div>
            <h1 className="text-2xl font-bold text-foreground">{detail.id}</h1>
            <p className="text-muted-foreground mt-1">{detail.purpose}</p>
            <div className="flex gap-2 mt-3">
              <Badge variant="secondary">
                {t('promptLayout.vars', { count: detail.template_variables.length })}
              </Badge>
              <Badge variant="outline">
                {t('promptLayout.anchors', { count: detail.anchor_variables.length })}
              </Badge>
            </div>
          </div>
        ) : (
          <p className="text-muted-foreground">{t('promptLayout.notFound')}</p>
        )}
      </div>

      {/* Tab navigation */}
      <Tabs
        value={activeTab}
        onValueChange={(value) => navigate(`/prompts/${promptId}/${value}`)}
      >
        <TabsList>
          {TAB_VALUES.map((tabValue) => (
            <TabsTrigger key={tabValue} value={tabValue}>
              {t(`promptLayout.${tabValue}`)}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {/* Child route content */}
      <Outlet />
    </div>
  )
}
