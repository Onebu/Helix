import { useState, useEffect, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import {
  Eye,
  EyeOff,
  CheckCircle2,
  XCircle,
  Loader2,
  RotateCcw,
  Save,
  Zap,
  Target,
  Scale,
} from 'lucide-react'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Separator } from '@/components/ui/separator'
import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { getApiBaseUrl } from '@/lib/api-config'

// --- Types ---

interface RoleConfig {
  provider: string
  model: string
  has_key: boolean
  key_hint: string
  thinking_budget: number | null
}

interface SettingsResponse {
  meta: RoleConfig
  target: RoleConfig
  judge: RoleConfig
  concurrency_limit: number
  generation: Record<string, unknown>
  providers: string[]
}

interface ModelInfo {
  id: string
  name: string
  context_length: number | null
}

interface TestConnectionResponse {
  success: boolean
  error: string | null
}

type RoleName = 'meta' | 'target' | 'judge'

// Map provider name to the API key field name in SettingsUpdateRequest
const PROVIDER_KEY_FIELDS: Record<string, string> = {
  gemini: 'gemini_api_key',
  openai: 'openai_api_key',
  openrouter: 'openrouter_api_key',
}

// Display names for providers (proper capitalization)
const PROVIDER_DISPLAY_NAMES: Record<string, string> = {
  gemini: 'Gemini',
  openai: 'OpenAI',
  openrouter: 'OpenRouter',
}

// Role icon mapping (only icons -- titles/descriptions come from t())
const ROLE_ICONS: Record<RoleName, React.ReactNode> = {
  meta: <Zap className="h-5 w-5 text-warning" />,
  target: <Target className="h-5 w-5 text-info" />,
  judge: <Scale className="h-5 w-5 text-mutation-fresh" />,
}

// --- API helpers ---

const base = getApiBaseUrl()

async function fetchSettings(): Promise<SettingsResponse> {
  const res = await fetch(`${base}/api/settings/`)
  if (!res.ok) throw new Error(`Failed to load settings: ${res.status}`)
  return res.json()
}

async function fetchDefaults(): Promise<SettingsResponse> {
  const res = await fetch(`${base}/api/settings/defaults`)
  if (!res.ok) throw new Error(`Failed to load defaults: ${res.status}`)
  return res.json()
}

async function saveSettings(payload: Record<string, unknown>): Promise<SettingsResponse> {
  const res = await fetch(`${base}/api/settings/`, {
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

async function testConnection(provider: string, apiKey: string): Promise<TestConnectionResponse> {
  const res = await fetch(`${base}/api/settings/test-connection`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider, api_key: apiKey }),
  })
  if (!res.ok) throw new Error(`Test connection failed: ${res.status}`)
  return res.json()
}

async function fetchModels(provider: string): Promise<ModelInfo[]> {
  const res = await fetch(`${base}/api/models?provider=${encodeURIComponent(provider)}`)
  if (res.status === 503) return [] // No API key configured
  if (!res.ok) throw new Error(`Failed to load models: ${res.status}`)
  return res.json()
}

// --- Form state shape ---

interface FormState {
  meta_provider: string
  meta_model: string
  meta_thinking_budget: string
  target_provider: string
  target_model: string
  target_thinking_budget: string
  judge_provider: string
  judge_model: string
  judge_thinking_budget: string
  concurrency_limit: string
  generation_temperature: string
  generation_max_tokens: string
}

function settingsToForm(s: SettingsResponse): FormState {
  return {
    meta_provider: s.meta.provider,
    meta_model: s.meta.model,
    meta_thinking_budget: s.meta.thinking_budget?.toString() ?? '',
    target_provider: s.target.provider,
    target_model: s.target.model,
    target_thinking_budget: s.target.thinking_budget?.toString() ?? '',
    judge_provider: s.judge.provider,
    judge_model: s.judge.model,
    judge_thinking_budget: s.judge.thinking_budget?.toString() ?? '',
    concurrency_limit: s.concurrency_limit.toString(),
    generation_temperature: ((s.generation?.temperature as number) ?? 0).toString(),
    generation_max_tokens: ((s.generation?.max_tokens as number) ?? 1024).toString(),
  }
}

