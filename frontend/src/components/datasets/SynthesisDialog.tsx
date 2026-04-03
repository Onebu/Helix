import { useState, useEffect, useRef, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Textarea } from '@/components/ui/textarea'
import { ScrollArea } from '@/components/ui/scroll-area'
import { getApiBaseUrl, getWsBaseUrl } from '@/lib/api-config'
import { UserPlus, Download, Upload, Wrench, Sparkles, X, Check, AlertCircle } from 'lucide-react'
import { createPortal } from 'react-dom'
import { PersonaCard, type Persona } from './PersonaCard'
import { PersonaEditor } from './PersonaEditor'
import { ReviewConversation, type ReviewConversationData, type ConversationEdits } from './ReviewConversation'

interface SynthesisDialogProps {
  promptId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  onComplete: () => void
}

interface SynthesisEvent {
  type: string
  data: Record<string, unknown>
}

interface ConversationProgress {
  personaId: string
  conversationIndex: number
  score?: number
  passed?: boolean
  caseId?: string
  hasToolCalls?: boolean
}

type SynthesisStatus = 'idle' | 'running' | 'review' | 'submitting' | 'complete' | 'error'

export function SynthesisDialog({ promptId, open, onOpenChange, onComplete }: SynthesisDialogProps) {
  const { t } = useTranslation()
  const [status, setStatus] = useState<SynthesisStatus>('idle')
  const [numConversations, setNumConversations] = useState(5)
  const [maxTurns, setMaxTurns] = useState(10)
  const [runId, setRunId] = useState<string | null>(null)
  const [progressText, setProgressText] = useState('')
  const [conversations, setConversations] = useState<ConversationProgress[]>([])
  const [result, setResult] = useState<{ total: number; persisted: number; discarded: number } | null>(null)
  const [errorMessage, setErrorMessage] = useState('')
  const wsRef = useRef<WebSocket | null>(null)

  // Review state
  const [reviewConversations, setReviewConversations] = useState<ReviewConversationData[]>([])
  const [decisions, setDecisions] = useState<Map<number, { action: 'approved' | 'rejected'; edits?: ConversationEdits }>>(new Map())
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [reviewError, setReviewError] = useState<string | null>(null)

  // Persona management state
  const [personas, setPersonas] = useState<Persona[]>([])
  const [selectedPersonaIds, setSelectedPersonaIds] = useState<Set<string>>(new Set())
  const [editingPersonaId, setEditingPersonaId] = useState<string | null>(null)
  const [showAddForm, setShowAddForm] = useState(false)
  const [scenarioContext, setScenarioContext] = useState('')
  const [personaLoading, setPersonaLoading] = useState(false)
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null)
  const importInputRef = useRef<HTMLInputElement>(null)

  const storageKey = `helix:synthesis-state:${promptId}`

  const cleanup = useCallback(() => {
    if (wsRef.current) {
      if (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING) {
        wsRef.current.close()
      }
      wsRef.current = null
    }
    localStorage.removeItem(storageKey)
  }, [storageKey])

  // Cleanup on unmount — close WS but keep localStorage for refresh survival
  useEffect(() => {
    return () => {
      if (wsRef.current) {
        if (wsRef.current.readyState === WebSocket.OPEN || wsRef.current.readyState === WebSocket.CONNECTING) {
          wsRef.current.close()
        }
        wsRef.current = null
      }
    }
  }, [])

  // Restore banner state from localStorage on mount (survives page refresh)
  useEffect(() => {
    const saved = localStorage.getItem(storageKey)
    if (saved && status === 'idle') {
      try {
        const state = JSON.parse(saved)
        // Expire after 10 minutes (synthesis probably done by then)
        if (Date.now() - state.timestamp > 10 * 60 * 1000) {
          localStorage.removeItem(storageKey)
          return
        }
        // Restore last known state
        setConversations(state.conversations || [])
        setResult(state.result || null)
        setRunId(state.runId || null)
        setErrorMessage(state.errorMessage || '')
        if (state.status === 'running') {
          // Synthesis is still running on the backend — show banner, try to reconnect WS
          setStatus('running')
          setProgressText(t('datasets.synthesisRunningBackground'))
          if (state.runId) {
            connectWebSocket(state.runId, true)
          }
        } else {
          setStatus(state.status)
          setProgressText(state.progressText || '')
        }
      } catch {
        localStorage.removeItem(storageKey)
      }
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Auto-persist banner state whenever synthesis state changes
  useEffect(() => {
    if (status !== 'idle') {
      const stateToSave = {
        status,
        conversations,
        progressText,
        result,
        errorMessage,
        runId,
        timestamp: Date.now(),
      }
      localStorage.setItem(storageKey, JSON.stringify(stateToSave))
    }
  }, [status, conversations, progressText, result, errorMessage, runId, storageKey])

  // Load scenario context from localStorage when dialog opens
  useEffect(() => {
    if (open && status === 'idle') {
      const saved = localStorage.getItem(`helix:scenario-context:${promptId}`)
      if (saved !== null) {
        setScenarioContext(saved)
      }
    }
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  // Persist scenario context to localStorage on change
  useEffect(() => {
    if (open && status === 'idle') {
      localStorage.setItem(`helix:scenario-context:${promptId}`, scenarioContext)
    }
  }, [scenarioContext, promptId, open, status])

  // Fetch personas when dialog opens
  useEffect(() => {
    if (open && status === 'idle') {
      fetchPersonas()
    }
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  async function fetchPersonas() {
    setPersonaLoading(true)
    try {
      const apiBase = getApiBaseUrl()
      const response = await fetch(`${apiBase}/api/prompts/${promptId}/personas`)
      if (response.ok) {
        const data = (await response.json()) as Persona[]
        setPersonas(data)
        // Select all personas by default
        setSelectedPersonaIds(new Set(data.map((p) => p.id)))
      }
    } catch {
      // Silently fail -- personas are optional
    } finally {
      setPersonaLoading(false)
    }
  }

  function handleClose() {
    // When running, just hide the dialog — keep WebSocket alive for background tracking
    if (status === 'running') {
      onOpenChange(false)
      return
    }
    // If in review mode with approved conversations, confirm before closing
    if (status === 'review') {
      const hasApproved = Array.from(decisions.values()).some((d) => d.action === 'approved')
      if (hasApproved && !window.confirm('You have approved conversations that haven\'t been submitted yet. Discard all and close?')) {
        return
      }
    }
    if (status === 'complete') {
      onComplete()
    }
    cleanup()
    setStatus('idle')
    setRunId(null)
    setProgressText('')
    setConversations([])
    setResult(null)
    setErrorMessage('')
    setEditingPersonaId(null)
    setShowAddForm(false)
    setDeleteConfirmId(null)
    setReviewConversations([])
    setDecisions(new Map())
    setEditingIndex(null)
    setReviewError(null)
    onOpenChange(false)
  }

  function handleDismissBanner() {
    if (status === 'complete') {
      onComplete()
    }
    cleanup()
    setStatus('idle')
    setRunId(null)
    setProgressText('')
    setConversations([])
    setResult(null)
    setErrorMessage('')
    setReviewConversations([])
    setDecisions(new Map())
    setEditingIndex(null)
    setReviewError(null)
  }

  function toggleSelectAll() {
    if (selectedPersonaIds.size === personas.length) {
      setSelectedPersonaIds(new Set())
    } else {
      setSelectedPersonaIds(new Set(personas.map((p) => p.id)))
    }
  }

  function togglePersona(id: string) {
    setSelectedPersonaIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  // --- Persona CRUD ---

  async function handleAddPersona(persona: Persona) {
    try {
      const apiBase = getApiBaseUrl()
      const response = await fetch(`${apiBase}/api/prompts/${promptId}/personas`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(persona),
      })
      if (response.ok) {
        setShowAddForm(false)
        await fetchPersonas()
      }
    } catch {
      // Silently fail
    }
  }

  async function handleEditPersona(persona: Persona) {
    try {
      const apiBase = getApiBaseUrl()
      const response = await fetch(`${apiBase}/api/prompts/${promptId}/personas/${persona.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          role: persona.role,
          traits: persona.traits,
          communication_style: persona.communication_style,
          goal: persona.goal,
          edge_cases: persona.edge_cases,
          behavior_criteria: persona.behavior_criteria,
        }),
      })
      if (response.ok) {
        setEditingPersonaId(null)
        await fetchPersonas()
      }
    } catch {
      // Silently fail
    }
  }

  async function handleDeletePersona(id: string) {
    if (deleteConfirmId !== id) {
      setDeleteConfirmId(id)
      return
    }
    try {
      const apiBase = getApiBaseUrl()
      const response = await fetch(`${apiBase}/api/prompts/${promptId}/personas/${id}`, {
        method: 'DELETE',
      })
      if (response.ok) {
        setDeleteConfirmId(null)
        await fetchPersonas()
      }
    } catch {
      // Silently fail
    }
  }

  // --- Export / Import ---

  async function handleExport() {
    try {
      const apiBase = getApiBaseUrl()
      const response = await fetch(`${apiBase}/api/prompts/${promptId}/personas/export`)
      if (response.ok) {
        const data = await response.json()
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `personas-${promptId}.json`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(url)
      }
    } catch {
      // Silently fail
    }
  }

  async function handleImport(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (!file) return

    try {
      const text = await file.text()
      const data = JSON.parse(text)
      const apiBase = getApiBaseUrl()
      const response = await fetch(`${apiBase}/api/prompts/${promptId}/personas/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      })
      if (response.ok) {
        await fetchPersonas()
      }
    } catch {
      // Silently fail
    }

    // Reset file input so the same file can be re-imported
    if (importInputRef.current) {
      importInputRef.current.value = ''
    }
  }

  // --- WebSocket / Synthesis ---

  function connectWebSocket(synthesisRunId: string, isReconnect = false) {
    const wsBase = getWsBaseUrl()
    const ws = new WebSocket(`${wsBase}/ws/synthesis/${synthesisRunId}`)
    wsRef.current = ws

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data as string) as Record<string, unknown>

      // Handle connected message
      if (msg.type === 'connected') {
        ws.send(JSON.stringify({ type: 'subscribe', last_event_id: 0 }))
        return
      }

      const evt = msg as unknown as SynthesisEvent
      handleSynthesisEvent(evt)
    }

    ws.onerror = () => {
      if (isReconnect) return // Silently fail reconnect — banner keeps showing last known state
      setStatus((prev) => {
        if (prev !== 'running') return prev
        setErrorMessage('WebSocket connection failed')
        return 'error'
      })
    }

    ws.onclose = () => {
      if (isReconnect) return // Silently fail reconnect
      setStatus((prev) => (prev === 'running' ? 'error' : prev))
    }
  }

  function handleSynthesisEvent(evt: SynthesisEvent) {
    switch (evt.type) {
      case 'synthesis_started':
        setProgressText(
          `Starting synthesis: ${evt.data.total_personas} persona(s), ${evt.data.num_conversations} conversation(s) each`
        )
        break
      case 'conversation_started':
        setProgressText(
          `Generating conversation ${(evt.data.conversation_index as number) + 1} for persona "${evt.data.persona_id}"...`
        )
        break
      case 'conversation_scored': {
        const conv: ConversationProgress = {
          personaId: evt.data.persona_id as string,
          conversationIndex: evt.data.conversation_index as number,
          score: evt.data.score as number,
          passed: evt.data.passed as boolean,
          hasToolCalls: (evt.data.has_tool_calls as boolean) ?? false,
        }
        setConversations((prev) => [...prev, conv])
        break
      }
      case 'conversation_persisted': {
        setConversations((prev) =>
          prev.map((c) =>
            c.personaId === evt.data.persona_id && c.conversationIndex === evt.data.conversation_index
              ? { ...c, caseId: evt.data.case_id as string }
              : c
          )
        )
        break
      }
      case 'review_ready':
        setReviewConversations((evt.data.conversations as ReviewConversationData[]) || [])
        break
      case 'synthesis_complete':
        if (evt.data.review_mode === true) {
          // Review mode: transition to review state instead of complete
          setStatus('review')
          setProgressText('')
        } else {
          setResult({
            total: evt.data.total_conversations as number,
            persisted: evt.data.total_persisted as number,
            discarded: evt.data.total_discarded as number,
          })
          setStatus('complete')
          setProgressText('')
        }
        break
      case 'synthesis_failed':
        setStatus('error')
        setErrorMessage((evt.data.error as string) || 'Synthesis failed')
        break
    }
  }

  async function handleGenerate() {
    if (selectedPersonaIds.size === 0) return

    setStatus('running')
    setConversations([])
    setResult(null)
    setErrorMessage('')

    const allSelected = selectedPersonaIds.size === personas.length

    try {
      const apiBase = getApiBaseUrl()
      const response = await fetch(`${apiBase}/api/prompts/${promptId}/synthesize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          persona_ids: allSelected ? null : Array.from(selectedPersonaIds),
          num_conversations: numConversations,
          max_turns: maxTurns,
          scenario_context: scenarioContext.trim() || undefined,
        }),
      })

      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: 'Request failed' }))
        throw new Error(err.detail || `HTTP ${response.status}`)
      }

      const data = await response.json()
      const newRunId = data.run_id as string
      setRunId(newRunId)
      setProgressText(`Synthesis started (${data.total_personas} persona(s))...`)
      connectWebSocket(newRunId)
    } catch (err) {
      setStatus('error')
      setErrorMessage(err instanceof Error ? err.message : 'Failed to start synthesis')
    }
  }

  // --- Review helpers ---

  function getDecision(index: number): 'pending' | 'approved' | 'rejected' {
    const d = decisions.get(index)
    return d ? d.action : 'pending'
  }

  function handleApproveConversation(index: number, edits?: ConversationEdits) {
    setDecisions((prev) => {
      const next = new Map(prev)
      next.set(index, { action: 'approved', edits })
      return next
    })
  }

  function handleRejectConversation(index: number) {
    setDecisions((prev) => {
      const next = new Map(prev)
      next.set(index, { action: 'rejected' })
      return next
    })
  }

  function handleUndoDecision(index: number) {
    setDecisions((prev) => {
      const next = new Map(prev)
      next.delete(index)
      return next
    })
  }

  function handleApproveAll() {
    setDecisions((prev) => {
      const next = new Map(prev)
      reviewConversations.forEach((_, i) => {
        if (!next.has(i)) {
          next.set(i, { action: 'approved' })
        }
      })
      return next
    })
  }

  function handleRejectAll() {
    setDecisions((prev) => {
      const next = new Map(prev)
      reviewConversations.forEach((_, i) => {
        if (!next.has(i)) {
          next.set(i, { action: 'rejected' })
        }
      })
      return next
    })
  }

  async function handleSubmitReview() {
    if (!runId) return
    setStatus('submitting')
    setReviewError(null)

    const decisionList = Array.from(decisions.entries()).map(([index, d]) => ({
      conversation_index: index,
      action: d.action,
      edits: d.edits || undefined,
    }))

    try {
      const apiBase = getApiBaseUrl()
      const response = await fetch(`${apiBase}/api/prompts/${promptId}/review`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          run_id: runId,
          decisions: decisionList,
        }),
      })

      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: 'Review submission failed' }))
        throw new Error(err.detail || `HTTP ${response.status}`)
      }

      const data = (await response.json()) as { approved: number; rejected: number; case_ids: string[] }
      setResult({
        total: reviewConversations.length,
        persisted: data.approved,
        discarded: data.rejected,
      })
      setStatus('complete')
    } catch (err) {
      setStatus('review')
      setReviewError(err instanceof Error ? err.message : 'Failed to submit review')
    }
  }

  const reviewApprovedCount = Array.from(decisions.values()).filter((d) => d.action === 'approved').length
  const reviewRejectedCount = Array.from(decisions.values()).filter((d) => d.action === 'rejected').length
  const reviewPendingCount = reviewConversations.length - decisions.size
  const allDecided = reviewConversations.length > 0 && decisions.size === reviewConversations.length

  // --- Floating progress banner (shown when dialog is closed but synthesis is active) ---
  const showBanner = !open && (status === 'running' || status === 'complete' || status === 'error')

  const failedCount = conversations.filter((c) => !c.passed).length
  const passedCount = conversations.filter((c) => c.passed).length

  const floatingBanner = showBanner
    ? createPortal(
        <div className="fixed bottom-6 right-6 z-50 animate-in slide-in-from-bottom-4 fade-in duration-300">
          <div
            className="rounded-lg border border-border bg-card shadow-lg p-3 min-w-[300px] max-w-[380px] cursor-pointer hover:border-primary/50 transition-colors"
            onClick={() => onOpenChange(true)}
          >
            {status === 'running' && (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Sparkles className="h-4 w-4 text-primary animate-pulse" />
                    <span className="text-sm font-medium text-foreground">{t('datasets.generatingTests')}</span>
                  </div>
                  <span className="text-xs text-muted-foreground">
                    {t('datasets.doneCount', { count: conversations.length })}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground truncate">{progressText}</p>
                {conversations.length > 0 && (
                  <div className="flex gap-3 text-xs">
                    <span className="text-success">{t('datasets.passed', { count: passedCount })}</span>
                    <span className="text-destructive">{t('datasets.failed', { count: failedCount })}</span>
                  </div>
                )}
                <p className="text-xs text-muted-foreground/60">{t('datasets.clickToViewDetails')}</p>
              </div>
            )}
            {status === 'complete' && result && (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Check className="h-4 w-4 text-success" />
                    <span className="text-sm font-medium text-foreground">{t('datasets.synthesisComplete')}</span>
                  </div>
                  <button
                    onClick={(e) => { e.stopPropagation(); handleDismissBanner() }}
                    className="text-muted-foreground hover:text-foreground transition-colors"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
                <div className="flex gap-4 text-xs">
                  <span>{result.total} {t('datasets.generated')}</span>
                  <span className="text-success">{result.persisted} {t('datasets.saved')}</span>
                  <span className="text-muted-foreground">{result.discarded} {t('datasets.discarded')}</span>
                </div>
              </div>
            )}
            {status === 'error' && (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <AlertCircle className="h-4 w-4 text-destructive" />
                    <span className="text-sm font-medium text-destructive">{t('datasets.synthesisFailed')}</span>
                  </div>
                  <button
                    onClick={(e) => { e.stopPropagation(); handleDismissBanner() }}
                    className="text-muted-foreground hover:text-foreground transition-colors"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
                <p className="text-xs text-muted-foreground truncate">{errorMessage}</p>
              </div>
            )}
          </div>
        </div>,
        document.body
      )
    : null

  // --- Render ---

  return (
    <>
    {floatingBanner}
    <Dialog open={open} onOpenChange={(isOpen) => { if (!isOpen) handleClose(); else onOpenChange(true) }}>
      <DialogContent className={status === 'review' || status === 'submitting' ? 'sm:max-w-4xl' : 'sm:max-w-2xl'}>
        <DialogHeader>
          <DialogTitle>
            {status === 'review' || status === 'submitting' ? t('datasets.synthesisReviewTitle') : t('datasets.synthesisGenerateTitle')}
          </DialogTitle>
          <DialogDescription>
            {status === 'review' || status === 'submitting'
              ? t('datasets.synthesisReviewDescription')
              : t('datasets.synthesisGenerateDescription')}
          </DialogDescription>
        </DialogHeader>

        {status === 'idle' && (
          <div className="space-y-4">
            {/* Scenario Context */}
            <div>
              <label className="text-sm font-medium text-foreground block mb-1.5">
                {t('datasets.scenarioContext')} <span className="text-xs text-muted-foreground font-normal">{t('datasets.optional')}</span>
              </label>
              <Textarea
                value={scenarioContext}
                onChange={(e) => setScenarioContext(e.target.value)}
                placeholder={t('datasets.scenarioPlaceholder')}
                rows={2}
                className="text-sm min-h-0"
              />
            </div>

            {/* Persona List */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <label className="text-sm font-medium text-foreground">{t('datasets.personas')}</label>
                <div className="flex items-center gap-2">
                  {personas.length > 0 && (
                    <button
                      onClick={toggleSelectAll}
                      className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                    >
                      {selectedPersonaIds.size === personas.length ? t('datasets.deselectAll') : t('datasets.selectAll')}
                    </button>
                  )}
                </div>
              </div>

              {personaLoading ? (
                <div className="text-sm text-muted-foreground animate-pulse py-4 text-center">
                  {t('datasets.loadingPersonas')}
                </div>
              ) : personas.length === 0 ? (
                <div className="text-sm text-muted-foreground py-4 text-center border border-dashed border-border rounded-lg">
                  {t('datasets.noPersonas')}
                </div>
              ) : (
                <div className="max-h-80 overflow-y-auto">
                  <div className="space-y-2 pr-1">
                    {personas.map((persona) =>
                      editingPersonaId === persona.id ? (
                        <PersonaEditor
                          key={persona.id}
                          persona={persona}
                          onSave={handleEditPersona}
                          onCancel={() => setEditingPersonaId(null)}
                        />
                      ) : (
                        <PersonaCard
                          key={persona.id}
                          persona={persona}
                          selected={selectedPersonaIds.has(persona.id)}
                          onToggleSelect={() => togglePersona(persona.id)}
                          onEdit={() => {
                            setEditingPersonaId(persona.id)
                            setShowAddForm(false)
                          }}
                          onDelete={() => handleDeletePersona(persona.id)}
                        />
                      )
                    )}
                  </div>
                </div>
              )}

              {/* Delete confirmation banner */}
              {deleteConfirmId && (
                <div className="flex items-center gap-2 mt-2 p-2 rounded-md bg-destructive/10 border border-destructive/30 text-sm">
                  <span className="text-destructive">{t('datasets.deleteConfirm', { id: deleteConfirmId })}</span>
                  <Button
                    variant="destructive"
                    size="sm"
                    className="h-6 text-xs"
                    onClick={() => handleDeletePersona(deleteConfirmId)}
                  >
                    {t('common.confirm')}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 text-xs"
                    onClick={() => setDeleteConfirmId(null)}
                  >
                    {t('common.cancel')}
                  </Button>
                </div>
              )}

              {/* Add persona form */}
              {showAddForm ? (
                <div className="mt-2">
                  <PersonaEditor
                    onSave={handleAddPersona}
                    onCancel={() => setShowAddForm(false)}
                  />
                </div>
              ) : (
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-2 w-full"
                  onClick={() => {
                    setShowAddForm(true)
                    setEditingPersonaId(null)
                  }}
                >
                  <UserPlus className="h-3.5 w-3.5 mr-1.5" />
                  {t('datasets.addPersona')}
                </Button>
              )}
            </div>

            {/* Run Config */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-sm font-medium text-foreground block mb-1.5">
                  {t('datasets.conversationsPerPersona')}
                </label>
                <input
                  type="number"
                  min={1}
                  max={50}
                  value={numConversations}
                  onChange={(e) => setNumConversations(Math.max(1, parseInt(e.target.value) || 1))}
                  className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                />
              </div>
              <div>
                <label className="text-sm font-medium text-foreground block mb-1.5">
                  {t('datasets.maxTurnsPerConversation')}
                </label>
                <input
                  type="number"
                  min={1}
                  max={50}
                  value={maxTurns}
                  onChange={(e) => setMaxTurns(Math.max(1, parseInt(e.target.value) || 1))}
                  className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                />
              </div>
            </div>

            {/* Action bar */}
            <div className="flex items-center justify-between pt-1">
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={handleExport} disabled={personas.length === 0}>
                  <Download className="h-3.5 w-3.5 mr-1.5" />
                  {t('common.export')}
                </Button>
                <Button variant="outline" size="sm" onClick={() => importInputRef.current?.click()}>
                  <Upload className="h-3.5 w-3.5 mr-1.5" />
                  {t('common.import')}
                </Button>
                <input
                  ref={importInputRef}
                  type="file"
                  accept=".json"
                  onChange={handleImport}
                  className="hidden"
                />
              </div>
              <div className="flex gap-2">
                <Button variant="outline" onClick={handleClose}>{t('common.cancel')}</Button>
                <Button onClick={handleGenerate} disabled={selectedPersonaIds.size === 0}>
                  {t('datasets.generateButton')}
                  {selectedPersonaIds.size > 0 && (
                    <span className="ml-1.5 text-xs opacity-70">
                      ({selectedPersonaIds.size} persona{selectedPersonaIds.size !== 1 ? 's' : ''})
                    </span>
                  )}
                </Button>
              </div>
            </div>
          </div>
        )}

        {status === 'running' && (
          <div className="space-y-4">
            <div className="text-sm text-muted-foreground animate-pulse">
              {progressText}
            </div>
            {conversations.length > 0 && (
              <div className="max-h-48 overflow-y-auto space-y-1.5">
                {conversations.map((conv, i) => (
                  <div key={i} className="flex items-center gap-2 text-sm">
                    <Badge variant={conv.passed ? 'outline' : 'destructive'} className="text-xs">
                      {conv.passed ? 'PASS' : 'FAIL'}
                    </Badge>
                    <span className="text-muted-foreground">
                      {conv.personaId} #{conv.conversationIndex + 1}
                    </span>
                    {conv.hasToolCalls && (
                      <Badge variant="outline" className="text-xs gap-1 bg-warning/10 border-warning/30">
                        <Wrench className="h-2.5 w-2.5" />
                        tools
                      </Badge>
                    )}
                    <span className="text-xs text-muted-foreground ml-auto">
                      score: {conv.score?.toFixed(1)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {status === 'complete' && result && (
          <div className="space-y-4">
            <div className="rounded-lg border border-border p-4 space-y-2">
              <p className="text-sm font-medium text-foreground">{t('datasets.synthesisComplete')}</p>
              <div className="grid grid-cols-3 gap-2 text-center">
                <div>
                  <p className="text-2xl font-bold text-foreground">{result.total}</p>
                  <p className="text-xs text-muted-foreground">{t('datasets.generated')}</p>
                </div>
                <div>
                  <p className="text-2xl font-bold text-success">{result.persisted}</p>
                  <p className="text-xs text-muted-foreground">{t('datasets.persisted')}</p>
                </div>
                <div>
                  <p className="text-2xl font-bold text-muted-foreground">{result.discarded}</p>
                  <p className="text-xs text-muted-foreground">{t('datasets.discarded')}</p>
                </div>
              </div>
              <p className="text-xs text-muted-foreground mt-2">
                {result.persisted > 0
                  ? t('datasets.failingConversationsAdded', { count: result.persisted })
                  : t('datasets.noFailingConversations')}
              </p>
            </div>
            {conversations.length > 0 && (
              <div className="max-h-36 overflow-y-auto space-y-1.5">
                {conversations.map((conv, i) => (
                  <div key={i} className="flex items-center gap-2 text-sm">
                    <Badge variant={conv.passed ? 'outline' : 'destructive'} className="text-xs">
                      {conv.passed ? 'PASS' : 'FAIL'}
                    </Badge>
                    <span className="text-muted-foreground">
                      {conv.personaId} #{conv.conversationIndex + 1}
                    </span>
                    {conv.hasToolCalls && (
                      <Badge variant="outline" className="text-xs gap-1 bg-warning/10 border-warning/30">
                        <Wrench className="h-2.5 w-2.5" />
                        tools
                      </Badge>
                    )}
                    {conv.caseId && (
                      <span className="text-xs text-success ml-auto">{t('datasets.saved')}</span>
                    )}
                  </div>
                ))}
              </div>
            )}
            <div className="flex justify-end">
              <Button onClick={handleClose}>{t('common.close')}</Button>
            </div>
          </div>
        )}

        {status === 'error' && (
          <div className="space-y-4">
            <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-4">
              <p className="text-sm text-destructive">{errorMessage}</p>
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={handleClose}>{t('common.close')}</Button>
              <Button onClick={handleGenerate}>{t('datasets.retry')}</Button>
            </div>
          </div>
        )}

        {(status === 'review' || status === 'submitting') && (
          <div className="space-y-4">
            {/* Stats row */}
            <div className="flex items-center gap-4 text-sm">
              <Badge variant="outline" className="text-xs">
                {t('datasets.conversations', { count: reviewConversations.length })}
              </Badge>
              <span className="text-success">{reviewApprovedCount} {t('datasets.approved')}</span>
              <span className="text-destructive">{reviewRejectedCount} {t('datasets.rejected')}</span>
              <span className="text-muted-foreground">{reviewPendingCount} {t('datasets.pending')}</span>
            </div>

            {/* Bulk action buttons */}
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                className="text-success border-success/30 hover:bg-success/10"
                onClick={handleApproveAll}
                disabled={reviewPendingCount === 0 || status === 'submitting'}
              >
                <Check className="h-3.5 w-3.5 mr-1" />
                {t('datasets.approveAllPending')}
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="text-destructive border-destructive/30 hover:bg-destructive/10"
                onClick={handleRejectAll}
                disabled={reviewPendingCount === 0 || status === 'submitting'}
              >
                <X className="h-3.5 w-3.5 mr-1" />
                {t('datasets.rejectAllPending')}
              </Button>
            </div>

            {/* Review error */}
            {reviewError && (
              <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-3">
                <p className="text-sm text-destructive">{reviewError}</p>
              </div>
            )}

            {/* Conversation review cards */}
            <ScrollArea className="max-h-[50vh]">
              <div className="space-y-3 pr-3">
                {reviewConversations.map((conv, i) => (
                  <ReviewConversation
                    key={i}
                    index={i}
                    conversation={conv}
                    decision={getDecision(i)}
                    editing={editingIndex === i}
                    onApprove={(idx) => handleApproveConversation(idx)}
                    onReject={handleRejectConversation}
                    onUndoDecision={handleUndoDecision}
                    onStartEdit={(idx) => setEditingIndex(idx)}
                    onSaveEdit={(idx, edits) => {
                      handleApproveConversation(idx, edits)
                      setEditingIndex(null)
                    }}
                    onCancelEdit={() => setEditingIndex(null)}
                  />
                ))}
              </div>
            </ScrollArea>

            {/* Bottom action bar */}
            <div className="flex items-center justify-between pt-2 border-t border-border">
              <Button variant="outline" onClick={handleClose} disabled={status === 'submitting'}>
                {t('common.cancel')}
              </Button>
              <Button
                onClick={handleSubmitReview}
                disabled={!allDecided || status === 'submitting'}
              >
                {status === 'submitting' ? t('datasets.submitting') : t('datasets.submitReview')}
                {allDecided && status !== 'submitting' && (
                  <span className="ml-1.5 text-xs opacity-70">
                    {t('datasets.reviewSummary', { approved: reviewApprovedCount, rejected: reviewRejectedCount })}
                  </span>
                )}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
    </>
  )
}
