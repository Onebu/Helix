import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Check, X, Pencil, ChevronDown, ChevronUp } from 'lucide-react'

export interface ConversationEdits {
  chat_history?: Array<{ role: string; content: string }>
  variables?: Record<string, unknown>
  expected_output?: Record<string, unknown>
  tags?: string[]
  name?: string
}

export interface ReviewConversationData {
  persona_id: string
  chat_history: Array<{ role: string; content: string }>
  variables: Record<string, unknown>
  turns: number
  score: number | null
  passed: boolean | null
  behavior_criteria: string[] | null
}

interface ReviewConversationProps {
  index: number
  conversation: ReviewConversationData
  decision: 'pending' | 'approved' | 'rejected'
  editing: boolean
  onApprove: (index: number) => void
  onReject: (index: number) => void
  onUndoDecision: (index: number) => void
  onStartEdit: (index: number) => void
  onSaveEdit: (index: number, edits: ConversationEdits) => void
  onCancelEdit: () => void
}

function truncate(text: string, max: number): string {
  if (text.length <= max) return text
  return text.slice(0, max) + '...'
}

function scoreColor(passed: boolean | null): string {
  if (passed === null) return 'bg-muted text-muted-foreground'
  return passed ? 'bg-success/10 text-success border-success/30' : 'bg-warning/10 text-warning border-warning/30'
}

