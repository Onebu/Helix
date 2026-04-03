import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'

/** Key parameters always shown in the summary row. */
const KEY_PARAMS = ['generations', 'conversations_per_island', 'n_islands', 'sample_size', 'budget_cap_usd']

/**
 * Hyperparameter category groupings.
 * Keys are display headings, values are the parameter keys that belong to each group.
 */
const HYPER_GROUPS: Record<string, string[]> = {
  'evolution': [
    'generations', 'conversations_per_island', 'n_seq', 'n_parents',
    'temperature', 'structural_mutation_probability', 'pr_no_parents',
    'budget_cap_usd', 'population_cap',
  ],
  'sampling': ['sample_size', 'sample_ratio'],
  'islandModel': ['n_islands', 'n_emigrate', 'reset_interval', 'n_reset', 'n_top'],
  'inference': [
    'inference_temperature', 'top_p', 'top_k', 'max_tokens',
    'frequency_penalty', 'presence_penalty',
  ],
  'thinking': [
    'meta_thinking_budget', 'meta_thinking_level',
    'target_thinking_budget', 'target_thinking_level',
    'judge_thinking_budget', 'judge_thinking_level',
  ],
}

/**
 * Default values from EvolutionConfig + GenerationConfig.
 * Used to determine which values are overrides.
 */
export const HYPER_DEFAULTS: Record<string, number | string | null> = {
  generations: 10,
  conversations_per_island: 5,
  n_seq: 3,
  n_parents: 5,
  temperature: 1.0,
  structural_mutation_probability: 0.2,
  pr_no_parents: 1 / 6,
  budget_cap_usd: null,
  population_cap: 10,
  n_islands: 4,
  n_emigrate: 5,
  reset_interval: 3,
  n_reset: 2,
  n_top: 5,
  sample_size: null,
  sample_ratio: null,
  inference_temperature: 0.7,
  top_p: null,
  top_k: null,
  max_tokens: 4096,
  frequency_penalty: null,
  presence_penalty: null,
  meta_thinking_budget: null,
  meta_thinking_level: null,
  target_thinking_budget: null,
  target_thinking_level: null,
  judge_thinking_budget: null,
  judge_thinking_level: null,
}

/**
 * Check if a hyperparameter value differs from its default.
 * Uses epsilon comparison for floats.
 */
export function isOverride(key: string, value: unknown): boolean {
  const defaultVal = HYPER_DEFAULTS[key]

  // Both null = not override
  if (defaultVal === null && value === null) return false
  // Default null but value set = override
  if (defaultVal === null && value !== null) return true
  // Value null but default set = override (explicit null override)
  if (defaultVal !== null && value === null) return true

  // Numeric comparison with epsilon for floats
  if (typeof defaultVal === 'number' && typeof value === 'number') {
    return Math.abs(defaultVal - value) > 1e-9
  }

  return defaultVal !== value
}

interface ModelInfo {
  metaModel: string | null
  metaProvider: string | null
  targetModel: string | null
  targetProvider: string | null
  judgeModel: string | null
  judgeProvider: string | null
}

interface HyperparameterDisplayProps {
  hyperparameters: Record<string, unknown>
  modelInfo?: ModelInfo
}

/**
 * Convert underscore_keys to human-readable Title Case labels.
 */
