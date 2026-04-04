import { useTranslation } from 'react-i18next'
import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { listPromptsApiPromptsGet, startEvolutionApiEvolutionStartPost } from '../../client/sdk.gen'
import type { EvolutionRunRequest, EvolutionRunStatus, PromptSummary } from '../../client/types.gen'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/select'
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible'
import { Switch } from '@/components/ui/switch'
import { Slider } from '@/components/ui/slider'
import { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider } from '@/components/ui/tooltip'
import { ChevronRight, HelpCircle } from 'lucide-react'
import PresetSelector from './PresetSelector'
import { BUILT_IN_PRESET_NAMES, isPresetMatch, type PresetName } from './evolution-presets'

interface RunConfigFormProps {
  promptId?: string
  onRunStarted?: (runId: string) => void
}

const DEFAULT_CONFIG: EvolutionRunRequest = {
  prompt_id: '',
  generations: 10,
  islands: 4,
  conversations_per_island: 5,
  budget_cap_usd: null,
  sample_size: null,
  sample_ratio: null,
  pr_no_parents: null,
  n_seq: null,
  population_cap: null,
  n_emigrate: null,
  reset_interval: null,
  n_reset: null,
  n_top: null,
}

/** Reusable label + tooltip helper */
function ParamLabel({ htmlFor, label, tooltip }: { htmlFor: string; label: string; tooltip: string }) {
  return (
    <label htmlFor={htmlFor} className="flex items-center gap-1.5 text-sm font-medium text-foreground mb-1">
      {label}
      <Tooltip>
        <TooltipTrigger asChild>
          <HelpCircle className="h-3.5 w-3.5 text-muted-foreground cursor-help" />
        </TooltipTrigger>
        <TooltipContent side="top" className="max-w-xs">
          <p className="text-xs">{tooltip}</p>
        </TooltipContent>
      </Tooltip>
    </label>
  )
}

