import { useState, useEffect, useMemo, useCallback } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Zap, Target, Scale, Wrench, Save, Loader2, X, Settings2, Plus, Trash2, AlertTriangle, Play, ChevronDown } from 'lucide-react'
// Card components removed — using unified card pattern (rounded-lg border border-border bg-card)
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible'
import ModelRoleSelector from '@/components/evolution/ModelRoleSelector'
import { MockEditor } from '@/components/prompts/MockEditor'
import ThinkingBudgetControl from '@/components/evolution/ThinkingBudgetControl'
import { getApiBaseUrl } from '@/lib/api-config'

// --- Types ---

interface RoleConfigResponse {
  provider: string
  model: string
  temperature: number | null
  thinking_budget: number | null
}

interface ToolMockerConfigResponse {
  mode: string // "static" | "llm"
  provider: string | null
  model: string | null
}

interface PromptConfigResponse {
  meta: RoleConfigResponse
  target: RoleConfigResponse
  judge: RoleConfigResponse
  tool_mocker: ToolMockerConfigResponse
  overrides: Record<string, unknown>
}

// --- Presets ---

interface PresetRoleConfig {
  provider: string
  model: string
  temperature: number | null
  thinking_budget: number | null
}

interface Preset {
  label: string
  description: string
  meta: PresetRoleConfig
  target: PresetRoleConfig
  judge: PresetRoleConfig
}

const CONFIG_PRESETS: Record<string, Preset> = {
  gemini_standard: {
    label: 'Gemini Standard',
    description: 'Gemini 2.5 models for all roles',
    meta: { provider: 'gemini', model: 'gemini-2.5-pro', temperature: 0.9, thinking_budget: -1 },
    target: { provider: 'gemini', model: 'gemini-2.5-flash', temperature: 0, thinking_budget: null },
    judge: { provider: 'gemini', model: 'gemini-2.5-flash', temperature: 0, thinking_budget: null },
  },
  openrouter_quality: {
    label: 'OpenRouter Quality',
    description: 'Claude + GPT-4o via OpenRouter',
    meta: { provider: 'openrouter', model: 'anthropic/claude-sonnet-4', temperature: 0.9, thinking_budget: null },
    target: { provider: 'openrouter', model: 'openai/gpt-4o-mini', temperature: 0, thinking_budget: null },
    judge: { provider: 'openrouter', model: 'anthropic/claude-sonnet-4', temperature: 0, thinking_budget: null },
  },
  budget: {
    label: 'Budget',
    description: 'All Gemini Flash for cost efficiency',
    meta: { provider: 'gemini', model: 'gemini-2.5-flash', temperature: 0.9, thinking_budget: -1 },
    target: { provider: 'gemini', model: 'gemini-2.5-flash', temperature: 0, thinking_budget: null },
    judge: { provider: 'gemini', model: 'gemini-2.5-flash', temperature: 0, thinking_budget: null },
  },
}

// --- Role icon mapping (text comes from t()) ---

const ROLE_ICONS: Record<'meta' | 'target' | 'judge' | 'tool_mocker', React.ReactNode> = {
  meta: <Zap className="h-4 w-4 text-warning" />,
  target: <Target className="h-4 w-4 text-info" />,
  judge: <Scale className="h-4 w-4 text-mutation-fresh" />,
  tool_mocker: <Wrench className="h-4 w-4 text-success" />,
}

const ROLE_DEFAULT_FOR: Record<string, string> = {
  meta: 'persona',
  target: 'assistant',
}

// --- Form state ---

interface RoleFormState {
  provider: string | null
  model: string | null
  temperature: string
  thinking_budget: number | null
  thinking_level: string | null
  // Advanced inference params
  top_p: string
  top_k: string
  max_tokens: string
  frequency_penalty: string
  presence_penalty: string
}

type RoleName = 'meta' | 'target' | 'judge'

interface ToolMockerFormState {
  mode: string // "static" | "llm"
  provider: string | null
  model: string | null
  maxToolSteps: number
}

interface FormState {
  meta: RoleFormState
  target: RoleFormState
  judge: RoleFormState
  tool_mocker: ToolMockerFormState
}

