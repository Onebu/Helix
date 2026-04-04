import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { getPromptApiPromptsPromptIdGet, addCaseApiPromptsPromptIdDatasetPost } from '@/client/sdk.gen'
import type { PromptDetail } from '@/client/types.gen'
import { useChatStream } from '@/hooks/useChatStream'
import type { ChatMessage } from '@/hooks/useChatStream'
import { getApiBaseUrl } from '@/lib/api-config'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { Textarea } from '@/components/ui/textarea'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from '@/components/ui/collapsible'

/** Replace {{ var }} placeholders with variable values */
function renderTemplate(template: string, variables: Record<string, string>): string {
  return template.replace(/\{\{\s*(\w+)\s*\}\}/g, (_match, key: string) => {
    return variables[key] ?? `{{ ${key} }}`
  })
}

function ToolCallBlock({ message }: { message: ChatMessage }) {
  const tc = message.toolCall!
  const args = tc.arguments
  const hasArgs = Object.keys(args).length > 0
  return (
    <div className="rounded-md border border-warning/30 bg-warning/10 px-3 py-2 text-xs font-mono">
      <div className="flex items-center gap-1.5 text-warning mb-1">
        <span className="text-[10px] font-semibold uppercase tracking-wider">Tool Call</span>
      </div>
      <div className="text-foreground font-semibold">{tc.name}()</div>
      {hasArgs && (
        <pre className="mt-1 text-muted-foreground text-[11px] overflow-x-auto">
          {JSON.stringify(args, null, 2)}
        </pre>
      )}
    </div>
  )
}

function ToolResultBlock({ message }: { message: ChatMessage }) {
  const tr = message.toolResult!
  return (
    <div className="rounded-md border border-info/30 bg-info/10 px-3 py-2 text-xs font-mono">
      <div className="flex items-center gap-1.5 text-info mb-1">
        <span className="text-[10px] font-semibold uppercase tracking-wider">Tool Result</span>
        <span className="text-muted-foreground">{tr.name}</span>
      </div>
      <pre className="text-foreground text-[11px] overflow-x-auto whitespace-pre-wrap">
        {tr.content}
      </pre>
    </div>
  )
}

function groupMessagesByStep(messages: ChatMessage[]): ChatMessage[][] {
  const groups: ChatMessage[][] = []
  let current: ChatMessage[] = []

  for (const msg of messages) {
    if (msg.role === 'user') {
      if (current.length > 0) groups.push(current)
      groups.push([msg])
      current = []
    } else if (
      current.length > 0 &&
      msg.step !== undefined &&
      current[0].step !== undefined &&
      msg.step !== current[0].step
    ) {
      // New step — start new group
      groups.push(current)
      current = [msg]
    } else {
      current.push(msg)
    }
  }
  if (current.length > 0) groups.push(current)
  return groups
}