// --- Component ---

export default function SettingsPage() {
  const queryClient = useQueryClient()
  const { t } = useTranslation()

  // Fetch current settings
  const { data: settings, isLoading, error } = useQuery({
    queryKey: ['settings'],
    queryFn: fetchSettings,
  })

  // Fetch defaults (for reset)
  const { data: defaults } = useQuery({
    queryKey: ['settings-defaults'],
    queryFn: fetchDefaults,
  })

  // Local form state
  const [form, setForm] = useState<FormState | null>(null)
  const [serverForm, setServerForm] = useState<FormState | null>(null)

  // API key inputs (separate from main form -- only sent when user types a new value)
  const [apiKeys, setApiKeys] = useState<Record<string, string>>({
    gemini: '',
    openai: '',
    openrouter: '',
  })

  // Key visibility toggles
  const [keyVisible, setKeyVisible] = useState<Record<string, boolean>>({
    gemini: false,
    openai: false,
    openrouter: false,
  })

  // Test connection state per provider
  const [testStatus, setTestStatus] = useState<Record<string, { testing: boolean; result?: TestConnectionResponse }>>({})

  // Status banner
  const [statusBanner, setStatusBanner] = useState<{ type: 'success' | 'error'; message: string } | null>(null)

  // Reset confirmation dialog
  const [showResetDialog, setShowResetDialog] = useState(false)

  // Initialize form from fetched settings
  useEffect(() => {
    if (settings && !form) {
      const f = settingsToForm(settings)
      setForm(f)
      setServerForm(f)
    }
  }, [settings, form])

  // Derive isDirty
  const isDirty = useMemo(() => {
    if (!form || !serverForm) return false
    const formDirty = JSON.stringify(form) !== JSON.stringify(serverForm)
    const keysDirty = Object.values(apiKeys).some((v) => v.length > 0)
    return formDirty || keysDirty
  }, [form, serverForm, apiKeys])

  // Save mutation
  const saveMutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) => saveSettings(payload),
    onSuccess: (data) => {
      const f = settingsToForm(data)
      setForm(f)
      setServerForm(f)
      setApiKeys({ gemini: '', openai: '', openrouter: '' })
      queryClient.invalidateQueries({ queryKey: ['settings'] })
      setStatusBanner({ type: 'success', message: t('settings.settingsSaved') })
      setTimeout(() => setStatusBanner(null), 4000)
    },
    onError: (err: Error) => {
      setStatusBanner({ type: 'error', message: err.message })
      setTimeout(() => setStatusBanner(null), 6000)
    },
  })

  // Build PUT payload with only changed fields
  function handleSave() {
    if (!form || !serverForm) return

    const payload: Record<string, unknown> = {}

    // Role fields
    for (const role of ['meta', 'target', 'judge'] as const) {
      const providerKey = `${role}_provider` as keyof FormState
      const modelKey = `${role}_model` as keyof FormState
      const budgetKey = `${role}_thinking_budget` as keyof FormState

      if (form[providerKey] !== serverForm[providerKey]) {
        payload[providerKey] = form[providerKey]
      }
      if (form[modelKey] !== serverForm[modelKey]) {
        payload[modelKey] = form[modelKey]
      }
      if (form[budgetKey] !== serverForm[budgetKey]) {
        const val = form[budgetKey]
        payload[budgetKey] = val === '' ? null : parseInt(val, 10)
      }
    }

    // API keys (only if user typed something)
    for (const [provider, key] of Object.entries(apiKeys)) {
      if (key.length > 0) {
        const field = PROVIDER_KEY_FIELDS[provider]
        if (field) payload[field] = key
      }
    }

    // Global settings
    if (form.concurrency_limit !== serverForm.concurrency_limit) {
      payload.concurrency_limit = parseInt(form.concurrency_limit, 10)
    }

    // Generation settings
    const genChanges: Record<string, unknown> = {}
    if (form.generation_temperature !== serverForm.generation_temperature) {
      genChanges.temperature = parseFloat(form.generation_temperature)
    }
    if (form.generation_max_tokens !== serverForm.generation_max_tokens) {
      genChanges.max_tokens = parseInt(form.generation_max_tokens, 10)
    }
    if (Object.keys(genChanges).length > 0) {
      payload.generation = genChanges
    }

    saveMutation.mutate(payload)
  }

  // Reset to defaults
  function handleReset() {
    if (!defaults) return
    const f = settingsToForm(defaults)
    setForm(f)
    setApiKeys({ gemini: '', openai: '', openrouter: '' })
    setShowResetDialog(false)
  }

  // Test connection handler
  async function handleTestConnection(provider: string) {
    // Use the typed key or fall back to the existing key on server
    const key = apiKeys[provider]
    if (!key) {
      setTestStatus((prev) => ({
        ...prev,
        [provider]: { testing: false, result: { success: false, error: t('settings.enterKeyToTest') } },
      }))
      return
    }

    setTestStatus((prev) => ({ ...prev, [provider]: { testing: true } }))
    try {
      const result = await testConnection(provider, key)
      setTestStatus((prev) => ({ ...prev, [provider]: { testing: false, result } }))
    } catch {
      setTestStatus((prev) => ({
        ...prev,
        [provider]: { testing: false, result: { success: false, error: t('settings.connectionTestFailed') } },
      }))
    }
  }

  // Form field updater
  function updateForm(field: keyof FormState, value: string) {
    setForm((prev) => (prev ? { ...prev, [field]: value } : prev))
  }

  // Loading state
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (error || !settings || !form) {
    return (
      <div className="py-10 text-center">
        <p className="text-destructive">{t('settings.failedToLoadSettings')}</p>
        <p className="text-muted-foreground text-sm mt-2">{(error as Error)?.message}</p>
      </div>
    )
  }

  return (
    <div className="space-y-8 pb-20">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-bold text-foreground">{t('settings.title')}</h1>
        <p className="text-muted-foreground text-sm mt-1">
          {t('settings.subtitle')}
        </p>
      </div>

      {/* API Keys Section */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">{t('settings.apiKeys')}</CardTitle>
          <CardDescription>
            {t('settings.apiKeysDescription')}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {settings.providers.map((provider) => {
            // Find if any role uses this provider to determine has_key status
            const roleUsingProvider = (['meta', 'target', 'judge'] as const).find(
              (r) => settings[r].provider === provider
            )
            const hasKey = roleUsingProvider ? settings[roleUsingProvider].has_key : false
            const keyHint = roleUsingProvider ? settings[roleUsingProvider].key_hint : ''
            const providerTestStatus = testStatus[provider]

            return (
              <div key={provider} className="flex items-center gap-4 flex-wrap sm:flex-nowrap">
                {/* Provider label */}
                <div className="w-28 shrink-0">
                  <span className="font-medium text-sm">{PROVIDER_DISPLAY_NAMES[provider] ?? provider}</span>
                  {hasKey ? (
                    <Badge variant="secondary" className="ml-2 text-xs">{t('settings.active')}</Badge>
                  ) : (
                    <Badge variant="outline" className="ml-2 text-xs">{t('settings.noKey')}</Badge>
                  )}
                </div>

                {/* Key hint / status */}
                <div className="w-28 shrink-0 text-sm text-muted-foreground font-mono">
                  {hasKey ? keyHint : t('settings.notConfigured')}
                </div>

                {/* Key input */}
                <div className="relative flex-1 min-w-[200px]">
                  <Input
                    type={keyVisible[provider] ? 'text' : 'password'}
                    placeholder={hasKey ? t('settings.enterNewKey') : t('settings.enterApiKey')}
                    value={apiKeys[provider]}
                    onChange={(e) =>
                      setApiKeys((prev) => ({ ...prev, [provider]: e.target.value }))
                    }
                    className="pr-10"
                  />
                  <button
                    type="button"
                    onClick={() =>
                      setKeyVisible((prev) => ({ ...prev, [provider]: !prev[provider] }))
                    }
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  >
                    {keyVisible[provider] ? (
                      <EyeOff className="h-4 w-4" />
                    ) : (
                      <Eye className="h-4 w-4" />
                    )}
                  </button>
                </div>

                {/* Test Connection */}
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handleTestConnection(provider)}
                  disabled={providerTestStatus?.testing}
                  className="shrink-0"
                >
                  {providerTestStatus?.testing ? (
                    <Loader2 className="h-4 w-4 animate-spin mr-1" />
                  ) : null}
                  {t('settings.test')}
                </Button>

                {/* Test result indicator */}
                {providerTestStatus?.result && (
                  <div className="shrink-0">
                    {providerTestStatus.result.success ? (
                      <CheckCircle2 className="h-5 w-5 text-success" />
                    ) : (
                      <span className="flex items-center gap-1 text-xs text-destructive">
                        <XCircle className="h-5 w-5" />
                        {providerTestStatus.result.error}
                      </span>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </CardContent>
      </Card>

      {/* Role Configuration Cards */}
      <div>
        <h2 className="text-lg font-semibold mb-4">{t('settings.roleConfiguration')}</h2>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {(['meta', 'target', 'judge'] as const).map((role) => (
            <RoleCard
              key={role}
              role={role}
              form={form}
              settings={settings}
              onUpdate={updateForm}
            />
          ))}
        </div>
      </div>

      {/* Global Settings */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">{t('settings.globalSettings')}</CardTitle>
          <CardDescription>
            {t('settings.globalSettingsDescription')}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">{t('settings.concurrencyLimit')}</label>
              <Input
                type="number"
                min={1}
                max={50}
                value={form.concurrency_limit}
                onChange={(e) => updateForm('concurrency_limit', e.target.value)}
              />
              <p className="text-xs text-muted-foreground">{t('settings.concurrencyDescription')}</p>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">{t('settings.temperature')}</label>
              <Input
                type="number"
                min={0}
                max={2}
                step={0.1}
                value={form.generation_temperature}
                onChange={(e) => updateForm('generation_temperature', e.target.value)}
              />
              <p className="text-xs text-muted-foreground">{t('settings.temperatureDescription')}</p>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">{t('settings.maxTokens')}</label>
              <Input
                type="number"
                min={1}
                max={32768}
                value={form.generation_max_tokens}
                onChange={(e) => updateForm('generation_max_tokens', e.target.value)}
              />
              <p className="text-xs text-muted-foreground">{t('settings.maxTokensDescription')}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Action Bar */}
      <Separator />
      <div className="flex items-center gap-3">
        <Button onClick={handleSave} disabled={!isDirty || saveMutation.isPending}>
          {saveMutation.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin mr-2" />
          ) : (
            <Save className="h-4 w-4 mr-2" />
          )}
          {t('settings.saveSettings')}
        </Button>
        <Button variant="outline" onClick={() => setShowResetDialog(true)} disabled={!defaults}>
          <RotateCcw className="h-4 w-4 mr-2" />
          {t('settings.resetToDefaults')}
        </Button>
      </div>

      {/* Status Banner */}
      {statusBanner && (
        <div
          className={`rounded-md px-4 py-3 text-sm ${
            statusBanner.type === 'success'
              ? 'bg-success/10 text-success border border-success/20'
              : 'bg-destructive/10 text-destructive border border-destructive/20'
          }`}
        >
          {statusBanner.message}
        </div>
      )}

      {/* Reset Confirmation Dialog */}
      <Dialog open={showResetDialog} onOpenChange={setShowResetDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('settings.resetDialogTitle')}</DialogTitle>
            <DialogDescription>
              {t('settings.resetDialogDescription')}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowResetDialog(false)}>
              {t('common.cancel')}
            </Button>
            <Button variant="destructive" onClick={handleReset}>
              {t('common.reset')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// --- Role Card sub-component ---

function RoleCard({
  role,
  form,
  settings,
  onUpdate,
}: {
  role: RoleName
  form: FormState
  settings: SettingsResponse
  onUpdate: (field: keyof FormState, value: string) => void
}) {
  const { t } = useTranslation()
  const icon = ROLE_ICONS[role]
  const titleKey = `settings.${role}Model` as const
  const descKey = `settings.${role}Description` as const
  const providerField = `${role}_provider` as keyof FormState
  const modelField = `${role}_model` as keyof FormState
  const budgetField = `${role}_thinking_budget` as keyof FormState
  const selectedProvider = form[providerField]

  // Fetch models for selected provider
  const { data: models, isLoading: modelsLoading, error: modelsError } = useQuery({
    queryKey: ['models', selectedProvider],
    queryFn: () => fetchModels(selectedProvider),
    enabled: !!selectedProvider,
    staleTime: 5 * 60 * 1000, // 5 min cache
  })

  // Check if the selected provider has a key configured
  const providerHasKey = useMemo(() => {
    // Check if any role in settings uses this provider and has a key
    for (const r of ['meta', 'target', 'judge'] as const) {
      if (settings[r].provider === selectedProvider && settings[r].has_key) {
        return true
      }
    }
    return false
  }, [settings, selectedProvider])

  // Ensure selected model is available in models list -- if models loaded
  // and current model not in list, keep value but user will see it's custom
  const modelOptions = models ?? []

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2">
          {icon}
          <div>
            <CardTitle className="text-base">{t(titleKey)}</CardTitle>
            <CardDescription className="text-xs">{t(descKey)}</CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Provider dropdown */}
        <div className="space-y-1.5">
          <label className="text-sm font-medium">{t('settings.provider')}</label>
          <Select
            value={form[providerField]}
            onValueChange={(val) => {
              onUpdate(providerField, val)
              // Reset model when provider changes -- user needs to pick a new one
              onUpdate(modelField, '')
            }}
          >
            <SelectTrigger>
              <SelectValue placeholder={t('settings.selectProvider')} />
            </SelectTrigger>
            <SelectContent>
              {settings.providers.map((p) => {
                // Check if provider has a key
                const pHasKey = (['meta', 'target', 'judge'] as const).some(
                  (r) => settings[r].provider === p && settings[r].has_key
                )
                return (
                  <SelectItem key={p} value={p}>
                    <span className={!pHasKey ? 'text-muted-foreground' : ''}>
                      {p}{!pHasKey ? ` ${t('settings.noKeyLabel')}` : ''}
                    </span>
                  </SelectItem>
                )
              })}
            </SelectContent>
          </Select>
        </div>

        {/* Model dropdown */}
        <div className="space-y-1.5">
          <label className="text-sm font-medium">{t('settings.model')}</label>
          {modelsLoading ? (
            <div className="flex items-center gap-2 h-10 px-3 text-sm text-muted-foreground border rounded-md">
              <Loader2 className="h-4 w-4 animate-spin" />
              {t('settings.loadingModels')}
            </div>
          ) : modelsError || (!providerHasKey && modelOptions.length === 0) ? (
            <div className="flex items-center h-10 px-3 text-sm text-muted-foreground border rounded-md bg-muted/50">
              {t('settings.configureApiKeyFirst')}
            </div>
          ) : (
            <Select
              value={form[modelField]}
              onValueChange={(val) => onUpdate(modelField, val)}
            >
              <SelectTrigger>
                <SelectValue placeholder={t('settings.selectModel')} />
              </SelectTrigger>
              <SelectContent>
                {modelOptions.map((m) => (
                  <SelectItem key={m.id} value={m.id}>
                    {m.name || m.id}
                  </SelectItem>
                ))}
                {/* If current model not in list, show it as an option */}
                {form[modelField] && !modelOptions.find((m) => m.id === form[modelField]) && (
                  <SelectItem value={form[modelField]}>
                    {form[modelField]} {t('settings.current')}
                  </SelectItem>
                )}
              </SelectContent>
            </Select>
          )}
        </div>

        {/* Thinking Budget */}
        <div className="space-y-1.5">
          <label className="text-sm font-medium">{t('settings.thinkingBudget')}</label>
          <Input
            type="number"
            min={0}
            max={32768}
            placeholder={t('settings.defaultProviderDecides')}
            value={form[budgetField]}
            onChange={(e) => onUpdate(budgetField, e.target.value)}
          />
        </div>
      </CardContent>
    </Card>
  )
}
