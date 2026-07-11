import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import HyperparameterDisplay, { isOverride } from '../components/evolution/HyperparameterDisplay'
import i18n from '../i18n'
describe('HyperparameterDisplay', () => {
  it('uses the public RCC rounds label', async () => {
    render(<HyperparameterDisplay hyperparameters={{ rcc_rounds: 3 }} />)

    await userEvent.click(screen.getByText('All parameters'))

    expect(screen.getByText('RCC rounds')).toBeInTheDocument()
  })

  it('localizes the RCC rounds label', async () => {
    await i18n.changeLanguage('es')
    try {
      render(<HyperparameterDisplay hyperparameters={{ rcc_rounds: 3 }} />)

      await userEvent.click(screen.getByText('All parameters'))

      expect(screen.getByText('Rondas RCC')).toBeInTheDocument()
    } finally {
      await i18n.changeLanguage('en')
    }
  })

  it('renders category headings when params from each group are present', async () => {
    const hyperparameters = {
      generations: 10,
      conversations_per_island: 5,
      rcc_rounds: 3,
      sample_size: 50,
      n_islands: 4,
      n_emigrate: 5,
    }
    render(<HyperparameterDisplay hyperparameters={hyperparameters} />)

    // Expand the detail section
    await userEvent.click(screen.getByText('All parameters'))

    expect(screen.getByText('Evolution')).toBeInTheDocument()
    expect(screen.getByText('Sampling')).toBeInTheDocument()
    expect(screen.getByText('Island Model')).toBeInTheDocument()
  })

  it('does not render empty categories (Inference heading absent when no inference sub-dict)', async () => {
    const hyperparameters = {
      generations: 10,
      n_islands: 4,
    }
    render(<HyperparameterDisplay hyperparameters={hyperparameters} />)

    await userEvent.click(screen.getByText('All parameters'))

    expect(screen.getByText('Evolution')).toBeInTheDocument()
    expect(screen.getByText('Island Model')).toBeInTheDocument()
    expect(screen.queryByText('Inference')).not.toBeInTheDocument()
    expect(screen.queryByText('Sampling')).not.toBeInTheDocument()
  })

  it('shows override badge for values that differ from defaults', () => {
    const hyperparameters = {
      generations: 20, // default is 10
      conversations_per_island: 5, // default is 5, no override
    }
    render(<HyperparameterDisplay hyperparameters={hyperparameters} />)

    // generations=20 differs from default 10 -> should show override badge
    const overrideBadges = screen.getAllByText('override')
    expect(overrideBadges.length).toBeGreaterThanOrEqual(1)

    // Check that the override value is rendered with amber styling
    const generationsValue = screen.getByText('20')
    expect(generationsValue).toBeInTheDocument()
  })

  it('does not show override badge for values at default', () => {
    const hyperparameters = {
      generations: 10, // default is 10
      conversations_per_island: 5, // default is 5
    }
    render(<HyperparameterDisplay hyperparameters={hyperparameters} />)

    // No overrides, so no "override" badges
    expect(screen.queryByText('override')).not.toBeInTheDocument()
  })

  it('handles inference sub-dict -- flattens inference.temperature to display in Inference group', async () => {
    const hyperparameters = {
      generations: 10,
      inference: {
        temperature: 0.9,
        top_p: 0.95,
        max_tokens: 2048,
      },
    }
    render(<HyperparameterDisplay hyperparameters={hyperparameters} />)

    await userEvent.click(screen.getByText('All parameters'))

    // Inference group should be visible
    expect(screen.getByText('Inference')).toBeInTheDocument()

    // Values should be displayed
    expect(screen.getByText('0.9')).toBeInTheDocument()
    expect(screen.getByText('0.95')).toBeInTheDocument()
    expect(screen.getByText('2048')).toBeInTheDocument()

    // inference.temperature -> inference_temperature, default 0.7, override at 0.9
    const overrideBadges = screen.getAllByText('override')
    expect(overrideBadges.length).toBeGreaterThanOrEqual(1)
  })

  it('shows Thinking group when thinking sub-dict present with override badges', async () => {
    const hyperparameters = {
      generations: 10,
      thinking: {
        meta: { thinking_budget: 1024 },
      },
    }
    render(<HyperparameterDisplay hyperparameters={hyperparameters} />)

    await userEvent.click(screen.getByText('All parameters'))

    // Thinking group heading should be visible
    expect(screen.getByText('Thinking')).toBeInTheDocument()

    // Budget value should be displayed
    expect(screen.getByText('1024')).toBeInTheDocument()

    // Non-null thinking value = override (default is null)
    const overrideBadges = screen.getAllByText('override')
    expect(overrideBadges.length).toBeGreaterThanOrEqual(1)
  })

  it('does not show Thinking group when no thinking sub-dict present', () => {
    const hyperparameters = {
      generations: 10,
      n_islands: 4,
    }
    render(<HyperparameterDisplay hyperparameters={hyperparameters} />)

    expect(screen.queryByText('Thinking')).not.toBeInTheDocument()
  })

  it('handles old run data gracefully (no inference key, no crash)', async () => {
    const hyperparameters = {
      generations: 10,
      conversations_per_island: 5,
      rcc_rounds: 3,
      n_parents: 5,
      temperature: 1.0,
      structural_mutation_probability: 0.2,
      pr_no_parents: 0.16666666666666666,
      budget_cap_usd: null,
      population_cap: 10,
      n_islands: 4,
      n_emigrate: 5,
      reset_interval: 3,
      n_reset: 2,
      n_top: 5,
      sample_size: null,
      sample_ratio: null,
    }
    // Should not throw
    const { container } = render(<HyperparameterDisplay hyperparameters={hyperparameters} />)
    expect(container).toBeTruthy()

    await userEvent.click(screen.getByText('All parameters'))

    // Should render Evolution and Island Model groups
    expect(screen.getByText('Evolution')).toBeInTheDocument()
    expect(screen.getByText('Island Model')).toBeInTheDocument()

    // No inference group
    expect(screen.queryByText('Inference')).not.toBeInTheDocument()
  })
})

describe('isOverride', () => {
  it('returns false when value matches default', () => {
    expect(isOverride('generations', 10)).toBe(false)
  })

  it('returns true when value differs from default', () => {
    expect(isOverride('generations', 20)).toBe(true)
  })

  it('handles float comparison with epsilon', () => {
    // pr_no_parents default is 1/6 ~ 0.16666...
    expect(isOverride('pr_no_parents', 1 / 6)).toBe(false)
    expect(isOverride('pr_no_parents', 0.5)).toBe(true)
  })

  it('null default + null value = not override', () => {
    expect(isOverride('budget_cap_usd', null)).toBe(false)
  })

  it('null default + non-null value = override', () => {
    expect(isOverride('budget_cap_usd', 10)).toBe(true)
  })
})