function MessageGroup({ messages, isStreaming }: { messages: ChatMessage[]; isStreaming: boolean }) {
  if (messages.length === 1 && messages[0].role === 'user') {
    return (
      <div className="flex justify-end mb-3">
        <div className="max-w-[80%] rounded-lg px-4 py-2.5 text-sm whitespace-pre-wrap bg-primary text-primary-foreground">
          {messages[0].content}
        </div>
      </div>
    )
  }

  // Group of assistant + tool messages from the same step
  const hasToolCalls = messages.some((m) => m.role === 'tool_call')

  return (
    <div className="flex justify-start mb-3">
      <div className={`max-w-[80%] space-y-1.5 ${hasToolCalls ? 'rounded-lg border border-border/50 bg-muted/30 p-2.5' : ''}`}>
        {messages.map((msg, i) => {
          if (msg.role === 'tool_call' && msg.toolCall) {
            return <ToolCallBlock key={i} message={msg} />
          }
          if (msg.role === 'tool_result' && msg.toolResult) {
            return <ToolResultBlock key={i} message={msg} />
          }
          // Assistant text
          return (
            <div key={i} className={`rounded-lg px-4 py-2.5 text-sm whitespace-pre-wrap ${hasToolCalls ? '' : 'bg-muted'} text-foreground`}>
              {msg.content}
              {isStreaming && i === messages.length - 1 && (
                <span className="inline-block w-2 h-4 ml-0.5 bg-foreground/60 animate-pulse" />
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default function PromptPlaygroundPage() {
  const { promptId } = useParams<{ promptId: string }>()
  const queryClient = useQueryClient()
  const { t } = useTranslation()

  const { data: prompt } = useQuery({
    queryKey: ['prompts', promptId],
    queryFn: () =>
      getPromptApiPromptsPromptIdGet({
        path: { prompt_id: promptId! },
      }),
    enabled: !!promptId,
  })

  const detail = prompt?.data as PromptDetail | undefined

  const { data: promptConfig } = useQuery({
    queryKey: ['prompt-config', promptId],
    queryFn: async () => {
      const base = getApiBaseUrl()
      const res = await fetch(`${base}/api/prompts/${encodeURIComponent(promptId!)}/config`)
      if (!res.ok) return null
      return res.json() as Promise<{ target: { provider: string; model: string } }>
    },
    enabled: !!promptId,
  })

  const chat = useChatStream(promptId ?? '')
  const messageGroups = useMemo(() => groupMessagesByStep(chat.messages), [chat.messages])

  // Local state
  const [variables, setVariables] = useState<Record<string, string>>({})
  const [turnLimit, setTurnLimit] = useState(20)
  const [costBudget, setCostBudget] = useState(0.5)
  const [inputValue, setInputValue] = useState('')
  const [showSystemPrompt, setShowSystemPrompt] = useState(false)
  const [showVariables, setShowVariables] = useState(false)

  // Save as Test Case dialog state
  const [showSaveDialog, setShowSaveDialog] = useState(false)
  const [saveName, setSaveName] = useState('')
  const [saveTags, setSaveTags] = useState('')
  const [saveExpectedOutput, setSaveExpectedOutput] = useState('')
  const [saveError, setSaveError] = useState<string | null>(null)
  const [isSaving, setIsSaving] = useState(false)
  const [saveSuccess, setSaveSuccess] = useState(false)

  // Auto-scroll ref
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Load variables from API on mount (replaces localStorage)
  useEffect(() => {
    if (detail?.template_variables && promptId) {
      const apiUrl = import.meta.env.VITE_API_URL || ''
      fetch(`${apiUrl}/api/prompts/${promptId}/variables`)
        .then((res) => (res.ok ? res.json() : { variables: {} }))
        .then((data: { variables: Record<string, string> }) => {
          setVariables(() => {
            const next: Record<string, string> = {}
            for (const v of detail.template_variables) {
              next[v] = data.variables[v] || ''
            }
            return next
          })
        })
        .catch(() => {
          // Fallback to empty values on error
          setVariables(() => {
            const next: Record<string, string> = {}
            for (const v of detail!.template_variables) {
              next[v] = ''
            }
            return next
          })
        })
    }
  }, [detail, promptId])

  // Debounced save variables to API on change (replaces localStorage)
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const saveVariablesToApi = useCallback(
    (vars: Record<string, string>) => {
      if (!promptId || Object.keys(vars).length === 0) return
      const hasValues = Object.values(vars).some((v) => v.trim() !== '')
      if (!hasValues) return

      if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
      saveTimerRef.current = setTimeout(() => {
        const apiUrl = import.meta.env.VITE_API_URL || ''
        fetch(`${apiUrl}/api/prompts/${promptId}/variables`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ variables: vars }),
        }).catch((err) => console.warn('Failed to save playground variables:', err))
      }, 300)
    },
    [promptId],
  )

  useEffect(() => {
    saveVariablesToApi(variables)
  }, [variables, saveVariablesToApi])

  // Auto-scroll on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chat.messages])

  // Rendered system prompt
  const renderedSystemPrompt = useMemo(() => {
    if (!detail?.template) return ''
    return renderTemplate(detail.template, variables)
  }, [detail?.template, variables])

  const handleSend = () => {
    const trimmed = inputValue.trim()
    if (!trimmed || chat.isStreaming || chat.limitReached) return
    chat.sendMessage(trimmed, variables, turnLimit, costBudget)
    setInputValue('')
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleNewChat = () => {
    chat.reset()
    if (detail?.template_variables) {
      const fresh: Record<string, string> = {}
      for (const v of detail.template_variables) {
        fresh[v] = ''
      }
      setVariables(fresh)
    }
  }

  const handleVariableChange = (key: string, value: string) => {
    setVariables((prev) => ({ ...prev, [key]: value }))
  }

  // Save as Test Case
  const handleOpenSaveDialog = () => {
    const now = new Date()
    const dateStr = now.toISOString().slice(0, 10)
    setSaveName(`Chat ${dateStr}`)
    setSaveTags('')
    setSaveExpectedOutput('')
    setSaveError(null)
    setSaveSuccess(false)
    setShowSaveDialog(true)
  }

  const handleSaveTestCase = async () => {
    if (!promptId) return
    setIsSaving(true)
    setSaveError(null)
    try {
      await addCaseApiPromptsPromptIdDatasetPost({
        path: { prompt_id: promptId },
        body: {
          name: saveName,
          chat_history: chat.messages.map((m: ChatMessage) => ({ role: m.role, content: m.content })),
          variables: variables,
          expected_output: saveExpectedOutput.trim()
            ? { content: saveExpectedOutput.trim() }
            : null,
          tags: saveTags
            .split(',')
            .map((t: string) => t.trim())
            .filter(Boolean),
          tier: 'normal',
        },
      })
      await queryClient.invalidateQueries({ queryKey: ['prompts', promptId] })
      setShowSaveDialog(false)
      setSaveSuccess(true)
      setTimeout(() => setSaveSuccess(false), 2000)
    } catch (err: unknown) {
      setSaveError(err instanceof Error ? err.message : t('playground.failedToSave'))
    } finally {
      setIsSaving(false)
    }
  }

  // Computed values for the save dialog preview
  const userMessageCount = chat.messages.filter((m: ChatMessage) => m.role === 'user').length
  const canSaveTestCase = chat.messages.length >= 2 && !chat.isStreaming

  if (!promptId) {
    return <p className="text-destructive">{t('playground.missingPromptId')}</p>
  }

  const hasVariables = detail?.template_variables && detail.template_variables.length > 0

  return (
    <div className="flex flex-col h-[calc(100vh-16rem)]">
      {/* Top bar: Variables, System Prompt, Limits, New Chat */}
      <div className="flex-shrink-0 space-y-3 mb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {/* Model indicator */}
            {promptConfig?.target && (
              <Badge variant="secondary" className="text-xs font-mono">
                {t('playground.model', {
                  provider: promptConfig.target.provider,
                  model: promptConfig.target.model,
                })}
              </Badge>
            )}
            {/* Turn limit */}
            <div className="flex items-center gap-1.5">
              <label className="text-xs text-muted-foreground whitespace-nowrap">{t('playground.turnLimit')}</label>
              <Input
                type="number"
                min={1}
                max={100}
                value={turnLimit}
                onChange={(e) => setTurnLimit(Number(e.target.value))}
                className="w-16 h-8 text-xs"
                disabled={chat.isStreaming}
              />
            </div>
            {/* Cost budget */}
            <div className="flex items-center gap-1.5">
              <label className="text-xs text-muted-foreground whitespace-nowrap">{t('playground.budget')}</label>
              <Input
                type="number"
                min={0.01}
                max={100}
                step={0.1}
                value={costBudget}
                onChange={(e) => setCostBudget(Number(e.target.value))}
                className="w-20 h-8 text-xs"
                disabled={chat.isStreaming}
              />
            </div>
          </div>
          <div className="flex items-center gap-2">
            {canSaveTestCase && (
              <Button
                variant="outline"
                size="sm"
                onClick={handleOpenSaveDialog}
              >
                {saveSuccess ? t('playground.savedBang') : t('playground.saveAsTestCase')}
              </Button>
            )}
            <Button variant="outline" size="sm" onClick={handleNewChat} disabled={chat.isStreaming}>
              {t('playground.newChat')}
            </Button>
          </div>
        </div>

        {/* Variable editor (collapsible) */}
        {hasVariables && (
          <Collapsible open={showVariables} onOpenChange={setShowVariables}>
            <CollapsibleTrigger asChild>
              <Button variant="ghost" size="sm" className="text-xs px-2 h-7">
                {showVariables ? t('playground.hideVariables') : t('playground.showVariables')} {t('playground.variablesCount', { count: detail.template_variables.length })}
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <Card className="mt-2">
                <CardContent className="pt-4 pb-3 max-h-[30vh] overflow-y-auto">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {detail.template_variables.map((varName) => (
                      <div key={varName} className="space-y-1">
                        <label className="text-xs font-medium text-muted-foreground">
                          {varName}
                        </label>
                        <Input
                          value={variables[varName] ?? ''}
                          onChange={(e) => handleVariableChange(varName, e.target.value)}
                          placeholder={`Enter ${varName}...`}
                          className="h-8 text-sm"
                          disabled={chat.isStreaming}
                        />
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            </CollapsibleContent>
          </Collapsible>
        )}

        {/* System prompt preview (collapsible) */}
        {detail?.template && (
          <Collapsible open={showSystemPrompt} onOpenChange={setShowSystemPrompt}>
            <CollapsibleTrigger asChild>
              <Button variant="ghost" size="sm" className="text-xs px-2 h-7">
                {showSystemPrompt ? t('playground.hideSystemPrompt') : t('playground.showSystemPrompt')} {t('playground.systemPrompt')}
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <Card className="mt-2 bg-muted/50">
                <CardContent className="pt-4 pb-3">
                  <pre className="text-xs font-mono text-muted-foreground whitespace-pre-wrap max-h-48 overflow-auto">
                    {renderedSystemPrompt}
                  </pre>
                </CardContent>
              </Card>
            </CollapsibleContent>
          </Collapsible>
        )}

        <Separator />
      </div>

      {/* Message list */}
      <ScrollArea className="flex-1 min-h-0 px-1">
        <div className="py-2">
          {chat.messages.length === 0 && (
            <div className="text-center text-muted-foreground text-sm py-12">
              {t('playground.emptyChat')}
            </div>
          )}
          {messageGroups.map((group, i, allGroups) => (
            <MessageGroup
              key={i}
              messages={group}
              isStreaming={chat.isStreaming && i === allGroups.length - 1}
            />
          ))}
          <div ref={messagesEndRef} />
        </div>
      </ScrollArea>

      {/* Status bar + Error + Input */}
      <div className="flex-shrink-0 mt-2 space-y-2">
        {/* Status bar */}
        <div className="flex items-center gap-3 text-xs text-muted-foreground">
          <span>{t('playground.turn', { current: chat.turnCount, total: turnLimit })}</span>
          <span>${chat.totalCost.toFixed(4)} / ${costBudget.toFixed(2)}</span>
          {chat.limitReached && (
            <Badge variant="destructive" className="text-xs">
              {t('playground.limitReached', { reason: chat.limitReached })}
            </Badge>
          )}
        </div>

        {/* Error display */}
        {chat.error && (
          <Badge variant="destructive" className="text-xs py-1 px-2">
            {t('common.error')}: {chat.error}
          </Badge>
        )}

        {/* Input bar */}
        <div className="flex gap-2">
          <textarea
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              chat.limitReached
                ? t('playground.limitReachedPlaceholder')
                : t('playground.inputPlaceholder')
            }
            disabled={chat.isStreaming || !!chat.limitReached}
            className="flex-1 min-h-[40px] max-h-[120px] rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 resize-none"
            rows={1}
          />
          <Button
            onClick={handleSend}
            disabled={chat.isStreaming || !!chat.limitReached || !inputValue.trim()}
            size="default"
          >
            {chat.isStreaming ? t('playground.streaming') : t('playground.send')}
          </Button>
        </div>
      </div>

      {/* Save as Test Case Dialog */}
      <Dialog open={showSaveDialog} onOpenChange={setShowSaveDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('playground.saveDialogTitle')}</DialogTitle>
            <DialogDescription>
              {t('playground.saveDialogDescription')}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2">
            {/* Name field */}
            <div className="space-y-1.5">
              <label className="text-sm font-medium">{t('playground.nameLabel')}</label>
              <Input
                value={saveName}
                onChange={(e) => setSaveName(e.target.value)}
                placeholder={t('playground.testCaseNamePlaceholder')}
              />
            </div>

            {/* Tags field */}
            <div className="space-y-1.5">
              <label className="text-sm font-medium">{t('playground.tagsLabel')}</label>
              <Input
                value={saveTags}
                onChange={(e) => setSaveTags(e.target.value)}
                placeholder={t('playground.tagsPlaceholder')}
              />
            </div>

            {/* Expected output field */}
            <div className="space-y-1.5">
              <label className="text-sm font-medium">{t('playground.expectedOutputLabel')}</label>
              <Textarea
                value={saveExpectedOutput}
                onChange={(e) => setSaveExpectedOutput(e.target.value)}
                placeholder={t('playground.expectedOutputPlaceholder')}
                className="min-h-[80px]"
              />
            </div>

            {/* Preview info */}
            <div className="text-xs text-muted-foreground bg-muted/50 rounded-md px-3 py-2">
              {t('playground.messagesTurns', { messages: chat.messages.length, turns: userMessageCount })}
            </div>

            {/* Error display */}
            {saveError && (
              <div className="text-sm text-destructive">{saveError}</div>
            )}
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setShowSaveDialog(false)} disabled={isSaving}>
              {t('common.cancel')}
            </Button>
            <Button onClick={handleSaveTestCase} disabled={isSaving || !saveName.trim()}>
              {isSaving ? t('playground.savingTestCase') : t('playground.saveTestCase')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
