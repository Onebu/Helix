import { useState, useCallback } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import Editor from '@monaco-editor/react'
import { updateTemplateApiPromptsPromptIdTemplatePut } from '@/client/sdk.gen'
import { registerJinja2Language } from '@/lib/jinja2-language'

interface TemplateEditorProps {
  promptId: string
  initialTemplate: string
  onSaved?: () => void
}

export default function TemplateEditor({ promptId, initialTemplate, onSaved }: TemplateEditorProps) {
  const [content, setContent] = useState(initialTemplate)
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saved' | 'error'>('idle')
  const queryClient = useQueryClient()
  const { t } = useTranslation()

  const saveMutation = useMutation({
    mutationFn: (template: string) =>
      updateTemplateApiPromptsPromptIdTemplatePut({
        path: { prompt_id: promptId },
        body: { template },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['prompts', promptId] })
      queryClient.invalidateQueries({ queryKey: ['prompts'] })
      setSaveStatus('saved')
      setTimeout(() => setSaveStatus('idle'), 2000)
      onSaved?.()
    },
    onError: () => {
      setSaveStatus('error')
    },
  })

  const handleSave = useCallback(() => {
    saveMutation.mutate(content)
  }, [content, saveMutation])

  const handleCancel = useCallback(() => {
    setContent(initialTemplate)
    setSaveStatus('idle')
  }, [initialTemplate])

  const hasChanges = content !== initialTemplate

  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-border bg-card overflow-hidden">
        <Editor
          height="500px"
          language="jinja2-md"
          theme="vs-dark"
          value={content}
          beforeMount={(monaco) => registerJinja2Language(monaco)}
          onChange={(value) => setContent(value ?? '')}
          options={{
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            wordWrap: 'on',
            fontSize: 14,
            lineNumbers: 'on',
          }}
        />
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={saveMutation.isPending || !hasChanges}
          className="inline-flex items-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {saveMutation.isPending ? t('prompts.saving') : t('common.save')}
        </button>
        <button
          onClick={handleCancel}
          className="inline-flex items-center rounded-md bg-secondary px-4 py-2 text-sm font-medium text-secondary-foreground hover:bg-secondary/80 transition-colors"
        >
          {t('common.cancel')}
        </button>
        {saveStatus === 'saved' && (
          <span className="text-sm text-success">{t('prompts.saved')}</span>
        )}
        {saveStatus === 'error' && (
          <span className="text-sm text-destructive">{t('prompts.failedToSaveTemplate')}</span>
        )}
      </div>
    </div>
  )
}