export function ReviewConversation({
  index,
  conversation,
  decision,
  editing,
  onApprove,
  onReject,
  onUndoDecision,
  onStartEdit,
  onSaveEdit,
  onCancelEdit,
}: ReviewConversationProps) {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState(false)

  // Edit state
  const [editMessages, setEditMessages] = useState<Array<{ role: string; content: string }>>([])
  const [editCriteria, setEditCriteria] = useState('')
  const [editTags, setEditTags] = useState('synthetic')
  const [editName, setEditName] = useState('')

  function handleStartEdit() {
    // Initialize edit state from conversation
    setEditMessages(conversation.chat_history.map((m) => ({ ...m })))
    setEditCriteria(conversation.behavior_criteria?.join('\n') || '')
    setEditTags('synthetic')
    setEditName('')
    onStartEdit(index)
  }

  function handleSaveEdit() {
    const edits: ConversationEdits = {}

    // Only include chat_history if modified
    const messagesChanged = editMessages.some(
      (m, i) =>
        i >= conversation.chat_history.length ||
        m.content !== conversation.chat_history[i].content ||
        m.role !== conversation.chat_history[i].role
    )
    if (messagesChanged) {
      edits.chat_history = editMessages
    }

    // Only include expected_output if criteria changed
    const originalCriteria = conversation.behavior_criteria?.join('\n') || ''
    if (editCriteria.trim() !== originalCriteria.trim()) {
      const criteria = editCriteria
        .split('\n')
        .map((l) => l.trim())
        .filter(Boolean)
      edits.expected_output = { behavior: criteria }
    }

    // Tags always included if non-empty
    const tags = editTags
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean)
    if (tags.length > 0) {
      edits.tags = tags
    }

    // Name only if provided
    if (editName.trim()) {
      edits.name = editName.trim()
    }

    onSaveEdit(index, edits)
  }

  function updateMessageContent(msgIndex: number, content: string) {
    setEditMessages((prev) =>
      prev.map((m, i) => (i === msgIndex ? { ...m, content } : m))
    )
  }

  const previewMessages = conversation.chat_history.slice(0, 3)
  const isRejected = decision === 'rejected'

  return (
    <Card className={`transition-opacity ${isRejected ? 'opacity-50' : ''}`}>
      <CardContent className="p-4 space-y-3">
        {/* Header row: persona ID + score badge */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Badge variant="secondary" className="text-xs">
              {conversation.persona_id}
            </Badge>
            <span className="text-xs text-muted-foreground">
              #{index + 1} &middot; {t('datasets.turns', { count: conversation.turns })}
            </span>
          </div>
          <Badge variant="outline" className={`text-xs ${scoreColor(conversation.passed)}`}>
            {conversation.score !== null ? t('datasets.score', { score: conversation.score.toFixed(1) }) : t('datasets.noScore')}
          </Badge>
        </div>

        {/* Message preview */}
        {!editing && (
          <div className="space-y-1.5">
            {previewMessages.map((msg, i) => (
              <div key={i} className="text-sm">
                <span className="text-xs font-medium text-muted-foreground mr-1.5">
                  {msg.role}:
                </span>
                <span className={msg.role === 'user' ? 'text-muted-foreground' : 'text-foreground'}>
                  {truncate(msg.content, 150)}
                </span>
              </div>
            ))}
            {conversation.chat_history.length > 3 && !expanded && (
              <span className="text-xs text-muted-foreground">
                {t('datasets.moreMessages', { count: conversation.chat_history.length - 3 })}
              </span>
            )}
          </div>
        )}

        {/* Expandable details (only when not editing) */}
        {!editing && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
            {expanded ? t('datasets.hideDetails') : t('datasets.showDetails')}
          </button>
        )}

        {expanded && !editing && (
          <div className="space-y-3 border-t border-border pt-3">
            {/* Full chat history */}
            <div>
              <p className="text-xs font-medium text-muted-foreground mb-1.5">{t('datasets.fullChatHistory')}</p>
              <div className="max-h-48 overflow-y-auto space-y-1.5 rounded-md border border-border p-2">
                {conversation.chat_history.map((msg, i) => (
                  <div key={i} className="text-sm">
                    <span className="text-xs font-medium text-muted-foreground mr-1.5">
                      {msg.role}:
                    </span>
                    <span className={msg.role === 'user' ? 'text-muted-foreground' : 'text-foreground'}>
                      {msg.content}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Variables */}
            {Object.keys(conversation.variables).length > 0 && (
              <div>
                <p className="text-xs font-medium text-muted-foreground mb-1.5">{t('datasets.variables')}</p>
                <pre className="text-xs bg-muted/50 rounded-md p-2 overflow-x-auto">
                  {JSON.stringify(conversation.variables, null, 2)}
                </pre>
              </div>
            )}

            {/* Behavior criteria */}
            {conversation.behavior_criteria && conversation.behavior_criteria.length > 0 && (
              <div>
                <p className="text-xs font-medium text-muted-foreground mb-1.5">{t('datasets.personaBehaviorCriteria')}</p>
                <ul className="text-xs space-y-0.5 list-disc list-inside text-muted-foreground">
                  {conversation.behavior_criteria.map((c, i) => (
                    <li key={i}>{c}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {/* Edit mode */}
        {editing && (
          <div className="space-y-3 border-t border-border pt-3">
            {/* Messages editor */}
            <div>
              <p className="text-xs font-medium text-muted-foreground mb-1.5">{t('datasets.messages')}</p>
              <div className="space-y-2">
                {editMessages.map((msg, i) => (
                  <div key={i}>
                    <label className="text-xs font-medium text-muted-foreground">{msg.role}</label>
                    <textarea
                      value={msg.content}
                      onChange={(e) => updateMessageContent(i, e.target.value)}
                      rows={2}
                      className="flex w-full rounded-md border border-input bg-transparent px-3 py-1.5 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring mt-0.5"
                    />
                  </div>
                ))}
              </div>
            </div>

            {/* Behavior criteria */}
            <div>
              <label className="text-xs font-medium text-muted-foreground">
                {t('datasets.behaviorCriteria')}
              </label>
              <textarea
                value={editCriteria}
                onChange={(e) => setEditCriteria(e.target.value)}
                rows={3}
                placeholder="greets warmly&#10;confirms department"
                className="flex w-full rounded-md border border-input bg-transparent px-3 py-1.5 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring mt-0.5"
              />
            </div>

            {/* Tags */}
            <div>
              <label className="text-xs font-medium text-muted-foreground">
                {t('datasets.tagsCommaSeparated')}
              </label>
              <input
                value={editTags}
                onChange={(e) => setEditTags(e.target.value)}
                placeholder="synthetic, custom"
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring mt-0.5"
              />
            </div>

            {/* Name */}
            <div>
              <label className="text-xs font-medium text-muted-foreground">
                {t('datasets.nameOptional')}
              </label>
              <input
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                placeholder={t('datasets.testCaseName')}
                className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring mt-0.5"
              />
            </div>

            {/* Edit action buttons */}
            <div className="flex justify-end gap-2 pt-1">
              <Button variant="outline" size="sm" onClick={onCancelEdit}>
                {t('common.cancel')}
              </Button>
              <Button size="sm" onClick={handleSaveEdit}>
                {t('datasets.saveAndApprove')}
              </Button>
            </div>
          </div>
        )}

        {/* Action buttons (only when not editing) */}
        {!editing && (
          <div className="flex items-center gap-2 pt-1">
            {decision === 'pending' && (
              <>
                <Button
                  variant="outline"
                  size="sm"
                  className="text-success border-success/30 hover:bg-success/10"
                  onClick={() => onApprove(index)}
                >
                  <Check className="h-3.5 w-3.5 mr-1" />
                  {t('datasets.approve')}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="text-destructive border-destructive/30 hover:bg-destructive/10"
                  onClick={() => onReject(index)}
                >
                  <X className="h-3.5 w-3.5 mr-1" />
                  {t('datasets.reject')}
                </Button>
                <Button variant="secondary" size="sm" onClick={handleStartEdit}>
                  <Pencil className="h-3.5 w-3.5 mr-1" />
                  {t('datasets.editAndApprove')}
                </Button>
              </>
            )}
            {decision === 'approved' && (
              <>
                <Badge className="bg-success/10 text-success border-success/30">
                  {t('datasets.approved')}
                </Badge>
                <button
                  onClick={() => onUndoDecision(index)}
                  className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                >
                  {t('datasets.undo')}
                </button>
              </>
            )}
            {decision === 'rejected' && (
              <>
                <Badge variant="destructive">{t('datasets.rejected')}</Badge>
                <button
                  onClick={() => onUndoDecision(index)}
                  className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                >
                  {t('datasets.undo')}
                </button>
              </>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
