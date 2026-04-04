import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  addCaseApiPromptsPromptIdDatasetPost,
  updateCaseApiPromptsPromptIdDatasetCaseIdPut,
} from '@/client/sdk.gen'
import type { TestCaseResponse } from '@/client/types.gen'
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/select'


interface CaseEditorProps {
  promptId: string
  existingCase?: TestCaseResponse
  open: boolean
  onOpenChange: (open: boolean) => void
}

function safeJsonParse(text: string): { ok: true; value: unknown } | { ok: false; error: string } {
  if (!text.trim()) return { ok: true, value: undefined }
  try {
    return { ok: true, value: JSON.parse(text) }
  } catch (e) {
    return { ok: false, error: (e as Error).message }
  }
}

export function CaseEditor({ promptId, existingCase, open, onOpenChange }: CaseEditorProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const isEdit = !!existingCase

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [tier, setTier] = useState('normal')
  const [tags, setTags] = useState('')
  const [variables, setVariables] = useState('')
  const [expectedOutput, setExpectedOutput] = useState('')
  const [chatHistory, setChatHistory] = useState('')
  const [requireContent, setRequireContent] = useState(false)
  const [matchArgs, setMatchArgs] = useState('exact')
  const [behaviorCriteria, setBehaviorCriteria] = useState('')
  const [jsonError, setJsonError] = useState<string | null>(null)

  useEffect(() => {
    if (open) {
      if (existingCase) {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setName(existingCase.name || '')
        setDescription(existingCase.description || '')
        setTier(existingCase.tier || 'normal')
        setTags(existingCase.tags?.join(', ') || '')
        setVariables(existingCase.variables ? JSON.stringify(existingCase.variables, null, 2) : '')
        const eo = existingCase.expected_output
        setRequireContent(eo?.require_content === true)
        setMatchArgs(typeof eo?.match_args === 'string' ? eo.match_args : 'exact')
        const behavior = eo?.behavior as string[] | undefined
        setBehaviorCriteria(behavior?.join('\n') || '')
        // Show expected_output without scorer flags or behavior for the JSON textarea
        if (eo) {
          const { require_content: _rc, match_args: _ma, behavior: _bh, ...rest } = eo as Record<string, unknown>
          setExpectedOutput(Object.keys(rest).length > 0 ? JSON.stringify(rest, null, 2) : '')
        } else {
          setExpectedOutput('')
        }
        setChatHistory(existingCase.chat_history?.length ? JSON.stringify(existingCase.chat_history, null, 2) : '')
      } else {
        setName('')
        setDescription('')
        setTier('normal')
        setTags('')
        setVariables('')
        setExpectedOutput('')
        setChatHistory('')
        setRequireContent(false)
        setMatchArgs('exact')
        setBehaviorCriteria('')
      }
      setJsonError(null)
    }
  }, [open, existingCase])

  const addMutation = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      addCaseApiPromptsPromptIdDatasetPost({
        path: { prompt_id: promptId },
        body: body as Parameters<typeof addCaseApiPromptsPromptIdDatasetPost>[0]['body'],
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['datasets', promptId] })
      onOpenChange(false)
    },
  })

  const updateMutation = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      updateCaseApiPromptsPromptIdDatasetCaseIdPut({
        path: { prompt_id: promptId, case_id: existingCase!.id },
        body: body as Parameters<typeof updateCaseApiPromptsPromptIdDatasetCaseIdPut>[0]['body'],
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['datasets', promptId] })
      onOpenChange(false)
    },
  })

  const mutation = isEdit ? updateMutation : addMutation

  function handleSave() {
    setJsonError(null)
    const varsResult = safeJsonParse(variables)
    if (!varsResult.ok) { setJsonError(`Variables: ${varsResult.error}`); return }
    const eoResult = safeJsonParse(expectedOutput)
    if (!eoResult.ok) { setJsonError(`Expected Output: ${eoResult.error}`); return }
    const chResult = safeJsonParse(chatHistory)
    if (!chResult.ok) { setJsonError(`Chat History: ${chResult.error}`); return }

    // Build expected_output with scorer flags merged in
    let finalEo: Record<string, unknown> | undefined = eoResult.value as Record<string, unknown> | undefined
    if (requireContent || matchArgs !== 'exact') {
      finalEo = { ...(finalEo || {}) }
      if (requireContent) finalEo.require_content = true
      if (matchArgs !== 'exact') finalEo.match_args = matchArgs
    }
    // Merge behavior criteria as array of strings
    if (behaviorCriteria.trim()) {
      const criteria = behaviorCriteria
        .split('\n')
        .map(l => l.trim())
        .filter(Boolean)
      finalEo = { ...(finalEo || {}), behavior: criteria }
    }

    const body: Record<string, unknown> = {
      name: name || null,
      description: description || null,
      tier,
      tags: tags ? tags.split(',').map((t) => t.trim()).filter(Boolean) : [],
      variables: varsResult.value || {},
      expected_output: finalEo || null,
      chat_history: chResult.value || [],
    }

    mutation.mutate(body)
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full sm:w-[600px] sm:max-w-[600px] overflow-y-auto">
        <SheetHeader>
          <SheetTitle>{isEdit ? t('datasets.editTestCase') : t('datasets.addTestCaseTitle')}</SheetTitle>
          <SheetDescription>
            {isEdit ? t('datasets.editDescription') : t('datasets.addDescription')}
          </SheetDescription>
        </SheetHeader>

        <div className="space-y-5 mt-6">
          {/* ── Section: Identity ── */}
          <div className="rounded-lg border border-border bg-card overflow-hidden">
            <div className="px-4 py-2.5 border-b border-border">
              <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Identity</h3>
            </div>
            <div className="p-4 space-y-3">
              <div>
                <label htmlFor="case-name" className="block text-sm font-medium text-foreground mb-1">{t('datasets.name')}</label>
                <Input
                  id="case-name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder={t('datasets.testCaseName')}
                />
              </div>
              <div>
                <label htmlFor="case-description" className="block text-sm font-medium text-foreground mb-1">{t('datasets.description')}</label>
                <Textarea
                  id="case-description"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={2}
                  placeholder={t('datasets.optionalDescription')}
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label htmlFor="case-tier" className="block text-sm font-medium text-foreground mb-1">{t('datasets.tier')}</label>
                  <Select value={tier} onValueChange={setTier}>
                    <SelectTrigger id="case-tier">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="critical">critical</SelectItem>
                      <SelectItem value="normal">normal</SelectItem>
                      <SelectItem value="low">low</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <label htmlFor="case-tags" className="block text-sm font-medium text-foreground mb-1">{t('datasets.tagsCommaSeparated')}</label>
                  <Input
                    id="case-tags"
                    value={tags}
                    onChange={(e) => setTags(e.target.value)}
                    placeholder="tag1, tag2"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* ── Section: Input ── */}
          <div className="rounded-lg border border-border bg-card overflow-hidden">
            <div className="px-4 py-2.5 border-b border-border">
              <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Input</h3>
            </div>
            <div className="p-4 space-y-3">
              <div>
                <label htmlFor="case-variables" className="block text-sm font-medium text-foreground mb-1">{t('datasets.variablesJson')}</label>
                <Textarea
                  id="case-variables"
                  value={variables}
                  onChange={(e) => setVariables(e.target.value)}
                  rows={3}
                  className="font-mono text-xs"
                  placeholder='{"key": "value"}'
                />
              </div>
              <div>
                <label htmlFor="case-chat-history" className="block text-sm font-medium text-foreground mb-1">{t('datasets.chatHistoryJson')}</label>
                <Textarea
                  id="case-chat-history"
                  value={chatHistory}
                  onChange={(e) => setChatHistory(e.target.value)}
                  rows={3}
                  className="font-mono text-xs"
                  placeholder='[{"role": "user", "content": "Hello"}]'
                />
              </div>
            </div>
          </div>

          {/* ── Section: Expected Behavior ── */}
          <div className="rounded-lg border border-border bg-card overflow-hidden">
            <div className="px-4 py-2.5 border-b border-border">
              <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Expected Behavior</h3>
            </div>
            <div className="p-4 space-y-3">
              <div>
                <label htmlFor="case-behavior" className="block text-sm font-medium text-foreground mb-1">
                  {t('datasets.behaviorCriteria')}
                </label>
                <Textarea
                  id="case-behavior"
                  value={behaviorCriteria}
                  onChange={(e) => setBehaviorCriteria(e.target.value)}
                  rows={3}
                  placeholder={"greets warmly in Spanish\nconfirms department before transfer\ntransfers to correct department"}
                />
              </div>
              <div>
                <label htmlFor="case-expected-output" className="block text-sm font-medium text-foreground mb-1">{t('datasets.expectedOutputJson')}</label>
                <Textarea
                  id="case-expected-output"
                  value={expectedOutput}
                  onChange={(e) => setExpectedOutput(e.target.value)}
                  rows={3}
                  className="font-mono text-xs"
                  placeholder='{"tool_name": "transfer_call", "tool_args": {"destination": "sales"}}'
                />
              </div>
            </div>
          </div>

          {/* ── Section: Scoring ── */}
          <div className="rounded-lg border border-border bg-card overflow-hidden">
            <div className="px-4 py-2.5 border-b border-border">
              <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">{t('datasets.scorerFlags')}</h3>
            </div>
            <div className="p-4 space-y-3">
              <div className="flex items-center justify-between">
                <label htmlFor="case-require-content" className="text-sm text-foreground">
                  {t('datasets.requireContent')}
                </label>
                <Switch
                  id="case-require-content"
                  checked={requireContent}
                  onCheckedChange={setRequireContent}
                />
              </div>
              <div className="flex items-center justify-between">
                <label htmlFor="case-match-args" className="text-sm text-foreground">{t('datasets.argumentMatchingMode')}</label>
                <Select value={matchArgs} onValueChange={setMatchArgs}>
                  <SelectTrigger id="case-match-args" className="w-[120px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="exact">exact</SelectItem>
                    <SelectItem value="subset">subset</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>

          {/* Error display */}
          {(jsonError || mutation.error) && (
            <p className="text-sm text-destructive">
              {jsonError || String(mutation.error)}
            </p>
          )}

          {/* Actions */}
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              {t('common.cancel')}
            </Button>
            <Button
              onClick={handleSave}
              disabled={mutation.isPending}
            >
              {mutation.isPending ? t('datasets.saving') : isEdit ? t('datasets.update') : t('common.create')}
            </Button>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  )
}
