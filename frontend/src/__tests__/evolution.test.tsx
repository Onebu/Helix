import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import userEvent from '@testing-library/user-event'
import RunConfigForm from '../components/evolution/RunConfigForm'
import ThinkingBudgetControl from '../components/evolution/ThinkingBudgetControl'

// Mock the SDK
vi.mock('../client/sdk.gen', () => ({
  listPromptsApiPromptsGet: vi.fn(),
  startEvolutionApiEvolutionStartPost: vi.fn(),
}))

import { listPromptsApiPromptsGet, startEvolutionApiEvolutionStartPost } from '../client/sdk.gen'

const mockListPrompts = vi.mocked(listPromptsApiPromptsGet)
const mockStartEvolution = vi.mocked(startEvolutionApiEvolutionStartPost)

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  mockListPrompts.mockResolvedValue({
    data: [
      { id: 'test-prompt', purpose: 'Testing prompt', template_variables: [], anchor_variables: [] },
      { id: 'other-prompt', purpose: 'Other', template_variables: [], anchor_variables: [] },
    ],
    response: {} as Response,
    request: {} as Request,
    error: undefined,
  } as never)
})

describe('RunConfigForm', () => {
  it('renders all configuration fields', async () => {
    renderWithProviders(<RunConfigForm />)

    // Radix Select renders differently - no accessible label on trigger
    // But all input fields still use htmlFor labels
    await waitFor(() => {
      expect(screen.getByLabelText('Generations')).toBeInTheDocument()
    })

    expect(screen.getByLabelText('Islands')).toBeInTheDocument()
    expect(screen.getByLabelText('Conversations / Island')).toBeInTheDocument()
    expect(screen.getByLabelText('Budget Cap ($)')).toBeInTheDocument()
    expect(screen.getByLabelText('Sample Size')).toBeInTheDocument()
    expect(screen.getByLabelText('New candidate ratio')).toBeInTheDocument()
    // Prompt label exists as text
    expect(screen.getByText('Prompt')).toBeInTheDocument()

    // Advanced section present (model config & inference moved to Config tab)
    expect(screen.getByText('Advanced Evolution Parameters')).toBeInTheDocument()
  })

  it('submit button disabled without prompt selection', async () => {
    renderWithProviders(<RunConfigForm />)

    await waitFor(() => {
      expect(screen.getByLabelText('Generations')).toBeInTheDocument()
    })

    const button = screen.getByRole('button', { name: /start evolution/i })
    expect(button).toBeDisabled()
  })

  it('renders basic parameters with correct i18n labels', async () => {
    renderWithProviders(<RunConfigForm promptId="test-prompt" />)

    await waitFor(() => {
      expect(screen.getByLabelText('Generations')).toBeInTheDocument()
    })

    // Check basic parameter fields
    expect(screen.getByLabelText('Islands')).toBeInTheDocument()
    expect(screen.getByLabelText('Conversations / Island')).toBeInTheDocument()
    expect(screen.getByLabelText('Budget Cap ($)')).toBeInTheDocument()
    expect(screen.getByLabelText('Sample Size')).toBeInTheDocument()
    expect(screen.getByLabelText('New candidate ratio')).toBeInTheDocument()

    // Basic Parameters section heading
    expect(screen.getByText('Basic Parameters')).toBeInTheDocument()
  })

  it('submits form with correct default values', async () => {
    mockStartEvolution.mockResolvedValue({
      data: { run_id: 'abc-123', prompt_id: 'test-prompt', status: 'running', started_at: '2026-01-01T00:00:00Z' },
      response: {} as Response,
      request: {} as Request,
      error: undefined,
    } as never)

    // Use promptId prop to skip Radix Select interaction
    renderWithProviders(<RunConfigForm promptId="test-prompt" />)

    await waitFor(() => {
      expect(screen.getByLabelText('Generations')).toBeInTheDocument()
    })

    // Set generations to 5
    fireEvent.change(screen.getByLabelText('Generations'), { target: { value: '5' } })

    // Submit without setting any overrides
    fireEvent.click(screen.getByRole('button', { name: /start evolution/i }))

    await waitFor(() => {
      expect(mockStartEvolution).toHaveBeenCalledWith({
        body: expect.objectContaining({
          prompt_id: 'test-prompt',
          generations: 5,
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
        }),
      })
    })
  })

  it('success shows run ID', async () => {
    mockStartEvolution.mockResolvedValue({
      data: { run_id: 'abc-123', prompt_id: 'test-prompt', status: 'running', started_at: '2026-01-01T00:00:00Z' },
      response: {} as Response,
      request: {} as Request,
      error: undefined,
    } as never)

    // Use promptId prop to skip Radix Select interaction
    renderWithProviders(<RunConfigForm promptId="test-prompt" />)

    await waitFor(() => {
      expect(screen.getByLabelText('Generations')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /start evolution/i }))

    await waitFor(() => {
      expect(screen.getByText('abc-123')).toBeInTheDocument()
      expect(screen.getByText('Evolution Started')).toBeInTheDocument()
    })
  })

  it('advanced section collapsed by default, expandable', async () => {
    const user = userEvent.setup()
    renderWithProviders(<RunConfigForm promptId="test-prompt" />)

    await waitFor(() => {
      expect(screen.getByLabelText('Generations')).toBeInTheDocument()
    })

    // Advanced fields should NOT be visible by default (collapsed)
    expect(screen.queryByLabelText('Sequential turns (n_seq)')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Population cap')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Selection temperature')).not.toBeInTheDocument()

    // Click the "Advanced Evolution Parameters" trigger to expand
    await user.click(screen.getByText('Advanced Evolution Parameters'))

    // Now the fields should be visible
    await waitFor(() => {
      expect(screen.getByLabelText('Sequential turns (n_seq)')).toBeInTheDocument()
    })
    expect(screen.getByLabelText('Population cap')).toBeInTheDocument()
    expect(screen.getByLabelText('Emigrate count')).toBeInTheDocument()
    expect(screen.getByLabelText('Reset interval')).toBeInTheDocument()
    expect(screen.getByLabelText('Reset count')).toBeInTheDocument()
    expect(screen.getByLabelText('Top candidates (n_top)')).toBeInTheDocument()
    expect(screen.getByLabelText('Selection temperature')).toBeInTheDocument()
  })

  it('structural mutation toggle present', async () => {
    renderWithProviders(<RunConfigForm promptId="test-prompt" />)

    await waitFor(() => {
      expect(screen.getByLabelText('Generations')).toBeInTheDocument()
    })

    // Structural mutation is a standalone card with a toggle
    expect(screen.getByText('Structural Mutation')).toBeInTheDocument()
  })
})

