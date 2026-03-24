import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { getPromptApiPromptsPromptIdGet } from '@/client/sdk.gen'
import { Button } from '@/components/ui/button'
import PromptDetail from '@/components/prompts/PromptDetail'
import TemplateEditor from '@/components/prompts/TemplateEditor'
import VersionHistory from '@/components/prompts/VersionHistory'

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
          <PromptDetail
            promptId={promptId}
            onEditTemplate={() => setEditing(true)}
          />

          {/* Section 5: Version History */}
          <VersionHistorySection promptId={promptId} />
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-xl font-bold text-foreground">{t('prompts.editingTemplate')}</h2>
            <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>
              {t('common.cancel')}
            </Button>
          </div>
          <TemplateEditor
            promptId={promptId}
            initialTemplate={prompt?.data?.template ?? ''}
            onSaved={() => setEditing(false)}
          />
        </div>
      )}
    </div>
  )
}

function VersionHistorySection({ promptId }: { promptId: string }) {
  const { t } = useTranslation()
  return (
    <div className="space-y-3">
      <h3 className="text-lg font-semibold text-foreground">{t('prompts.versionHistory')}</h3>
      <VersionHistory promptId={promptId} />
    </div>
  )
}
