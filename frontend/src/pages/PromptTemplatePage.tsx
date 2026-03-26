import { useState, lazy, Suspense } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { getPromptApiPromptsPromptIdGet } from '@/client/sdk.gen'
import { Button } from '@/components/ui/button'
import PromptDetail from '@/components/prompts/PromptDetail'
import VersionHistory from '@/components/prompts/VersionHistory'

const TemplateEditor = lazy(() => import('@/components/prompts/TemplateEditor'))

export default function PromptTemplatePage() {
  const { promptId } = useParams<{ promptId: string }>()
  const [editing, setEditing] = useState(false)
  const { t } = useTranslation()

  const { data: prompt } = useQuery({
    queryKey: ['prompts', promptId],
    queryFn: () =>
      getPromptApiPromptsPromptIdGet({
        path: { prompt_id: promptId! },
      }),
    enabled: !!promptId,
  })

  if (!promptId) {
    return <p className="text-destructive">{t('promptLayout.missingId')}</p>
  }

  return (
    <div>
      {!editing ? (
        <div className="space-y-6">
          {/* Top row: Template Preview + Version History side by side on large screens */}
          <div className="grid grid-cols-1 xl:grid-cols-[1fr_320px] gap-6">
            <PromptDetail
              promptId={promptId}
              onEditTemplate={() => setEditing(true)}
            />
            <div className="space-y-3">
              <h3 className="text-lg font-semibold text-foreground">{t('prompts.versionHistory')}</h3>
              <div className="xl:sticky xl:top-4">
                <VersionHistory promptId={promptId} />
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-xl font-bold text-foreground">{t('prompts.editingTemplate')}</h2>
            <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>
              {t('common.cancel')}
            </Button>
          </div>
          <Suspense fallback={
            <div className="flex items-center justify-center py-20">
              <div className="h-8 w-8 animate-spin rounded-full border-4 border-muted border-t-primary" />
            </div>
          }>
            <TemplateEditor
              promptId={promptId}
              initialTemplate={prompt?.data?.template ?? ''}
              onSaved={() => setEditing(false)}
            />
          </Suspense>
        </div>
      )}
    </div>
  )
}