export default function RunConfigForm({ promptId: propPromptId, onRunStarted }: RunConfigFormProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()

  // The effective promptId: either from prop or selected by user in the dropdown
  const [selectedPromptId, setSelectedPromptId] = useState(propPromptId ?? '')
  const effectivePromptId = propPromptId ?? selectedPromptId

  const [config, setConfig] = useState<EvolutionRunRequest>({
    ...DEFAULT_CONFIG,
    prompt_id: effectivePromptId,
  })

  const [successResult, setSuccessResult] = useState<EvolutionRunStatus | null>(null)

  // Mutation toggle state (off by default)
  const [mutationEnabled, setMutationEnabled] = useState(false)

  // Preset state (string to support both built-in names and "custom-{id}" keys)
  const [activePreset, setActivePreset] = useState<string | null>(null)
  const isCustom = useMemo(() => {
    if ((BUILT_IN_PRESET_NAMES as readonly string[]).includes(activePreset as string)) {
      return !isPresetMatch(config, activePreset as PresetName)
    }
    return false
  }, [config, activePreset])

  const { data: prompts, isLoading: promptsLoading } = useQuery({
    queryKey: ['prompts'],
    queryFn: () => listPromptsApiPromptsGet(),
    enabled: !propPromptId,
  })

  // Preset selection handler (works for both built-in and custom presets)
  function handlePresetSelect(presetName: string, values: Partial<EvolutionRunRequest>) {
    if (!presetName) {
      // Cleared selection (e.g. deleted active custom preset)
      setActivePreset(null)
      return
    }
    setConfig((prev) => ({
      ...prev,
      ...values,
      prompt_id: prev.prompt_id,
    }))
    setActivePreset(presetName)

    // Auto-enable mutation toggle if preset has non-null structural_mutation_probability
    const smp = (values as Record<string, unknown>).structural_mutation_probability as number | null | undefined
    if (smp !== null && smp !== undefined && smp > 0) {
      setMutationEnabled(true)
    } else {
      setMutationEnabled(false)
    }
  }

  // When mutation toggle is turned off, set structural_mutation_probability to null
  function handleMutationToggle(checked: boolean) {
    setMutationEnabled(checked)
    if (!checked) {
      setConfig((prev) => ({ ...prev, structural_mutation_probability: null }))
    } else {
      // When turning on, set a default value if currently null
      setConfig((prev) => ({
        ...prev,
        structural_mutation_probability:
          (prev as Record<string, unknown>).structural_mutation_probability as number ?? 0.2,
      }))
    }
  }

  const mutation = useMutation({
    mutationFn: (body: EvolutionRunRequest) =>
      startEvolutionApiEvolutionStartPost({ body }),
    onSuccess: (data) => {
      const result = data.data as EvolutionRunStatus
      if (onRunStarted && result.run_id) {
        onRunStarted(result.run_id)
      }
      setSuccessResult(result)
      queryClient.invalidateQueries({ queryKey: ['history'] })
    },
  })

  const promptList: PromptSummary[] = (prompts?.data as PromptSummary[] | undefined) ?? []

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!config.prompt_id) return
    // Ensure structural_mutation_probability is null when mutation is disabled
    const submitConfig = {
      ...config,
      structural_mutation_probability: mutationEnabled
        ? (config as Record<string, unknown>).structural_mutation_probability as number
        : null,
    }
    mutation.mutate(submitConfig)
  }

  function updateNum(field: keyof EvolutionRunRequest, value: string, nullable = false) {
    if (nullable && value === '') {
      setConfig((prev) => ({ ...prev, [field]: null }))
      return
    }
    const num = parseFloat(value)
    if (!isNaN(num)) {
      setConfig((prev) => ({ ...prev, [field]: num }))
    }
  }

  const currentMutationProb = (config as Record<string, unknown>).structural_mutation_probability as number | null

  if (successResult) {
    return (
      <Card className="border-success/30">
        <CardContent className="pt-6">
          <h3 className="text-lg font-semibold text-success mb-2">{t('evolution.evolutionStarted')}</h3>
          <p className="text-foreground mb-1">
            {t('evolution.runIdLabel')} <span className="font-mono text-success" data-testid="run-id">{successResult.run_id}</span>
          </p>
          <p className="text-muted-foreground mb-4">
            {t('evolution.statusLabel')} <span className="text-success">{successResult.status}</span>
          </p>
          <div className="flex gap-3">
            <Button variant="secondary" asChild>
              <a href="/history">{t('evolution.viewHistory')}</a>
            </Button>
            <Button
              variant="outline"
              onClick={() => { setSuccessResult(null); mutation.reset() }}
            >
              {t('evolution.startAnother')}
            </Button>
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <TooltipProvider delayDuration={300}>
      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Prompt selector -- hidden when promptId is provided via prop */}
        {!propPromptId && (
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">
              {t('evolution.prompt')}
            </label>
            <Select
              value={config.prompt_id}
              onValueChange={(value) => {
                setSelectedPromptId(value)
                setConfig((prev) => ({ ...prev, prompt_id: value }))
              }}
            >
              <SelectTrigger>
                <SelectValue placeholder={promptsLoading ? t('evolution.loadingPrompts') : t('evolution.selectPrompt')} />
              </SelectTrigger>
              <SelectContent>
                {promptList.map((p) => (
                  <SelectItem key={p.id} value={p.id}>
                    {p.id} -- {p.purpose}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        {/* Preset Selector */}
        <PresetSelector
          activePreset={activePreset}
          isCustom={isCustom}
          onSelect={handlePresetSelect}
          currentValues={config}
        />

        {/* Basic Parameters (always visible) */}
        <div className="rounded-lg border border-border bg-card overflow-hidden">
          <div className="px-4 py-3 border-b border-border">
            <h3 className="text-sm font-semibold text-foreground">{t('evolution.basicParameters')}</h3>
          </div>
          <div className="p-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <ParamLabel
                  htmlFor="generations"
                  label={t('evolution.generations')}
                  tooltip={t('evolution.generationsTooltip')}
                />
                <Input
                  id="generations"
                  type="number"
                  min={1}
                  max={100}
                  value={config.generations ?? 10}
                  onChange={(e) => updateNum('generations', e.target.value)}
                />
              </div>

              <div>
                <ParamLabel
                  htmlFor="islands"
                  label={t('evolution.islands')}
                  tooltip={t('evolution.islandsTooltip')}
                />
                <Input
                  id="islands"
                  type="number"
                  min={1}
                  max={20}
                  value={config.islands ?? 4}
                  onChange={(e) => updateNum('islands', e.target.value)}
                />
              </div>

              <div>
                <ParamLabel
                  htmlFor="conversations"
                  label={t('evolution.conversationsPerIsland')}
                  tooltip={t('evolution.conversationsTooltip')}
                />
                <Input
                  id="conversations"
                  type="number"
                  min={1}
                  max={50}
                  value={config.conversations_per_island ?? 5}
                  onChange={(e) => updateNum('conversations_per_island', e.target.value)}
                />
              </div>

              <div>
                <ParamLabel
                  htmlFor="budget"
                  label={t('evolution.budgetCapUsd')}
                  tooltip={t('evolution.budgetCapTooltip')}
                />
                <Input
                  id="budget"
                  type="number"
                  min={0}
                  step={0.01}
                  value={config.budget_cap_usd ?? ''}
                  onChange={(e) => updateNum('budget_cap_usd', e.target.value, true)}
                  placeholder={t('evolution.noLimit')}
                />
              </div>

              <div>
                <ParamLabel
                  htmlFor="sample-size"
                  label={t('evolution.sampleSize')}
                  tooltip={t('evolution.sampleSizeTooltip')}
                />
                <Input
                  id="sample-size"
                  type="number"
                  min={1}
                  value={config.sample_size ?? ''}
                  onChange={(e) => updateNum('sample_size', e.target.value, true)}
                  placeholder={t('evolution.allCases')}
                />
              </div>

              <div>
                <ParamLabel
                  htmlFor="pr-no-parents"
                  label={t('evolution.newCandidateRatio')}
                  tooltip={t('evolution.newCandidateRatioTooltip')}
                />
                <Input
                  id="pr-no-parents"
                  type="number"
                  min={0}
                  max={1}
                  step={0.01}
                  value={config.pr_no_parents ?? ''}
                  onChange={(e) => updateNum('pr_no_parents', e.target.value, true)}
                  placeholder={t('evolution.modelDefault')}
                />
                <p className="text-xs text-muted-foreground mt-1">{t('evolution.incrementalOnlyScratch')}</p>
              </div>
            </div>
          </div>
        </div>

        {/* Structural Mutation Toggle */}
        <div className="rounded-lg border border-border bg-card overflow-hidden">
          <div className="px-4 py-3 border-b border-border flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <ParamLabel
                htmlFor="mutation-toggle"
                label={t('evolution.structuralMutation')}
                tooltip={t('evolution.structuralMutationTooltip')}
              />
            </div>
            <Switch
              id="mutation-toggle"
              checked={mutationEnabled}
              onCheckedChange={handleMutationToggle}
            />
          </div>
          {mutationEnabled && (
            <div className="p-4 space-y-2">
              <div className="flex items-center justify-between text-sm">
                <span className="text-muted-foreground">{t('evolution.probability')}</span>
                <span className="font-mono text-foreground">
                  {Math.round((currentMutationProb ?? 0.2) * 100)}%
                </span>
              </div>
              <Slider
                value={[currentMutationProb ?? 0.2]}
                onValueChange={([val]) =>
                  setConfig((prev) => ({ ...prev, structural_mutation_probability: val }))
                }
                min={0}
                max={1}
                step={0.05}
                className="w-full"
              />
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>0%</span>
                <span>100%</span>
              </div>
            </div>
          )}
        </div>

        {/* Advanced Evolution Parameters (collapsible, default-closed) */}
        <Collapsible defaultOpen={false} className="rounded-lg border border-border bg-card overflow-hidden">
          <CollapsibleTrigger className="px-4 py-3 border-b border-border flex items-center gap-2 w-full text-left">
            <ChevronRight className="h-4 w-4 transition-transform duration-200 [[data-state=open]_&]:rotate-90" />
            <h3 className="text-sm font-semibold text-foreground">{t('evolution.advancedEvolutionParameters')}</h3>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="p-4 grid grid-cols-1 md:grid-cols-3 gap-4">
                <div>
                  <ParamLabel
                    htmlFor="sel-temperature"
                    label={t('evolution.selectionTemperature')}
                    tooltip={t('evolution.selectionTemperatureTooltip')}
                  />
                  <Input
                    id="sel-temperature"
                    type="number"
                    min={0}
                    max={2}
                    step={0.1}
                    value={(config as Record<string, unknown>).temperature as number ?? ''}
                    onChange={(e) => updateNum('temperature' as keyof EvolutionRunRequest, e.target.value, true)}
                    placeholder="1.0"
                  />
                </div>

                <div>
                  <ParamLabel
                    htmlFor="n-seq"
                    label={t('evolution.nSeq')}
                    tooltip={t('evolution.nSeqTooltip')}
                  />
                  <Input
                    id="n-seq"
                    type="number"
                    min={1}
                    value={config.n_seq ?? ''}
                    onChange={(e) => updateNum('n_seq', e.target.value, true)}
                    placeholder="3"
                  />
                </div>

                <div>
                  <ParamLabel
                    htmlFor="population-cap"
                    label={t('evolution.populationCap')}
                    tooltip={t('evolution.populationCapTooltip')}
                  />
                  <Input
                    id="population-cap"
                    type="number"
                    min={1}
                    value={config.population_cap ?? ''}
                    onChange={(e) => updateNum('population_cap', e.target.value, true)}
                    placeholder="10"
                  />
                </div>

                <div>
                  <ParamLabel
                    htmlFor="n-emigrate"
                    label={t('evolution.emigrateCount')}
                    tooltip={t('evolution.emigrateCountTooltip')}
                  />
                  <Input
                    id="n-emigrate"
                    type="number"
                    min={0}
                    value={config.n_emigrate ?? ''}
                    onChange={(e) => updateNum('n_emigrate', e.target.value, true)}
                    placeholder="5"
                  />
                </div>

                <div>
                  <ParamLabel
                    htmlFor="reset-interval"
                    label={t('evolution.resetInterval')}
                    tooltip={t('evolution.resetIntervalTooltip')}
                  />
                  <Input
                    id="reset-interval"
                    type="number"
                    min={1}
                    value={config.reset_interval ?? ''}
                    onChange={(e) => updateNum('reset_interval', e.target.value, true)}
                    placeholder="3"
                  />
                </div>

                <div>
                  <ParamLabel
                    htmlFor="n-reset"
                    label={t('evolution.resetCount')}
                    tooltip={t('evolution.resetCountTooltip')}
                  />
                  <Input
                    id="n-reset"
                    type="number"
                    min={0}
                    value={config.n_reset ?? ''}
                    onChange={(e) => updateNum('n_reset', e.target.value, true)}
                    placeholder="2"
                  />
                </div>

                <div>
                  <ParamLabel
                    htmlFor="n-top"
                    label={t('evolution.nTop')}
                    tooltip={t('evolution.nTopTooltip')}
                  />
                  <Input
                    id="n-top"
                    type="number"
                    min={1}
                    value={config.n_top ?? ''}
                    onChange={(e) => updateNum('n_top', e.target.value, true)}
                    placeholder="5"
                  />
                </div>
            </div>
          </CollapsibleContent>
        </Collapsible>

        {/* Configure models link */}
        {effectivePromptId && (
          <p className="text-xs text-muted-foreground">
            {t('evolution.modelConfigHint')}{' '}
            <a
              href={`/prompts/${effectivePromptId}/config`}
              className="text-primary underline hover:text-primary/80"
            >
              {t('evolution.configTab')}
            </a>
          </p>
        )}

        {/* Error */}
        {mutation.isError && (
          <div className="rounded-md bg-destructive/10 border border-destructive/30 p-3 text-destructive text-sm">
            {mutation.error instanceof Error ? mutation.error.message : t('evolution.failedToStart')}
          </div>
        )}

        {/* Submit */}
        <Button
          type="submit"
          disabled={!config.prompt_id || mutation.isPending}
          className="w-full md:w-auto"
        >
          {mutation.isPending ? t('evolution.starting') : t('evolution.startEvolution')}
        </Button>
      </form>
    </TooltipProvider>
  )
}