function configToForm(config: PromptConfigResponse): FormState {
  function roleToForm(role: RoleConfigResponse, roleName: RoleName): RoleFormState {
    const ov = config.overrides
    return {
      provider: role.provider || null,
      model: role.model || null,
      temperature: role.temperature !== null ? String(role.temperature) : '',
      thinking_budget: role.thinking_budget,
      thinking_level: null,
      top_p: `${roleName}_top_p` in ov ? String(ov[`${roleName}_top_p`]) : '',
      top_k: `${roleName}_top_k` in ov ? String(ov[`${roleName}_top_k`]) : '',
      max_tokens: `${roleName}_max_tokens` in ov ? String(ov[`${roleName}_max_tokens`]) : '',
      frequency_penalty: `${roleName}_frequency_penalty` in ov ? String(ov[`${roleName}_frequency_penalty`]) : '',
      presence_penalty: `${roleName}_presence_penalty` in ov ? String(ov[`${roleName}_presence_penalty`]) : '',
    }
  }
  return {
    meta: roleToForm(config.meta, 'meta'),
    target: roleToForm(config.target, 'target'),
    judge: roleToForm(config.judge, 'judge'),
    tool_mocker: {
      mode: config.tool_mocker.mode || 'static',
      provider: config.tool_mocker.provider || null,
      model: config.tool_mocker.model || null,
      maxToolSteps: (config.overrides as Record<string, unknown>).max_tool_steps as number ?? 10,
    },
  }
}

// --- API helpers ---

const base = getApiBaseUrl()

async function fetchPromptConfig(promptId: string): Promise<PromptConfigResponse> {
  const res = await fetch(`${base}/api/prompts/${encodeURIComponent(promptId)}/config`)
  if (!res.ok) throw new Error(`Failed to load config: ${res.status}`)
  return res.json()
}

async function savePromptConfig(
  promptId: string,
  payload: Record<string, unknown>,
): Promise<PromptConfigResponse> {
  const res = await fetch(`${base}/api/prompts/${encodeURIComponent(promptId)}/config`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`Save failed (${res.status}): ${text}`)
  }
  return res.json()
}

// --- Format Guide types & API helpers ---

interface FormatGuideData {
  id: number
  prompt_id: string
  tool_name: string
  examples: string[]
}

interface GenerateSampleResult {
  sample: string
  scenario_type: string
}

async function fetchFormatGuides(promptId: string): Promise<FormatGuideData[]> {
  const res = await fetch(`${base}/api/prompts/${encodeURIComponent(promptId)}/format-guides`)
  if (!res.ok) throw new Error(`Failed to load format guides: ${res.status}`)
  return res.json()
}