describe('ThinkingBudgetControl', () => {
  const noop = () => {}

  it('renders budget dropdown when provider is "gemini" and model contains "2.5"', () => {
    render(
      <ThinkingBudgetControl
        provider="gemini"
        modelId="gemini-2.5-flash-preview-05-20"
        thinkingBudget={null}
        thinkingLevel={null}
        onBudgetChange={noop}
        onLevelChange={noop}
      />
    )

    expect(screen.getByText('Server default')).toBeInTheDocument()
  })

  it('renders level dropdown when provider is "gemini" and model contains "3.0"', () => {
    render(
      <ThinkingBudgetControl
        provider="gemini"
        modelId="gemini-3.0-flash"
        thinkingBudget={null}
        thinkingLevel={null}
        onBudgetChange={noop}
        onLevelChange={noop}
      />
    )

    expect(screen.getByText('Server default')).toBeInTheDocument()
  })

  it('renders nothing when provider is null or "openrouter"', () => {
    const { container: c1 } = render(
      <ThinkingBudgetControl
        provider={null}
        modelId="gemini-2.5-flash"
        thinkingBudget={null}
        thinkingLevel={null}
        onBudgetChange={noop}
        onLevelChange={noop}
      />
    )
    expect(c1.innerHTML).toBe('')

    const { container: c2 } = render(
      <ThinkingBudgetControl
        provider="openrouter"
        modelId="gemini-2.5-flash"
        thinkingBudget={null}
        thinkingLevel={null}
        onBudgetChange={noop}
        onLevelChange={noop}
      />
    )
    expect(c2.innerHTML).toBe('')
  })

  it('renders nothing when provider is "gemini" but model is null', () => {
    const { container } = render(
      <ThinkingBudgetControl
        provider="gemini"
        modelId={null}
        thinkingBudget={null}
        thinkingLevel={null}
        onBudgetChange={noop}
        onLevelChange={noop}
      />
    )
    expect(container.innerHTML).toBe('')
  })

  it('renders budget dropdown for alias model "gemini-flash-latest"', () => {
    render(
      <ThinkingBudgetControl
        provider="gemini"
        modelId="gemini-flash-latest"
        thinkingBudget={null}
        thinkingLevel={null}
        onBudgetChange={noop}
        onLevelChange={noop}
      />
    )

    expect(screen.getByText('Server default')).toBeInTheDocument()
  })

  it('renders budget dropdown for alias model "gemini-pro-latest"', () => {
    render(
      <ThinkingBudgetControl
        provider="gemini"
        modelId="gemini-pro-latest"
        thinkingBudget={null}
        thinkingLevel={null}
        onBudgetChange={noop}
        onLevelChange={noop}
      />
    )

    expect(screen.getByText('Server default')).toBeInTheDocument()
  })

  it('budget dropdown includes "Dynamic (auto)" option for 2.5 models', () => {
    const onBudgetChange = vi.fn()
    render(
      <ThinkingBudgetControl
        provider="gemini"
        modelId="gemini-2.5-pro-preview-05-06"
        thinkingBudget={-1}
        thinkingLevel={null}
        onBudgetChange={onBudgetChange}
        onLevelChange={noop}
      />
    )

    // When budget is set to -1, the select should display "Dynamic (auto)"
    // Radix Select renders the selected option's label in the trigger
    expect(screen.getByText('Dynamic (auto)')).toBeInTheDocument()
  })
})
