import type { EvolutionRunRequest } from '../../client/types.gen'

export const PRESET_NAMES = ['conservative', 'balanced', 'aggressive'] as const
export const BUILT_IN_PRESET_NAMES = PRESET_NAMES

export type PresetName = (typeof PRESET_NAMES)[number]

/** Response shape from /api/presets endpoint */
export interface PresetResponse {
  id: number
  name: string
  type: string
  data: Record<string, unknown>
  is_default: boolean
  created_at: string
}

export interface PresetConfig {
  name: PresetName
  label: string
  description: string
  values: Partial<EvolutionRunRequest>
}

export const PRESETS: Record<PresetName, PresetConfig> = {
  conservative: {
    name: 'conservative',
    label: 'Conservative',
    description: 'Slower, steadier improvement. Best for production prompts.',
    values: {
      evolution_profile: 'cost_controlled',
      generations: 15,
      islands: 2,
      conversations_per_island: 8,
      population_cap: 8,
      pr_no_parents: 0.1,
      temperature: 0.7,
      structural_mutation_probability: 0.1,
      rcc_rounds: 5,
      n_emigrate: 2,
      reset_interval: 5,
      n_reset: 1,
      n_top: 3,
    },
  },
  balanced: {
    name: 'balanced',
    label: 'Balanced',
    description: 'Good balance of exploration and refinement. Recommended default.',
    values: {
      evolution_profile: 'cost_controlled',
      generations: 10,
      islands: 4,
      conversations_per_island: 5,
      population_cap: 10,
      pr_no_parents: 0.3,
      temperature: 1.0,
      structural_mutation_probability: 0.2,
      rcc_rounds: 3,
      n_emigrate: 5,
      reset_interval: 3,
      n_reset: 2,
      n_top: 5,
    },
  },
  aggressive: {
    name: 'aggressive',
    label: 'Aggressive',
    description: 'Maximum exploration. Best for new or underperforming prompts.',
    values: {
      evolution_profile: 'cost_controlled',
      generations: 8,
      islands: 6,
      conversations_per_island: 4,
      population_cap: 15,
      pr_no_parents: 0.5,
      temperature: 1.3,
      structural_mutation_probability: 0.4,
      rcc_rounds: 2,
      n_emigrate: 8,
      reset_interval: 2,
      n_reset: 3,
      n_top: 7,
    },
  },
}

/**
 * Fields always visible in the basic config section.
 */
export const BASIC_FIELDS: (keyof EvolutionRunRequest)[] = [
  'generations',
  'islands',
  'conversations_per_island',
  'budget_cap_usd',
  'sample_size',
  'pr_no_parents',
]

/**
 * Returns true if all non-null values in the given preset match the
 * corresponding values in `config`. Used to detect whether the user
 * has customised a preset (showing a "Custom" badge when they diverge).
 */
export function isPresetMatch(
  config: Partial<EvolutionRunRequest>,
  presetName: PresetName,
): boolean {
  const preset = PRESETS[presetName]
  if (!preset) return false

  return Object.entries(preset.values).every(([key, value]) => {
    if (value === null || value === undefined) return true
    const configValue = config[key as keyof EvolutionRunRequest]
    return configValue === value
  })
}

/**
 * Look up preset values by name — checks built-in presets first, then custom.
 * Returns the form values or null if not found.
 */
export function getPresetValues(
  name: string,
  customPresets: PresetResponse[],
): Partial<EvolutionRunRequest> | null {
  // Check built-in presets
  if ((PRESET_NAMES as readonly string[]).includes(name)) {
    return PRESETS[name as PresetName].values
  }

  // Check custom presets (key format: "custom-{id}")
  if (name.startsWith('custom-')) {
    const id = parseInt(name.replace('custom-', ''), 10)
    const custom = customPresets.find((p) => p.id === id)
    if (custom) {
      return custom.data as Partial<EvolutionRunRequest>
    }
  }

  return null
}