async function saveFormatGuide(
  promptId: string,
  toolName: string,
  examples: string[],
): Promise<FormatGuideData> {
  const res = await fetch(
    `${base}/api/prompts/${encodeURIComponent(promptId)}/format-guides/${encodeURIComponent(toolName)}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(examples),
    },
  )
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`Save failed (${res.status}): ${text}`)
  }
  return res.json()
}

async function deleteFormatGuide(promptId: string, toolName: string): Promise<void> {
  const res = await fetch(
    `${base}/api/prompts/${encodeURIComponent(promptId)}/format-guides/${encodeURIComponent(toolName)}`,
    { method: 'DELETE' },
  )
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`Delete failed (${res.status}): ${text}`)
  }
}

async function generateSample(
  promptId: string,
  toolName: string,
  scenarioType: string,
): Promise<GenerateSampleResult> {
  const res = await fetch(
    `${base}/api/prompts/${encodeURIComponent(promptId)}/format-guides/generate-sample`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tool_name: toolName, scenario_type: scenarioType }),
    },
  )
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`Generate sample failed (${res.status}): ${text}`)
  }
  return res.json()
}

async function fetchPromptDetail(promptId: string): Promise<{ tools?: { function: { name: string } }[] | null; tool_schemas?: { name: string }[] | null }> {
  const res = await fetch(`${base}/api/prompts/${encodeURIComponent(promptId)}`)
  if (!res.ok) return { tools: null, tool_schemas: null }
  return res.json()
}

/** Extract tool names from a prompt's tools or tool_schemas fields. */
function extractToolNames(detail: { tools?: { function: { name: string } }[] | null; tool_schemas?: { name: string }[] | null }): string[] {
  const names: string[] = []
  if (detail.tool_schemas) {
    for (const schema of detail.tool_schemas) {
      if (schema.name) names.push(schema.name)
    }
  } else if (detail.tools) {
    for (const tool of detail.tools) {
      if (tool.function?.name) names.push(tool.function.name)
    }
  }
  return names
}

/** Check if a string is valid JSON. */
function isValidJson(str: string): boolean {
  if (!str.trim()) return false
  try {
    JSON.parse(str)
    return true
  } catch {
    return false
  }
}

// --- Provenance Badge ---

function ProvenanceBadge({ fieldKey, overrides }: { fieldKey: string; overrides: Record<string, unknown> }) {
  const { t } = useTranslation()
  const isOverride = fieldKey in overrides
  return (
    <Badge variant={isOverride ? 'default' : 'secondary'} className="text-[10px] px-1.5 py-0">
      {isOverride ? t('config.override') : t('config.global')}
    </Badge>
  )
}

// --- Component ---

export default function PromptConfigPage() {
  const { promptId } = useParams<{ promptId: string }>()
  const queryClient = useQueryClient()
  const { t } = useTranslation()

  // Fetch config
  const { data: config, isLoading, error } = useQuery({
    queryKey: ['prompt-config', promptId],
    queryFn: () => fetchPromptConfig(promptId!),
    enabled: !!promptId,
  })

  // Fetch prompt detail for tool names (used by format guide UI)
  const { data: promptDetail } = useQuery({
    queryKey: ['prompt-detail-tools', promptId],
    queryFn: () => fetchPromptDetail(promptId!),
    enabled: !!promptId,
  })

  const toolNames = useMemo(() => {
    if (!promptDetail) return []
    return extractToolNames(promptDetail)
  }, [promptDetail])

  // Local form state
  const [form, setForm] = useState<FormState | null>(null)
  const [serverForm, setServerForm] = useState<FormState | null>(null)

  // Status banner
  const [statusBanner, setStatusBanner] = useState<{ type: 'success' | 'error'; message: string } | null>(null)

  // Initialize form from fetched config
  useEffect(() => {
    if (config) {
      const f = configToForm(config)
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setForm(f)
      setServerForm(f)
    }
  }, [config])

  // Derive isDirty
  const isDirty = useMemo(() => {
    if (!form || !serverForm) return false
    return JSON.stringify(form) !== JSON.stringify(serverForm)
  }, [form, serverForm])

  // Save mutation
  const saveMutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) => savePromptConfig(promptId!, payload),
    onSuccess: (data) => {
      const f = configToForm(data)
      setForm(f)
      setServerForm(f)
      queryClient.invalidateQueries({ queryKey: ['prompt-config', promptId] })
      setStatusBanner({ type: 'success', message: t('config.configSavedSuccess') })
      setTimeout(() => setStatusBanner(null), 4000)
    },
    onError: (err: Error) => {
      setStatusBanner({ type: 'error', message: err.message })
      setTimeout(() => setStatusBanner(null), 6000)
    },
  })

  // Build PUT payload from form state
  function handleSave() {
    if (!form) return

    const payload: Record<string, unknown> = {}

    for (const role of ['meta', 'target', 'judge'] as const) {
      const roleForm = form[role]
      if (roleForm.provider) payload[`${role}_provider`] = roleForm.provider
      if (roleForm.model) payload[`${role}_model`] = roleForm.model
      if (roleForm.temperature !== '') {
        payload[`${role}_temperature`] = parseFloat(roleForm.temperature)
      }
      if (roleForm.thinking_budget !== null) {
        payload[`${role}_thinking_budget`] = roleForm.thinking_budget
      }
      // Advanced inference params
      if (roleForm.top_p !== '') payload[`${role}_top_p`] = parseFloat(roleForm.top_p)
      if (roleForm.top_k !== '') payload[`${role}_top_k`] = parseInt(roleForm.top_k)
      if (roleForm.max_tokens !== '') payload[`${role}_max_tokens`] = parseInt(roleForm.max_tokens)
      if (roleForm.frequency_penalty !== '') payload[`${role}_frequency_penalty`] = parseFloat(roleForm.frequency_penalty)
      if (roleForm.presence_penalty !== '') payload[`${role}_presence_penalty`] = parseFloat(roleForm.presence_penalty)
    }

    // Tool Mocker fields
    payload['tool_mocker_mode'] = form.tool_mocker.mode
    payload['max_tool_steps'] = form.tool_mocker.maxToolSteps
    if (form.tool_mocker.mode === 'llm') {
      if (form.tool_mocker.provider) payload['tool_mocker_provider'] = form.tool_mocker.provider
      if (form.tool_mocker.model) payload['tool_mocker_model'] = form.tool_mocker.model
    }

    saveMutation.mutate(payload)
  }

  // Apply preset (presets only affect meta/target/judge, not tool_mocker)
  function applyPreset(presetKey: string) {
    const preset = CONFIG_PRESETS[presetKey]
    if (!preset) return

    const payload: Record<string, unknown> = {}
    for (const role of ['meta', 'target', 'judge'] as const) {
      const presetRole = preset[role]
      payload[`${role}_provider`] = presetRole.provider
      payload[`${role}_model`] = presetRole.model
      if (presetRole.temperature !== null) {
        payload[`${role}_temperature`] = presetRole.temperature
      }
      if (presetRole.thinking_budget !== null) {
        payload[`${role}_thinking_budget`] = presetRole.thinking_budget
      }
    }

    // Preserve existing tool_mocker state when applying presets
    if (form) {
      payload['tool_mocker_mode'] = form.tool_mocker.mode
      payload['max_tool_steps'] = form.tool_mocker.maxToolSteps
      if (form.tool_mocker.mode === 'llm') {
        if (form.tool_mocker.provider) payload['tool_mocker_provider'] = form.tool_mocker.provider
        if (form.tool_mocker.model) payload['tool_mocker_model'] = form.tool_mocker.model
      }
    }

    saveMutation.mutate(payload)
  }

  // Reset a single field to global (set to null in overrides)
  function resetField(role: 'meta' | 'target' | 'judge', field: string) {
    if (!form || !config) return

    // Build payload from current overrides, removing the specified field
    const currentOverrides = { ...config.overrides }
    const fieldKey = `${role}_${field}`
    delete currentOverrides[fieldKey]

    // Rebuild payload from remaining overrides only
    const payload: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(currentOverrides)) {
      payload[key] = value
    }

    saveMutation.mutate(payload)
  }

  // Update a standard role's form field
  function updateRole(role: 'meta' | 'target' | 'judge', field: keyof RoleFormState, value: unknown) {
    setForm((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        [role]: { ...prev[role], [field]: value },
      }
    })
  }

  // Update tool_mocker form field
  function updateToolMocker(field: keyof ToolMockerFormState, value: unknown) {
    setForm((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        tool_mocker: { ...prev.tool_mocker, [field]: value },
      }
    })
  }

  // Loading state
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (error || !config || !form) {
    return (
      <div className="py-10 text-center">
        <p className="text-destructive">{t('config.failedToLoad')}</p>
        <p className="text-muted-foreground text-sm mt-2">{(error as Error)?.message}</p>
      </div>
    )
  }

  return (
    <div className="space-y-6 pb-10">
      {/* Preset buttons */}
      <div className="rounded-lg border border-border bg-card overflow-hidden">
        <div className="px-4 py-3 border-b border-border">
          <h3 className="text-sm font-semibold text-foreground">{t('config.quickPresets')}</h3>
        </div>
        <div className="p-4">
          <div className="flex flex-wrap gap-2">
            {Object.entries(CONFIG_PRESETS).map(([key, preset]) => (
              <Button
                key={key}
                variant="outline"
                size="sm"
                onClick={() => applyPreset(key)}
                disabled={saveMutation.isPending}
              >
                {preset.label}
              </Button>
            ))}
          </div>
        </div>
      </div>

      {/* 2x2 role card grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {(['meta', 'target', 'judge'] as const).map((role) => (
          <RoleCard
            key={role}
            role={role}
            form={form[role]}
            overrides={config.overrides}
            onUpdate={(field, value) => updateRole(role, field, value)}
            onReset={(field) => resetField(role, field)}
            isPending={saveMutation.isPending}
          />
        ))}
        <ToolMockerCard
          form={form.tool_mocker}
          overrides={config.overrides}
          onUpdate={updateToolMocker}
          isPending={saveMutation.isPending}
          promptId={promptId!}
          toolNames={toolNames}
        />
      </div>

      {/* Save button + Status Banner */}
      <div className="rounded-lg border border-border bg-card overflow-hidden">
        <div className="px-4 py-3 flex items-center gap-3">
          <Button onClick={handleSave} disabled={!isDirty || saveMutation.isPending}>
            {saveMutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin mr-2" />
            ) : (
              <Save className="h-4 w-4 mr-2" />
            )}
            {t('config.saveConfig')}
          </Button>
          {isDirty && (
            <span className="text-xs text-muted-foreground">{t('config.unsavedChanges')}</span>
          )}
        </div>
        {statusBanner && (
          <div
            className={`px-4 py-3 text-sm border-t ${
              statusBanner.type === 'success'
                ? 'bg-success/10 text-success border-success/20'
                : 'bg-destructive/10 text-destructive border-destructive/20'
            }`}
          >
            {statusBanner.message}
          </div>
        )}
      </div>
    </div>
  )
}

// --- Advanced Inference Dialog sub-component ---

const ADVANCED_FIELDS = [
  { key: 'top_p' as const, labelKey: 'config.topP', min: 0, max: 1, step: 0.05, placeholderKey: 'config.notSet' },
  { key: 'top_k' as const, labelKey: 'config.topK', min: 1, max: undefined, step: 1, placeholderKey: 'config.notSet' },
  { key: 'max_tokens' as const, labelKey: 'config.maxTokens', min: 1, max: undefined, step: 1, placeholderKey: 'config.default' },
  { key: 'frequency_penalty' as const, labelKey: 'config.frequencyPenalty', min: -2, max: 2, step: 0.1, placeholderKey: 'config.notSet' },
  { key: 'presence_penalty' as const, labelKey: 'config.presencePenalty', min: -2, max: 2, step: 0.1, placeholderKey: 'config.notSet' },
] as const

function AdvancedInferenceSection({
  role: _role,
  form,
  onUpdate,
}: {
  role: RoleName
  form: RoleFormState
  onUpdate: (field: keyof RoleFormState, value: unknown) => void
}) {
  const { t } = useTranslation()

  return (
    <Collapsible defaultOpen={false}>
      <CollapsibleTrigger asChild>
        <button
          type="button"
          className="group flex w-full items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors py-1"
        >
          <ChevronDown className="h-3.5 w-3.5 transition-transform duration-200 group-data-[state=closed]:-rotate-90" />
          <Settings2 className="h-3.5 w-3.5" />
          {t('config.advanced')}
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="space-y-3 pt-2 pl-5">
          {ADVANCED_FIELDS.map((field) => (
            <div key={field.key}>
              <div className="flex items-center justify-between mb-1">
                <label className="text-xs font-medium text-foreground">{t(field.labelKey)}</label>
                {form[field.key] !== '' && (
                  <button
                    type="button"
                    onClick={() => onUpdate(field.key, '')}
                    className="text-muted-foreground hover:text-foreground p-0.5 rounded"
                    title={t('config.resetToDefault')}
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
              <Input
                type="number"
                min={field.min}
                max={field.max}
                step={field.step}
                placeholder={t(field.placeholderKey)}
                value={form[field.key]}
                onChange={(e) => onUpdate(field.key, e.target.value)}
                className="h-8 text-xs"
              />
            </div>
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  )
}

// --- Role Card sub-component ---

function RoleCard({
  role,
  form,
  overrides,
  onUpdate,
  onReset,
  isPending,
}: {
  role: 'meta' | 'target' | 'judge'
  form: RoleFormState
  overrides: Record<string, unknown>
  onUpdate: (field: keyof RoleFormState, value: unknown) => void
  onReset: (field: string) => void
  isPending: boolean
}) {
  const { t } = useTranslation()
  const icon = ROLE_ICONS[role]
  const defaultForKey = ROLE_DEFAULT_FOR[role]

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      <div className="px-4 py-3 border-b border-border">
        <div className="flex items-center gap-2">
          {icon}
          <div className="flex-1">
            <h3 className="text-sm font-semibold text-foreground">{t(`config.${role}`)}</h3>
            <p className="text-xs text-muted-foreground">{t(`config.${role}Subtitle`)}</p>
            {defaultForKey && (
              <Badge variant="outline" className="mt-1 text-[10px] text-muted-foreground">
                {t('config.defaultFor', { role: t(`config.${defaultForKey}`) })}
              </Badge>
            )}
          </div>
        </div>
      </div>
      <div className="p-4 space-y-4">
        {/* Provider + Model */}
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-medium text-muted-foreground">{t('config.providerModel')}</span>
            <ProvenanceBadge fieldKey={`${role}_provider`} overrides={overrides} />
            {(`${role}_provider` in overrides) && (
              <button
                type="button"
                onClick={() => {
                  onReset('provider')
                  onReset('model')
                }}
                className="text-muted-foreground hover:text-foreground"
                title={t('config.resetToGlobal')}
                disabled={isPending}
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </div>
          <ModelRoleSelector
            role={role}
            provider={form.provider}
            model={form.model}
            onProviderChange={(provider) => {
              onUpdate('provider', provider)
              onUpdate('model', null)
            }}
            onModelChange={(model) => onUpdate('model', model)}
          />
        </div>

        {/* Temperature */}
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-medium text-muted-foreground">{t('config.temperature')}</span>
            <ProvenanceBadge fieldKey={`${role}_temperature`} overrides={overrides} />
            {(`${role}_temperature` in overrides) && (
              <button
                type="button"
                onClick={() => onReset('temperature')}
                className="text-muted-foreground hover:text-foreground"
                title={t('config.resetToGlobal')}
                disabled={isPending}
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </div>
          <Input
            type="number"
            min={0}
            max={2}
            step={0.1}
            placeholder={t('config.inheritedFromGlobal')}
            value={form.temperature}
            onChange={(e) => onUpdate('temperature', e.target.value)}
            className="h-8 text-xs"
          />
        </div>

        {/* Thinking Budget */}
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-medium text-muted-foreground">{t('config.thinking')}</span>
            <ProvenanceBadge fieldKey={`${role}_thinking_budget`} overrides={overrides} />
            {(`${role}_thinking_budget` in overrides) && (
              <button
                type="button"
                onClick={() => onReset('thinking_budget')}
                className="text-muted-foreground hover:text-foreground"
                title={t('config.resetToGlobal')}
                disabled={isPending}
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </div>
          <ThinkingBudgetControl
            provider={form.provider}
            modelId={form.model}
            thinkingBudget={form.thinking_budget}
            thinkingLevel={form.thinking_level}
            onBudgetChange={(v) => onUpdate('thinking_budget', v)}
            onLevelChange={(v) => onUpdate('thinking_level', v)}
          />
        </div>

        {/* Advanced inference params */}
        <AdvancedInferenceSection
          role={role}
          form={form}
          onUpdate={onUpdate}
        />
      </div>
    </div>
  )
}

// --- Tool Mocker Card sub-component ---

function ToolMockerCard({
  form,
  overrides,
  onUpdate,
  isPending,
  promptId,
  toolNames,
}: {
  form: ToolMockerFormState
  overrides: Record<string, unknown>
  onUpdate: (field: keyof ToolMockerFormState, value: unknown) => void
  isPending: boolean
  promptId: string
  toolNames: string[]
}) {
  const { t } = useTranslation()
  const isLlmMode = form.mode === 'llm'
  const queryClient = useQueryClient()

  // Fetch saved format guides when in LLM mode
  const { data: savedGuides } = useQuery({
    queryKey: ['format-guides', promptId],
    queryFn: () => fetchFormatGuides(promptId),
    enabled: isLlmMode && !!promptId,
  })

  // Build lookup: tool_name -> saved examples
  const savedGuidesMap = useMemo(() => {
    const map: Record<string, string[]> = {}
    if (savedGuides) {
      for (const guide of savedGuides) {
        map[guide.tool_name] = guide.examples
      }
    }
    return map
  }, [savedGuides])

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      <div className="px-4 py-3 border-b border-border">
        <div className="flex items-center gap-2">
          {ROLE_ICONS.tool_mocker}
          <div className="flex-1">
            <h3 className="text-sm font-semibold text-foreground">{t('config.toolMocker')}</h3>
            <p className="text-xs text-muted-foreground">{t('config.toolMockerSubtitle')}</p>
          </div>
        </div>
      </div>
      <div className="p-4 space-y-4">
        {/* Static / LLM Mode Toggle */}
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-medium text-muted-foreground">{t('config.mode')}</span>
            {('tool_mocker_mode' in overrides) && (
              <ProvenanceBadge fieldKey="tool_mocker_mode" overrides={overrides} />
            )}
          </div>
          <div className="flex items-center gap-3">
            <span className={`text-sm ${!isLlmMode ? 'font-medium text-foreground' : 'text-muted-foreground'}`}>
              {t('config.static')}
            </span>
            <Switch
              checked={isLlmMode}
              onCheckedChange={(checked) => {
                onUpdate('mode', checked ? 'llm' : 'static')
                if (!checked) {
                  // Clear provider/model when switching to static
                  onUpdate('provider', null)
                  onUpdate('model', null)
                }
              }}
              disabled={isPending}
            />
            <span className={`text-sm ${isLlmMode ? 'font-medium text-foreground' : 'text-muted-foreground'}`}>
              {t('config.llm')}
            </span>
          </div>
        </div>

        {/* Max tool steps */}
        {toolNames.length > 0 && (
          <div className="flex items-center gap-3">
            <span className="text-xs font-medium text-muted-foreground">{t('config.maxToolSteps')}</span>
            <Input
              type="number"
              min={1}
              max={50}
              value={form.maxToolSteps}
              onChange={(e) => onUpdate('maxToolSteps', Number(e.target.value))}
              className="w-20 h-8 text-xs"
              disabled={isPending}
            />
          </div>
        )}

        {/* Conditional: LLM mode shows model selector, Static mode shows info text */}
        {isLlmMode ? (
          <>
            <div>
              <div className="flex items-center gap-2 mb-1">
                <span className="text-xs font-medium text-muted-foreground">{t('config.providerModel')}</span>
                {('tool_mocker_provider' in overrides) && (
                  <ProvenanceBadge fieldKey="tool_mocker_provider" overrides={overrides} />
                )}
              </div>
              <ModelRoleSelector
                role="tool_mocker"
                provider={form.provider}
                model={form.model}
                onProviderChange={(provider) => {
                  onUpdate('provider', provider)
                  onUpdate('model', null)
                }}
                onModelChange={(model) => onUpdate('model', model)}
              />
            </div>

            {/* Format Guides Section */}
            <div className="border-t pt-4">
              <h4 className="text-sm font-medium text-foreground mb-3">{t('config.formatGuides')}</h4>
              {toolNames.length === 0 ? (
                <p className="text-xs text-muted-foreground italic py-2">
                  {t('config.noToolsDefined')}
                </p>
              ) : (
                <div className="space-y-4">
                  {toolNames.map((toolName) => (
                    <FormatGuideToolSection
                      key={toolName}
                      promptId={promptId}
                      toolName={toolName}
                      savedExamples={savedGuidesMap[toolName] || []}
                      onSaved={() => queryClient.invalidateQueries({ queryKey: ['format-guides', promptId] })}
                    />
                  ))}
                </div>
              )}
            </div>
          </>
        ) : (
          <div className="border-t pt-4">
            <h4 className="text-sm font-medium text-foreground mb-3">
              {t('config.staticMocks')}
            </h4>
            <MockEditor promptId={promptId} toolNames={toolNames} />
          </div>
        )}
      </div>
    </div>
  )
}

// --- Format Guide per-tool section ---

function FormatGuideToolSection({
  promptId,
  toolName,
  savedExamples,
  onSaved,
}: {
  promptId: string
  toolName: string
  savedExamples: string[]
  onSaved: () => void
}) {
  const { t } = useTranslation()
  const hasSavedExamples = savedExamples.length > 0

  // Local editing state: list of example textareas
  const [examples, setExamples] = useState<string[]>(() =>
    hasSavedExamples ? [...savedExamples] : [''],
  )
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saveSuccess, setSaveSuccess] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)

  // Sample generation state
  const [scenarioType, setScenarioType] = useState<string>('success')
  const [sampleResult, setSampleResult] = useState<string | null>(null)
  const [sampleError, setSampleError] = useState<string | null>(null)
  const [sampleLoading, setSampleLoading] = useState(false)

  // Sync from saved when savedExamples changes (e.g., after save/reload)
  useEffect(() => {
    if (savedExamples.length > 0) {
      setExamples([...savedExamples])
    }
  }, [savedExamples])

  const updateExample = useCallback((index: number, value: string) => {
    setExamples((prev) => {
      const next = [...prev]
      next[index] = value
      return next
    })
    setSaveSuccess(false)
    setSaveError(null)
  }, [])

  const addExample = useCallback(() => {
    setExamples((prev) => [...prev, ''])
    setSaveSuccess(false)
  }, [])

  const removeExample = useCallback((index: number) => {
    setExamples((prev) => {
      const next = [...prev]
      next.splice(index, 1)
      return next.length === 0 ? [''] : next
    })
    setSaveSuccess(false)
  }, [])

  // Determine if all examples are non-empty and valid JSON
  const nonEmptyExamples = examples.filter((ex) => ex.trim() !== '')
  const allValid = nonEmptyExamples.length > 0 && nonEmptyExamples.every(isValidJson)
  const canSave = nonEmptyExamples.length > 0 && allValid

  async function handleSave() {
    if (!canSave) return
    setIsSaving(true)
    setSaveError(null)
    setSaveSuccess(false)
    try {
      await saveFormatGuide(promptId, toolName, nonEmptyExamples)
      setSaveSuccess(true)
      onSaved()
      setTimeout(() => setSaveSuccess(false), 3000)
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setIsSaving(false)
    }
  }

  async function handleDelete() {
    setIsDeleting(true)
    setSaveError(null)
    try {
      await deleteFormatGuide(promptId, toolName)
      setExamples([''])
      setSampleResult(null)
      onSaved()
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : 'Delete failed')
    } finally {
      setIsDeleting(false)
    }
  }

  async function handleGenerateSample() {
    setSampleLoading(true)
    setSampleError(null)
    setSampleResult(null)
    try {
      const result = await generateSample(promptId, toolName, scenarioType)
      setSampleResult(result.sample)
    } catch (err) {
      setSampleError(err instanceof Error ? err.message : 'Generation failed')
    } finally {
      setSampleLoading(false)
    }
  }

  return (
    <div className="rounded-md border border-border p-3 space-y-3">
      {/* Tool name header with warning indicator */}
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium text-foreground font-mono">{toolName}</span>
        {!hasSavedExamples && (
          <span className="flex items-center gap-1 text-xs text-warning">
            <AlertTriangle className="h-3 w-3" />
            {t('config.noExamples')}
          </span>
        )}
        {hasSavedExamples && (
          <Badge variant="secondary" className="text-[10px]">
            {t('config.savedCount', { count: savedExamples.length })}
          </Badge>
        )}
      </div>

      {/* Example textareas */}
      <div className="space-y-2">
        {examples.map((example, index) => {
          const trimmed = example.trim()
          const hasContent = trimmed !== ''
          const valid = hasContent ? isValidJson(trimmed) : true // empty is neutral
          return (
            <div key={index} className="flex gap-2">
              <Textarea
                value={example}
                onChange={(e) => updateExample(index, e.target.value)}
                placeholder='{"status": "success", "data": {...}}'
                rows={3}
                className={`font-mono text-xs flex-1 ${
                  hasContent && !valid
                    ? 'border-destructive focus-visible:ring-destructive'
                    : ''
                }`}
              />
              {examples.length > 1 && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-8 w-8 p-0 text-muted-foreground hover:text-destructive"
                  onClick={() => removeExample(index)}
                  title={t('config.removeExample')}
                >
                  <X className="h-3.5 w-3.5" />
                </Button>
              )}
            </div>
          )
        })}
        {examples.some((ex) => ex.trim() !== '' && !isValidJson(ex.trim())) && (
          <p className="text-xs text-destructive">{t('config.invalidJson')}</p>
        )}
      </div>

      {/* Action buttons */}
      <div className="flex items-center gap-2 flex-wrap">
        <Button
          variant="outline"
          size="sm"
          className="h-7 text-xs gap-1"
          onClick={addExample}
        >
          <Plus className="h-3 w-3" />
          {t('config.addExample')}
        </Button>
        <Button
          size="sm"
          className="h-7 text-xs gap-1"
          onClick={handleSave}
          disabled={!canSave || isSaving}
        >
          {isSaving ? <Loader2 className="h-3 w-3 animate-spin" /> : <Save className="h-3 w-3" />}
          {t('common.save')}
        </Button>
        {hasSavedExamples && (
          <Button
            variant="ghost"
            size="sm"
            className="h-7 text-xs gap-1 text-destructive hover:text-destructive"
            onClick={handleDelete}
            disabled={isDeleting}
          >
            {isDeleting ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}
            {t('common.delete')}
          </Button>
        )}
        {saveSuccess && (
          <span className="text-xs text-success">{t('config.saved')}</span>
        )}
        {saveError && (
          <span className="text-xs text-destructive">{saveError}</span>
        )}
      </div>

      {/* Generate Sample section */}
      <div className="border-t border-border/50 pt-3 space-y-2">
        <div className="flex items-center gap-2 flex-wrap">
          <Select value={scenarioType} onValueChange={setScenarioType}>
            <SelectTrigger className="h-7 w-[140px] text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="success">{t('config.success')}</SelectItem>
              <SelectItem value="failure">{t('config.failure')}</SelectItem>
              <SelectItem value="edge_case">{t('config.edgeCase')}</SelectItem>
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            size="sm"
            className="h-7 text-xs gap-1"
            onClick={handleGenerateSample}
            disabled={!hasSavedExamples || sampleLoading}
            title={!hasSavedExamples ? 'Save at least 1 example first' : 'Generate a sample mock response'}
          >
            {sampleLoading ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Play className="h-3 w-3" />
            )}
            {t('config.generateSample')}
          </Button>
        </div>
        {sampleResult && (
          <pre className="rounded-md bg-muted p-2 text-xs font-mono overflow-x-auto whitespace-pre-wrap max-h-40">
            {sampleResult}
          </pre>
        )}
        {sampleError && (
          <p className="text-xs text-destructive">{sampleError}</p>
        )}
      </div>
    </div>
  )
}
