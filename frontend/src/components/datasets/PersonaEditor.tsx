import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import type { Persona } from './PersonaCard'

const LANGUAGES = [
  { code: 'en', name: 'English' },
  { code: 'es', name: 'Spanish' },
  { code: 'zh', name: 'Chinese' },
  { code: 'ar', name: 'Arabic' },
  { code: 'pt', name: 'Portuguese' },
  { code: 'fr', name: 'French' },
  { code: 'de', name: 'German' },
  { code: 'ja', name: 'Japanese' },
  { code: 'ko', name: 'Korean' },
  { code: 'hi', name: 'Hindi' },
  { code: 'it', name: 'Italian' },
  { code: 'ru', name: 'Russian' },
  { code: 'nl', name: 'Dutch' },
  { code: 'th', name: 'Thai' },
  { code: 'vi', name: 'Vietnamese' },
  { code: 'tr', name: 'Turkish' },
  { code: 'pl', name: 'Polish' },
  { code: 'sv', name: 'Swedish' },
  { code: 'id', name: 'Indonesian' },
  { code: 'uk', name: 'Ukrainian' },
] as const

const CHANNELS = [
  { value: 'text', label: 'Text' },
  { value: 'voice', label: 'Voice' },
] as const

interface PersonaEditorProps {
  persona?: Persona
  onSave: (persona: Persona) => void
  onCancel: () => void
}

function toKebabCase(str: string): string {
  return str
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
}

export function PersonaEditor({ persona, onSave, onCancel }: PersonaEditorProps) {
  const { t } = useTranslation()
  const isEditing = !!persona

  const [id, setId] = useState(persona?.id ?? '')
  const [role, setRole] = useState(persona?.role ?? '')
  const [traits, setTraits] = useState(persona?.traits.join(', ') ?? '')
  const [communicationStyle, setCommunicationStyle] = useState(persona?.communication_style ?? '')
  const [goal, setGoal] = useState(persona?.goal ?? '')
  const [edgeCases, setEdgeCases] = useState(persona?.edge_cases.join('\n') ?? '')
  const [behaviorCriteria, setBehaviorCriteria] = useState(persona?.behavior_criteria.join('\n') ?? '')
  const [language, setLanguage] = useState(persona?.language ?? 'en')
  const [channel, setChannel] = useState(persona?.channel ?? 'text')
  const [idManuallyEdited, setIdManuallyEdited] = useState(false)

  // Auto-generate id from role when creating (unless user manually edited)
  useEffect(() => {
    if (!isEditing && !idManuallyEdited && role) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- id is both auto-derived from role and independently user-editable
      setId(toKebabCase(role))
    }
  }, [role, isEditing, idManuallyEdited])

  function handleSave() {
    if (!id.trim() || !role.trim()) return

    const personaData: Persona = {
      id: id.trim(),
      role: role.trim(),
      traits: traits
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean),
      communication_style: communicationStyle.trim(),
      goal: goal.trim(),
      edge_cases: edgeCases
        .split('\n')
        .map((e) => e.trim())
        .filter(Boolean),
      behavior_criteria: behaviorCriteria
        .split('\n')
        .map((b) => b.trim())
        .filter(Boolean),
      language,
      channel,
    }
    onSave(personaData)
  }

  return (
    <div className="space-y-3 rounded-lg border border-border bg-card p-4">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs font-medium text-muted-foreground block mb-1">{t('datasets.personaId')}</label>
          <Input
            value={id}
            onChange={(e) => {
              setId(e.target.value)
              if (!isEditing) setIdManuallyEdited(true)
            }}
            disabled={isEditing}
            placeholder="persona-id"
            className="h-8 text-sm"
          />
        </div>
        <div>
          <label className="text-xs font-medium text-muted-foreground block mb-1">
            {t('datasets.personaRole')} <span className="text-destructive">*</span>
          </label>
          <Input
            value={role}
            onChange={(e) => setRole(e.target.value)}
            placeholder={t('datasets.personaRolePlaceholder')}
            className="h-8 text-sm"
          />
        </div>
      </div>

      <div>
        <label className="text-xs font-medium text-muted-foreground block mb-1">
          {t('datasets.personaTraits')} <span className="text-muted-foreground/60">{t('datasets.commaSeparated')}</span>
        </label>
        <Input
          value={traits}
          onChange={(e) => setTraits(e.target.value)}
          placeholder={t('datasets.personaTraitsPlaceholder')}
          className="h-8 text-sm"
        />
      </div>

      <div>
        <label className="text-xs font-medium text-muted-foreground block mb-1">{t('datasets.personaCommunicationStyle')}</label>
        <Input
          value={communicationStyle}
          onChange={(e) => setCommunicationStyle(e.target.value)}
          placeholder={t('datasets.personaCommunicationStylePlaceholder')}
          className="h-8 text-sm"
        />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs font-medium text-muted-foreground block mb-1">{t('datasets.personaLanguage')}</label>
          <Select value={language} onValueChange={setLanguage}>
            <SelectTrigger className="h-8 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {LANGUAGES.map(lang => (
                <SelectItem key={lang.code} value={lang.code}>
                  {lang.name} ({lang.code})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div>
          <label className="text-xs font-medium text-muted-foreground block mb-1">{t('datasets.personaChannel')}</label>
          <Select value={channel} onValueChange={setChannel}>
            <SelectTrigger className="h-8 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {CHANNELS.map(ch => (
                <SelectItem key={ch.value} value={ch.value}>
                  {ch.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <div>
        <label className="text-xs font-medium text-muted-foreground block mb-1">{t('datasets.personaGoal')}</label>
        <Textarea
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          placeholder={t('datasets.personaGoalPlaceholder')}
          rows={2}
          className="text-sm min-h-0"
        />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs font-medium text-muted-foreground block mb-1">
            {t('datasets.personaEdgeCases')} <span className="text-muted-foreground/60">{t('datasets.onePerLine')}</span>
          </label>
          <Textarea
            value={edgeCases}
            onChange={(e) => setEdgeCases(e.target.value)}
            placeholder={"Ask same question twice\nProvide invalid input"}
            rows={3}
            className="text-sm min-h-0"
          />
        </div>
        <div>
          <label className="text-xs font-medium text-muted-foreground block mb-1">
            {t('datasets.personaBehaviorCriteria')} <span className="text-muted-foreground/60">{t('datasets.onePerLine')}</span>
          </label>
          <Textarea
            value={behaviorCriteria}
            onChange={(e) => setBehaviorCriteria(e.target.value)}
            placeholder={"Should use simple language\nMust stay in character"}
            rows={3}
            className="text-sm min-h-0"
          />
        </div>
      </div>

      <div className="flex justify-end gap-2 pt-1">
        <Button variant="outline" size="sm" onClick={onCancel}>
          {t('common.cancel')}
        </Button>
        <Button size="sm" onClick={handleSave} disabled={!id.trim() || !role.trim()}>
          {isEditing ? t('datasets.update') : t('common.create')}
        </Button>
      </div>
    </div>
  )
}
