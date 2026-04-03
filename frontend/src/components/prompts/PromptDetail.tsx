import { useState, useMemo, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { ChevronDown, ChevronRight, FileText, Wrench, FlaskConical, Code2, Pencil, Plus, X, Check } from 'lucide-react'
import {
  getPromptApiPromptsPromptIdGet,
  listCasesApiPromptsPromptIdDatasetGet,
  updateVariableDefinitionsApiPromptsPromptIdVariableDefinitionsPut,
  updateToolsApiPromptsPromptIdToolsPut,
} from '@/client/sdk.gen'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from '@/components/ui/collapsible'

interface PromptDetailProps {
  promptId: string
  onEditTemplate?: () => void
}

interface VariableDefinition {
  name: string
  var_type?: string
  description?: string | null
  is_anchor?: boolean
  items_schema?: VariableDefinition[] | null
}

interface ToolFunction {
  name: string
  description?: string
  parameters?: {
    type?: string
    properties?: Record<string, ToolParameter>
    required?: string[]
  }
}

interface ToolParameter {
  type?: string
  description?: string
  items?: { type?: string }
  enum?: string[]
}

interface Tool {
  type?: string
  function?: ToolFunction
}

// ---------------------------------------------------------------------------
// Skeleton
// ---------------------------------------------------------------------------

function PromptDetailSkeleton() {
  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-border bg-card overflow-hidden">
        <div className="px-4 py-3 border-b border-border">
          <Skeleton className="h-7 w-[200px]" />
        </div>
        <div className="p-4 space-y-3">
          <Skeleton className="h-4 w-[350px]" />
          <div className="flex gap-2">
            <Skeleton className="h-5 w-16 rounded-full" />
            <Skeleton className="h-5 w-16 rounded-full" />
            <Skeleton className="h-5 w-16 rounded-full" />
          </div>
        </div>
      </div>
      <div className="rounded-lg border border-border bg-card overflow-hidden">
        <div className="p-4">
          <Skeleton className="h-[200px] w-full" />
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Section 1: Template Preview
// ---------------------------------------------------------------------------

const COLLAPSED_LINE_LIMIT = 20

function highlightTemplateVariables(text: string): React.ReactNode[] {
  const parts = text.split(/(\{\{.*?\}\})/g)
  return parts.map((part, i) => {
    if (/^\{\{.*\}\}$/.test(part)) {
      return (
        <span key={i} className="text-primary font-semibold bg-primary/10 rounded px-0.5">
          {part}
        </span>
      )
    }
    return <span key={i}>{part}</span>
  })
}

function TemplatePreviewSection({
  template,
  onEdit,
}: {
  template: string
  onEdit?: () => void
}) {
  const { t } = useTranslation()
  const lines = template.split('\n')
  const isLong = lines.length > COLLAPSED_LINE_LIMIT
  const [expanded, setExpanded] = useState(false)

  const displayText =
    isLong && !expanded
      ? lines.slice(0, COLLAPSED_LINE_LIMIT).join('\n')
      : template

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      <div className="px-4 py-3 border-b border-border flex items-center justify-between">
        <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
          <FileText className="h-4 w-4" />
          {t('prompts.templatePreview')}
        </h3>
        {onEdit && (
          <Button variant="ghost" size="sm" onClick={onEdit}>
            {t('prompts.editTemplate')}
          </Button>
        )}
      </div>
      <div className="p-4">
        <pre className="overflow-auto rounded bg-muted p-4 text-sm text-foreground whitespace-pre-wrap break-words font-mono leading-relaxed">
          {highlightTemplateVariables(displayText)}
          {isLong && !expanded && (
            <span className="text-muted-foreground">{'\n...'}</span>
          )}
        </pre>
        {isLong && (
          <Button
            variant="ghost"
            size="sm"
            className="mt-2"
            onClick={() => setExpanded(!expanded)}
          >
            {expanded
              ? t('prompts.showLess')
              : t('prompts.showAll', { count: lines.length })}
          </Button>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Section 2: Variables & Schema (merged)
// ---------------------------------------------------------------------------

function VariableSchemaRow({ varDef }: { varDef: VariableDefinition }) {
  const [expanded, setExpanded] = useState(false)
  const { t } = useTranslation()
  const hasSubFields = varDef.items_schema && varDef.items_schema.length > 0

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2">
        {hasSubFields ? (
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex items-center gap-1 text-muted-foreground hover:text-foreground transition-colors"
          >
            {expanded ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
          </button>
        ) : (
          <span className="w-5" />
        )}
        <code className="font-mono text-sm font-medium">{varDef.name}</code>
        <Badge variant="secondary" className="text-xs">
          {varDef.var_type === 'array' && hasSubFields
            ? 'array<object>'
            : varDef.var_type || 'string'}
        </Badge>
        {varDef.is_anchor && (
          <Badge
            variant="outline"
            className="bg-success/20 text-success border-success/30 text-xs"
          >
            {t('prompts.anchor')}
          </Badge>
        )}
        {varDef.description && (
          <span className="text-xs text-muted-foreground truncate">
            {varDef.description}
          </span>
        )}
      </div>

      {expanded && hasSubFields && (
        <div className="ml-7 mt-1 border-l-2 border-primary/20 pl-3 space-y-1">
          {varDef.items_schema!.map((subField, i) => (
            <div key={i} className="flex items-center gap-2 py-0.5">
              <code className="text-sm text-muted-foreground font-mono">
                {subField.name}
              </code>
              <Badge variant="secondary" className="text-xs">
                {subField.var_type || 'string'}
              </Badge>
              {subField.is_anchor && (
                <Badge
                  variant="outline"
                  className="bg-success/20 text-success border-success/30 text-xs"
                >
                  {t('prompts.anchor')}
                </Badge>
              )}
              {subField.description && (
                <span className="text-xs text-muted-foreground truncate">
                  {subField.description}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Edit mode: inline variable editor
// ---------------------------------------------------------------------------

interface EditableVariableDef {
  name: string
  var_type: string
  description: string
  is_anchor: boolean
  items_schema: EditableVariableDef[]
}

function toEditable(v: VariableDefinition): EditableVariableDef {
  return {
    name: v.name,
    var_type: v.var_type || 'string',
    description: v.description || '',
    is_anchor: v.is_anchor || false,
    items_schema: (v.items_schema || []).map(toEditable),
  }
}

function toApiFormat(v: EditableVariableDef): Record<string, unknown> {
  const out: Record<string, unknown> = {
    name: v.name,
    var_type: v.var_type,
    is_anchor: v.is_anchor,
  }
  if (v.description) out.description = v.description
  if (v.items_schema.length > 0) out.items_schema = v.items_schema.map(toApiFormat)
  return out
}

function VariableEditRow({
  variable,
  onChange,
  onRemove,
}: {
  variable: EditableVariableDef
  onChange: (updated: EditableVariableDef) => void
  onRemove: () => void
}) {
  const { t } = useTranslation()
  const hasSubFields = variable.var_type === 'object' || variable.var_type === 'array'

  const updateSubField = (subIndex: number, updated: Partial<EditableVariableDef>) => {
    const newSubs = variable.items_schema.map((sf, i) =>
      i === subIndex ? { ...sf, ...updated } : sf
    )
    onChange({ ...variable, items_schema: newSubs })
  }

  const addSubField = () => {
    onChange({
      ...variable,
      items_schema: [...variable.items_schema, { name: '', var_type: 'string', description: '', is_anchor: false, items_schema: [] }],
    })
  }

  const removeSubField = (subIndex: number) => {
    onChange({
      ...variable,
      items_schema: variable.items_schema.filter((_, i) => i !== subIndex),
    })
  }

  const handleTypeChange = (value: string) => {
    if (value !== 'object' && value !== 'array') {
      onChange({ ...variable, var_type: value, items_schema: [] })
    } else {
      onChange({ ...variable, var_type: value })
    }
  }

  return (
    <div className="rounded-md border border-border p-3 space-y-2">
      <div className="flex items-start gap-2">
        <div className="flex-1 space-y-1">
          <label className="text-xs font-medium text-muted-foreground">{t('prompts.name')}</label>
          <Input
            value={variable.name}
            onChange={(e) => onChange({ ...variable, name: e.target.value })}
            className="h-8 text-sm font-mono"
            placeholder="variable_name"
          />
        </div>
        <div className="w-28 space-y-1">
          <label className="text-xs font-medium text-muted-foreground">{t('prompts.type')}</label>
          <Select value={variable.var_type} onValueChange={handleTypeChange}>
            <SelectTrigger className="h-8 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="string">string</SelectItem>
              <SelectItem value="number">number</SelectItem>
              <SelectItem value="boolean">boolean</SelectItem>
              <SelectItem value="object">object</SelectItem>
              <SelectItem value="array">array</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <Button variant="ghost" size="icon" className="mt-5 h-8 w-8 shrink-0" onClick={onRemove}>
          <X className="h-3 w-3" />
        </Button>
      </div>
      <div className="space-y-1">
        <label className="text-xs font-medium text-muted-foreground">{t('prompts.description')}</label>
        <Input
          value={variable.description}
          onChange={(e) => onChange({ ...variable, description: e.target.value })}
          className="h-8 text-sm"
          placeholder={t('prompts.descriptionPlaceholder')}
        />
      </div>
      <label className="flex items-center gap-2 text-xs">
        <input
          type="checkbox"
          checked={variable.is_anchor}
          onChange={(e) => onChange({ ...variable, is_anchor: e.target.checked })}
          className="rounded border-input"
        />
        <span className="text-foreground">{t('prompts.anchor')}</span>
        <span className="text-muted-foreground">{t('prompts.anchorHint')}</span>
      </label>

      {hasSubFields && (
        <div className="ml-4 mt-2 border-l-2 border-primary/20 pl-3 space-y-2">
          {variable.items_schema.map((sub, si) => (
            <div key={si} className="flex flex-col gap-1 rounded-md border border-border/60 bg-muted/30 p-2">
              <div className="flex items-start gap-2">
                <div className="flex-1">
                  <Input
                    value={sub.name}
                    onChange={(e) => updateSubField(si, { name: e.target.value })}
                    className="h-7 text-xs font-mono"
                    placeholder="field_name"
                  />
                </div>
                <Select value={sub.var_type} onValueChange={(v) => updateSubField(si, { var_type: v })}>
                  <SelectTrigger className="h-7 w-24 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="string">string</SelectItem>
                    <SelectItem value="number">number</SelectItem>
                    <SelectItem value="boolean">boolean</SelectItem>
                  </SelectContent>
                </Select>
                <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0" onClick={() => removeSubField(si)}>
                  <X className="h-3 w-3" />
                </Button>
              </div>
              <Input
                value={sub.description}
                onChange={(e) => updateSubField(si, { description: e.target.value })}
                className="h-7 text-xs"
                placeholder={t('prompts.descriptionPlaceholder')}
              />
              {!variable.is_anchor && (
                <label className="flex items-center gap-2 text-xs">
                  <input
                    type="checkbox"
                    checked={sub.is_anchor}
                    onChange={(e) => updateSubField(si, { is_anchor: e.target.checked })}
                    className="rounded border-input"
                  />
                  <span className="text-foreground">{t('prompts.anchor')}</span>
                </label>
              )}
            </div>
          ))}
          <Button variant="outline" size="sm" onClick={addSubField} className="w-full h-7 text-xs">
            <Plus className="h-3 w-3 mr-1" />
            {t('prompts.addSubField')}
          </Button>
        </div>
      )}
    </div>
  )
}

function VariablesSchemaSection({
  promptId,
  variableDefs,
}: {
  promptId: string
  variableDefs: VariableDefinition[]
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState<EditableVariableDef[]>([])
  const [saving, setSaving] = useState(false)

  const startEditing = useCallback(() => {
    setDraft(variableDefs.map(toEditable))
    setEditing(true)
  }, [variableDefs])

  const cancelEditing = () => {
    setEditing(false)
    setDraft([])
  }

  const updateDraftVar = (index: number, updated: EditableVariableDef) => {
    setDraft(prev => prev.map((v, i) => (i === index ? updated : v)))
  }

  const removeDraftVar = (index: number) => {
    setDraft(prev => prev.filter((_, i) => i !== index))
  }

  const addDraftVar = () => {
    setDraft(prev => [...prev, { name: '', var_type: 'string', description: '', is_anchor: false, items_schema: [] }])
  }

  const saveVariables = async () => {
    setSaving(true)
    try {
      await updateVariableDefinitionsApiPromptsPromptIdVariableDefinitionsPut({
        path: { prompt_id: promptId },
        body: { variables: draft.filter(v => v.name.trim()).map(toApiFormat) },
      })
      await queryClient.invalidateQueries({ queryKey: ['prompts', promptId] })
      setEditing(false)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      <div className="px-4 py-3 border-b border-border flex items-center justify-between">
        <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
          <Code2 className="h-4 w-4" />
          {t('prompts.variablesAndSchema')}
        </h3>
        {!editing ? (
          <Button variant="ghost" size="sm" onClick={startEditing}>
            <Pencil className="h-3 w-3 mr-1" />
            {t('common.edit')}
          </Button>
        ) : (
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="sm" onClick={cancelEditing} disabled={saving}>
              {t('common.cancel')}
            </Button>
            <Button size="sm" onClick={saveVariables} disabled={saving}>
              {saving ? (
                <>{t('prompts.saving')}</>
              ) : (
                <><Check className="h-3 w-3 mr-1" />{t('common.save')}</>
              )}
            </Button>
          </div>
        )}
      </div>
      <div className="p-4">
        {editing ? (
          <div className="space-y-3">
            {draft.map((varDef, i) => (
              <VariableEditRow
                key={i}
                variable={varDef}
                onChange={(updated) => updateDraftVar(i, updated)}
                onRemove={() => removeDraftVar(i)}
              />
            ))}
            <Button variant="outline" size="sm" onClick={addDraftVar} className="w-full">
              <Plus className="h-4 w-4 mr-1" />
              {t('prompts.addVariable')}
            </Button>
          </div>
        ) : variableDefs.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {t('prompts.noVariables')}
          </p>
        ) : (
          <div className="space-y-2">
            {variableDefs.map((varDef, i) => (
              <VariableSchemaRow key={i} varDef={varDef} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Section 3: Tools (reformatted)
// ---------------------------------------------------------------------------

function formatParamType(param: ToolParameter): string {
  if (param.type === 'array' && param.items?.type) {
    return `${param.items.type}[]`
  }
  if (param.enum && param.enum.length > 0) {
    return `enum(${param.enum.join(', ')})`
  }
  return param.type || 'string'
}

function ToolCard({ tool, index }: { tool: Tool; index: number }) {
  const { t } = useTranslation()
  const [showRaw, setShowRaw] = useState(false)
  const fn = tool.function

  if (!fn) return null

  const properties = fn.parameters?.properties || {}
  const required = new Set(fn.parameters?.required || [])
  const paramEntries = Object.entries(properties)

  return (
    <div className="rounded-lg border bg-muted/30 p-4 space-y-3">
      <div className="flex items-center gap-2">
        <code className="font-mono text-sm font-semibold text-foreground">
          {fn.name}
        </code>
        {index >= 0 && (
          <span className="text-xs text-muted-foreground">#{index + 1}</span>
        )}
      </div>

      {fn.description ? (
        <p className="text-sm text-muted-foreground">{fn.description}</p>
      ) : (
        <p className="text-sm text-muted-foreground italic">
          {t('prompts.noDescription')}
        </p>
      )}

      {paramEntries.length > 0 ? (
        <div className="space-y-1">
          <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
            {t('prompts.parameters')}
          </span>
          <div className="grid gap-1">
            {paramEntries.map(([paramName, param]) => (
              <div key={paramName} className="flex items-center gap-2 pl-2">
                <code className="font-mono text-xs">{paramName}</code>
                <Badge variant="secondary" className="text-xs py-0">
                  {formatParamType(param)}
                </Badge>
                {required.has(paramName) && (
                  <Badge
                    variant="outline"
                    className="text-xs py-0 text-warning border-warning/30 bg-warning/10"
                  >
                    {t('prompts.required')}
                  </Badge>
                )}
                {param.description && (
                  <span className="text-xs text-muted-foreground truncate">
                    {param.description}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground italic pl-2">
          {t('prompts.noParameters')}
        </p>
      )}

      <Collapsible>
        <CollapsibleTrigger asChild>
          <Button
            variant="ghost"
            size="sm"
            className="text-xs h-7 px-2"
            onClick={() => setShowRaw(!showRaw)}
          >
            {showRaw ? t('prompts.hideRawJson') : t('prompts.showRawJson')}
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <pre className="mt-2 overflow-auto rounded bg-muted p-3 text-xs text-foreground">
            {JSON.stringify(tool, null, 2)}
          </pre>
        </CollapsibleContent>
      </Collapsible>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tool Edit Row (JSON editor per tool)
// ---------------------------------------------------------------------------

function ToolEditRow({
  json,
  onChange,
  onRemove,
  error,
}: {
  json: string
  onChange: (json: string) => void
  onRemove: () => void
  error?: string
}) {
  const { t } = useTranslation()
  // Try to extract the name for display
  let toolName = ''
  try {
    const parsed = JSON.parse(json)
    toolName = parsed?.function?.name || parsed?.name || ''
  } catch { /* ignore */ }

  return (
    <div className="rounded-md border border-border p-3 space-y-2">
      <div className="flex items-center justify-between">
        <code className="font-mono text-sm font-medium">
          {toolName || t('prompts.newTool')}
        </code>
        <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0" onClick={onRemove}>
          <X className="h-3 w-3" />
        </Button>
      </div>
      <Textarea
        value={json}
        onChange={(e) => onChange(e.target.value)}
        className="font-mono text-xs min-h-[120px]"
        spellCheck={false}
      />
      {error && (
        <p className="text-xs text-destructive">{error}</p>
      )}
    </div>
  )
}

function ToolsSection({
  promptId,
  tools,
}: {
  promptId: string
  tools: Tool[]
}) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [drafts, setDrafts] = useState<string[]>([])
  const [errors, setErrors] = useState<(string | undefined)[]>([])
  const [saving, setSaving] = useState(false)

  const startEditing = useCallback(() => {
    setDrafts(tools.map(t => JSON.stringify(t, null, 2)))
    setErrors(tools.map(() => undefined))
    setEditing(true)
  }, [tools])

  const cancelEditing = () => {
    setEditing(false)
    setDrafts([])
    setErrors([])
  }

  const updateDraft = (index: number, json: string) => {
    setDrafts(prev => prev.map((d, i) => (i === index ? json : d)))
    setErrors(prev => prev.map((e, i) => {
      if (i !== index) return e
      try { JSON.parse(json); return undefined } catch { return t('prompts.invalidToolJson') }
    }))
  }

  const removeDraft = (index: number) => {
    setDrafts(prev => prev.filter((_, i) => i !== index))
    setErrors(prev => prev.filter((_, i) => i !== index))
  }

  const addDraft = () => {
    const empty = JSON.stringify({
      type: 'function',
      function: { name: '', description: '', parameters: { type: 'object', properties: {}, required: [] } },
    }, null, 2)
    setDrafts(prev => [...prev, empty])
    setErrors(prev => [...prev, undefined])
  }

  const saveTools = async () => {
    // Validate all JSON
    const newErrors = drafts.map(d => {
      try { JSON.parse(d); return undefined } catch { return t('prompts.invalidToolJson') }
    })
    setErrors(newErrors)
    if (newErrors.some(e => e)) return

    setSaving(true)
    try {
      const parsed = drafts.map(d => JSON.parse(d))
      await updateToolsApiPromptsPromptIdToolsPut({
        path: { prompt_id: promptId },
        body: { tools: parsed },
      })
      await queryClient.invalidateQueries({ queryKey: ['prompts', promptId] })
      setEditing(false)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      <div className="px-4 py-3 border-b border-border flex items-center justify-between">
        <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
          <Wrench className="h-4 w-4" />
          {!editing && tools.length > 0
            ? t('prompts.toolsCount', { count: tools.length })
            : t('prompts.tools')}
        </h3>
        {!editing ? (
          <Button variant="ghost" size="sm" onClick={startEditing}>
            <Pencil className="h-3 w-3 mr-1" />
            {t('common.edit')}
          </Button>
        ) : (
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="sm" onClick={cancelEditing} disabled={saving}>
              {t('common.cancel')}
            </Button>
            <Button size="sm" onClick={saveTools} disabled={saving || errors.some(e => e)}>
              {saving ? (
                <>{t('prompts.saving')}</>
              ) : (
                <><Check className="h-3 w-3 mr-1" />{t('common.save')}</>
              )}
            </Button>
          </div>
        )}
      </div>
      <div className="p-4">
        {editing ? (
          <div className="space-y-3">
            {drafts.map((json, i) => (
              <ToolEditRow
                key={i}
                json={json}
                onChange={(val) => updateDraft(i, val)}
                onRemove={() => removeDraft(i)}
                error={errors[i]}
              />
            ))}
            <Button variant="outline" size="sm" onClick={addDraft} className="w-full">
              <Plus className="h-4 w-4 mr-1" />
              {t('prompts.addTool')}
            </Button>
          </div>
        ) : tools.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {t('prompts.noTools')}
          </p>
        ) : (
          <div className="space-y-3">
            {tools.map((tool, i) => (
              <ToolCard key={i} tool={tool} index={i} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Section 4: Test Cases (inline preview)
// ---------------------------------------------------------------------------

interface TestCasePreview {
  tier: string
}

function TestCasesPreviewSection({ promptId }: { promptId: string }) {
  const { t } = useTranslation()

  const { data: casesResp } = useQuery({
    queryKey: ['test-cases', promptId],
    queryFn: () =>
      listCasesApiPromptsPromptIdDatasetGet({
        path: { prompt_id: promptId },
      }),
    enabled: !!promptId,
  })

  const cases = (casesResp?.data || []) as unknown as TestCasePreview[]

  const { total, critical, normal, low } = useMemo(() => {
    let crit = 0
    let norm = 0
    let lo = 0
    for (const tc of cases) {
      const tier = (tc.tier || 'normal').toLowerCase()
      if (tier === 'critical') crit++
      else if (tier === 'low') lo++
      else norm++
    }
    return { total: cases.length, critical: crit, normal: norm, low: lo }
  }, [cases])

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      <div className="px-4 py-3 border-b border-border">
        <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
          <FlaskConical className="h-4 w-4" />
          {t('prompts.testCases')}
        </h3>
      </div>
      <div className="p-4">
        {total === 0 ? (
          <p className="text-sm text-muted-foreground">
            {t('prompts.noTestCases')}
          </p>
        ) : (
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm text-foreground font-medium">
              {total === 1
                ? t('prompts.testCasesSummaryOne')
                : t('prompts.testCasesSummary', { count: total })}
            </span>
            <span className="text-sm text-muted-foreground">
              {t('prompts.tierBreakdown', { critical, normal, low })}
            </span>
          </div>
        )}
        <div className="mt-3">
          <Button variant="secondary" size="sm" asChild>
            <Link to="../dataset">{t('prompts.viewDatasetTab')}</Link>
          </Button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main Export
// ---------------------------------------------------------------------------

export default function PromptDetail({ promptId, onEditTemplate }: PromptDetailProps) {
  const { t } = useTranslation()
  const {
    data: prompt,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['prompts', promptId],
    queryFn: () =>
      getPromptApiPromptsPromptIdGet({
        path: { prompt_id: promptId },
      }),
  })

  if (isLoading) {
    return <PromptDetailSkeleton />
  }

  if (error) {
    return <p className="text-destructive">{t('prompts.failedToLoadPrompt')}</p>
  }

  const detail = prompt?.data
  if (!detail) {
    return <p className="text-muted-foreground">{t('prompts.promptNotFound')}</p>
  }

  const variableDefs = (detail.variable_definitions || []) as unknown as VariableDefinition[]
  const tools = (detail.tools || []) as unknown as Tool[]

  return (
    <div className="space-y-6">
      {/* Section 1: Template Preview */}
      <TemplatePreviewSection
        template={detail.template}
        onEdit={onEditTemplate}
      />

      {/* Section 2: Variables & Schema */}
      <VariablesSchemaSection promptId={promptId} variableDefs={variableDefs} />

      {/* Section 3: Tools */}
      <ToolsSection promptId={promptId} tools={tools} />

      {/* Section 4: Test Cases */}
      <TestCasesPreviewSection promptId={promptId} />
    </div>
  )
}