function formatLabel(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

/**
 * Flatten the hyperparameters dict:
 * - Extract `inference` sub-dict keys with proper mapping (temperature -> inference_temperature)
 * - Remove the `inference` key itself
 * - Return a flat key-value map
 */
function flattenHyperparameters(raw: Record<string, unknown>): Record<string, unknown> {
  const flat: Record<string, unknown> = {}

  for (const [key, value] of Object.entries(raw)) {
    if (key === 'inference' && typeof value === 'object' && value !== null) {
      // Flatten inference sub-dict
      const inference = value as Record<string, unknown>
      for (const [iKey, iValue] of Object.entries(inference)) {
        if (iKey === 'temperature') {
          flat['inference_temperature'] = iValue
        } else {
          flat[iKey] = iValue
        }
      }
    } else if (key === 'thinking' && typeof value === 'object' && value !== null) {
      // Flatten thinking sub-dict: { meta: { thinking_budget: 1024 }, target: { thinking_level: "low" } }
      const thinking = value as Record<string, unknown>
      for (const [role, roleConfig] of Object.entries(thinking)) {
        if (typeof roleConfig === 'object' && roleConfig !== null) {
          const rc = roleConfig as Record<string, unknown>
          if ('thinking_budget' in rc) {
            flat[`${role}_thinking_budget`] = rc.thinking_budget
          }
          if ('thinking_level' in rc) {
            flat[`${role}_thinking_level`] = rc.thinking_level
          }
        }
      }
    } else {
      flat[key] = value
    }
  }

  return flat
}

function ParamRow({ label, value, override, t }: { label: string; value: unknown; override: boolean; t: (k: string) => string }) {
  return (
    <div className="flex items-center justify-between gap-2 text-sm">
      <span className="text-muted-foreground truncate">{label}</span>
      <span className="flex items-center gap-1.5 shrink-0">
        <span className={override ? 'font-mono text-warning' : 'font-mono text-foreground'}>
          {String(value)}
        </span>
        {override && (
          <Badge variant="outline" className="text-warning border-warning/30 px-1.5 py-0 text-[10px]">
            {t('evolution.override')}
          </Badge>
        )}
      </span>
    </div>
  )
}

function ModelBadge({ role, provider, model }: { role: string; provider: string | null; model: string }) {
  return (
    <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
      <span>{role}</span>
      <span className="font-mono text-foreground text-xs">{provider ? `${provider}/` : ''}{model}</span>
    </span>
  )
}

export default function HyperparameterDisplay({ hyperparameters, modelInfo }: HyperparameterDisplayProps) {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState(false)
  const flat = flattenHyperparameters(hyperparameters)

  const hasModels = modelInfo && (modelInfo.metaModel || modelInfo.targetModel || modelInfo.judgeModel)
  const hasParams = Object.keys(flat).length > 0

  // Split into key params (always visible) and advanced params
  const keyEntries = KEY_PARAMS
    .filter((k) => k in flat && flat[k] !== null && flat[k] !== undefined)
    .map((k) => ({ key: k, label: formatLabel(k), value: flat[k], override: isOverride(k, flat[k]) }))

  return (
    <div className="space-y-1">
      {/* Compact summary row: models + key params, all inline */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 text-sm px-1">
        {hasModels && (
          <>
            {modelInfo.metaModel && (
              <ModelBadge role="Meta" provider={modelInfo.metaProvider} model={modelInfo.metaModel} />
            )}
            {modelInfo.targetModel && (
              <ModelBadge role="Target" provider={modelInfo.targetProvider} model={modelInfo.targetModel} />
            )}
            {modelInfo.judgeModel && (
              <ModelBadge role="Judge" provider={modelInfo.judgeProvider} model={modelInfo.judgeModel} />
            )}
            {keyEntries.length > 0 && (
              <span className="text-muted-foreground/30">|</span>
            )}
          </>
        )}
        {keyEntries.map(({ key, label, value, override }) => (
          <span key={key} className="inline-flex items-center gap-1 text-xs text-muted-foreground">
            {label}
            <span className={override ? 'font-mono text-warning' : 'font-mono text-foreground'}>
              {String(value)}
            </span>
            {override && (
              <Badge variant="outline" className="text-warning border-warning/30 px-1 py-0 text-[10px] leading-tight">
                {t('evolution.override')}
              </Badge>
            )}
          </span>
        ))}
      </div>

      {/* Expandable full detail */}
      {hasParams && (
        <>
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors px-1"
          >
            <ChevronDown className={`h-3.5 w-3.5 transition-transform ${expanded ? '' : '-rotate-90'}`} />
            {expanded ? 'Hide parameters' : 'All parameters'}
          </button>

          {expanded && (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 pt-2">
              {Object.entries(HYPER_GROUPS).map(([groupName, keys]) => {
                const presentKeys = keys.filter((k) => k in flat && flat[k] !== null && flat[k] !== undefined)
                if (presentKeys.length === 0) return null

                return (
                  <Card key={groupName} className="bg-card/50">
                    <CardContent className="p-4">
                      <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
                        {t(`evolution.${groupName}`)}
                      </h4>
                      <div className="space-y-2">
                        {presentKeys.map((k) => (
                          <ParamRow
                            key={k}
                            label={formatLabel(k)}
                            value={flat[k]}
                            override={isOverride(k, flat[k])}
                            t={t}
                          />
                        ))}
                      </div>
                    </CardContent>
                  </Card>
                )
              })}
            </div>
          )}
        </>
      )}
    </div>
  )
}
