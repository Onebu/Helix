import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { EvolutionState } from '../types/evolution'

// Use vi.hoisted to create mock state that vi.mock factories can reference
const { mockEvolutionState, mockRunResults, mockInitialState, mockUseRunResults, mockAcceptVersion } = vi.hoisted(() => {
  const mockInitialState: EvolutionState = {
    status: 'idle',
    generations: [],
    candidates: [],
    migrations: [],
    summary: {
      bestFitness: null,
      bestNormalized: null,
      seedFitness: null,
      improvementDelta: 0,
      terminationReason: null,
      lineageEventCount: 0,
      totalCostUsd: 0,
      generationsCompleted: 0,
    },
    islandCount: 0,
  }

  const mockEvolutionState: EvolutionState = { ...mockInitialState }
  const mockRunResults: { data: unknown; loading: boolean; error: string | null } = {
    data: null,
    loading: false,
    error: null,
  }

  const mockUseRunResults = vi.fn((_runId?: string, _refetchKey?: number) => mockRunResults)
  const mockAcceptVersion = vi.fn()

  return { mockEvolutionState, mockRunResults, mockInitialState, mockUseRunResults, mockAcceptVersion }
})

// --- Mock hooks (paths relative to test file) ---
vi.mock('../hooks/useEvolutionSocket', () => ({
  useEvolutionSocket: () => mockEvolutionState,
  initialState: mockInitialState,
}))

vi.mock('../hooks/useRunResults', () => ({
  useRunResults: (runId: string, refetchKey?: number) => mockUseRunResults(runId, refetchKey),
}))

// Mock SDK function used by useQuery in the component
vi.mock('../client/sdk.gen', () => ({
  getRunStatusApiEvolutionRunIdStatusGet: vi.fn().mockResolvedValue({ data: null }),
  acceptVersionApiPromptsPromptIdVersionsAcceptPost: mockAcceptVersion,
  listCasesApiPromptsPromptIdDatasetGet: vi.fn().mockResolvedValue({ data: [] }),
}))

// --- Mock child components to avoid import cascades ---
vi.mock('../components/evolution/FitnessChart', () => ({
  default: () => <div data-testid="fitness-chart">FitnessChart</div>,
}))
vi.mock('../components/evolution/GenerationTable', () => ({
  default: () => <div data-testid="generation-table">GenerationTable</div>,
}))
vi.mock('../components/evolution/DiffViewer', () => ({
  default: () => <div data-testid="diff-viewer">DiffViewer</div>,
}))
vi.mock('../components/evolution/MutationStats', () => ({
  default: () => <div data-testid="mutation-stats">MutationStats</div>,
}))
vi.mock('../components/evolution/CaseResultsGrid', () => ({
  default: () => <div data-testid="case-results-grid">CaseResultsGrid</div>,
}))
vi.mock('../components/evolution/HyperparameterDisplay', () => ({
  default: () => <div data-testid="hyperparameter-display">HyperparameterDisplay</div>,
}))

// SummaryCards mock (no longer rendered directly, CompactSummary is used instead)
vi.mock('../components/evolution/SummaryCards', () => ({
  default: () => null,
}))

import EvolutionDashboard from '../components/evolution/EvolutionDashboard'

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query === '(min-width: 1280px)',
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }))
  vi.clearAllMocks()
  mockUseRunResults.mockImplementation(() => mockRunResults)
  mockAcceptVersion.mockResolvedValue({ data: { version: 3 } })
  // Reset mock state
  Object.assign(mockEvolutionState, {
    ...mockInitialState,
    summary: { ...mockInitialState.summary },
  })
  mockRunResults.data = null
  mockRunResults.loading = false
  mockRunResults.error = null
})

describe('EvolutionDashboard transition', () => {
  it('clears prior run evidence and acceptance state when runId changes', async () => {
    const user = userEvent.setup()
    Object.assign(mockEvolutionState, {
      ...mockInitialState,
      status: 'complete',
      summary: { ...mockInitialState.summary },
    })
    mockRunResults.data = {
      promptId: 'old-prompt',
      lineageEvents: [{
        candidateId: 'old-candidate', parentIds: [], generation: 0, island: 0,
        fitnessScore: -1, normalizedScore: 0.8, rejected: false,
        mutationType: 'seed', survived: true, template: 'Old prompt',
      }],
      caseResults: [], seedCaseResults: [], generationRecords: [],
      bestCandidateId: 'old-candidate', bestTemplate: 'Old prompt',
      totalCostUsd: 0.1, bestFitnessScore: -1, bestNormalizedScore: 0.8,
      generationsCompleted: 1, terminationReason: 'generations_complete',
      metaModel: null, targetModel: null, judgeModel: null,
      metaProvider: null, targetProvider: null, judgeProvider: null,
      hyperparameters: null,
    }
    const view = renderWithProviders(<EvolutionDashboard runId="old-run" />)
    await user.click(screen.getByRole('button', { name: 'Accept as new version' }))
    expect(await screen.findByText('Accepted as v3')).toBeInTheDocument()

    mockRunResults.data = null
    Object.assign(mockEvolutionState, {
      ...mockInitialState,
      status: 'connecting',
      summary: { ...mockInitialState.summary },
    })
    view.rerender(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter><EvolutionDashboard runId="new-run" /></MemoryRouter>
      </QueryClientProvider>,
    )

    expect(screen.queryByText('old-candidate')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Accept as new version' })).not.toBeInTheDocument()
    expect(screen.queryByText(/Accepted as v/)).not.toBeInTheDocument()
    expect(within(screen.getByRole('complementary', { name: 'Candidate inspector' }))
      .getByText('No candidate selected')).toBeInTheDocument()
  })

  it.each(['complete', 'budget_exhausted', 'cancelled', 'failed'] as const)(
    'refetches persisted results when a run becomes %s',
    (terminalStatus) => {
      vi.useFakeTimers()
      Object.assign(mockEvolutionState, {
        ...mockInitialState,
        status: 'running',
        summary: { ...mockInitialState.summary },
      })
      const view = renderWithProviders(<EvolutionDashboard runId="terminal-run" />)

      mockEvolutionState.status = terminalStatus
      view.rerender(
        <QueryClientProvider client={new QueryClient()}>
          <MemoryRouter><EvolutionDashboard runId="terminal-run" /></MemoryRouter>
        </QueryClientProvider>,
      )
      act(() => vi.advanceTimersByTime(2000))

      expect(mockUseRunResults).toHaveBeenLastCalledWith('terminal-run', 1)
      vi.useRealTimers()
    },
  )

  it('keeps the workbench tabs visible while status is running', () => {
    // Set up running state
    Object.assign(mockEvolutionState, {
      ...mockInitialState,
      status: 'running',
      summary: { ...mockInitialState.summary },
    })
    mockRunResults.data = null

    renderWithProviders(<EvolutionDashboard runId="test-run-1" />)

    // Compact summary and FitnessChart should be present
    expect(screen.getByTestId('fitness-chart')).toBeInTheDocument()

    expect(screen.getByRole('tab', { name: 'Progress' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Lineage' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Cases' })).toBeInTheDocument()
  })

  it('shows tabbed view when results data arrives', () => {
    // Set up complete state with results
    Object.assign(mockEvolutionState, {
      ...mockInitialState,
      status: 'complete',
      summary: { ...mockInitialState.summary },
    })
    mockRunResults.data = {
      lineageEvents: [
        {
          candidateId: 'seed-1',
          parentIds: [],
          generation: 0,
          island: 0,
          fitnessScore: 0.4,
          normalizedScore: -0.6,
          rejected: false,
          mutationType: 'seed',
          survived: true,
        },
      ],
      caseResults: [],
      seedCaseResults: [],
      generationRecords: [],
      bestCandidateId: 'seed-1',
      bestTemplate: null,
      totalCostUsd: 0.5,
      bestFitnessScore: 0.4,
      bestNormalizedScore: -0.6,
      generationsCompleted: 1,
      terminationReason: 'max_generations',
      metaModel: null,
      targetModel: null,
      judgeModel: null,
      metaProvider: null,
      targetProvider: null,
      judgeProvider: null,
      hyperparameters: null,
    }

    renderWithProviders(<EvolutionDashboard runId="test-run-2" />)

    expect(screen.getByRole('tab', { name: 'Progress' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Lineage' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Cases' })).toBeInTheDocument()
  })

  it('selects the newest feasible live candidate at the best fitness', () => {
    Object.assign(mockEvolutionState, {
      ...mockInitialState,
      status: 'running',
      candidates: [
        {
          candidateId: 'older-best', generation: 1, island: 0,
          fitnessScore: -1, normalizedScore: 0.8, rejected: false,
          mutationType: 'rcc', parentIds: [],
        },
        {
          candidateId: 'rejected-high', generation: 2, island: 0,
          fitnessScore: 0, normalizedScore: 1, rejected: true,
          mutationType: 'rcc', parentIds: [],
        },
        {
          candidateId: 'newest-best', generation: 2, island: 1,
          fitnessScore: -1, normalizedScore: 0.8, rejected: false,
          mutationType: 'rcc', parentIds: [],
        },
      ],
      summary: { ...mockInitialState.summary, lineageEventCount: 3 },
    })

    renderWithProviders(<EvolutionDashboard runId="live-selection" />)

    const inspector = screen.getByRole('complementary', { name: 'Candidate inspector' })
    expect(within(inspector).getByText('newest-best')).toBeInTheDocument()
    expect(within(inspector).queryByText('rejected-high')).not.toBeInTheDocument()
  })

  it('selects the persisted winner when results replace a manual live selection', async () => {
    const user = userEvent.setup()
    Object.assign(mockEvolutionState, {
      ...mockInitialState,
      status: 'running',
      candidates: [
        {
          candidateId: 'live-selected', generation: 1, island: 0,
          fitnessScore: -2, normalizedScore: 0.6, rejected: false,
          mutationType: 'rcc', parentIds: [], template: 'Live prompt',
        },
        {
          candidateId: 'persisted-best', generation: 2, island: 1,
          fitnessScore: -1, normalizedScore: 0.8, rejected: false,
          mutationType: 'rcc', parentIds: ['live-selected'], template: 'Best prompt',
        },
      ],
      summary: { ...mockInitialState.summary, lineageEventCount: 2 },
    })
    const view = renderWithProviders(<EvolutionDashboard runId="phase-selection" />)
    await user.click(screen.getByRole('tab', { name: 'Lineage' }))
    await user.click(screen.getByRole('button', { name: /candidate live-selected/i }))
    expect(within(screen.getByRole('complementary', { name: 'Candidate inspector' }))
      .getByText('live-selected')).toBeInTheDocument()

    mockRunResults.data = {
      promptId: null,
      lineageEvents: [
        {
          candidateId: 'live-selected', parentIds: [], generation: 1, island: 0,
          fitnessScore: -2, normalizedScore: 0.6, rejected: false,
          mutationType: 'rcc', survived: true, template: 'Live prompt',
        },
        {
          candidateId: 'persisted-best', parentIds: ['live-selected'], generation: 2, island: 1,
          fitnessScore: -1, normalizedScore: 0.8, rejected: false,
          mutationType: 'rcc', survived: true, template: 'Best prompt',
        },
      ],
      caseResults: [], seedCaseResults: [], generationRecords: [],
      bestCandidateId: 'persisted-best', bestTemplate: 'Best prompt',
      totalCostUsd: 0.5, bestFitnessScore: -1, bestNormalizedScore: 0.8,
      generationsCompleted: 2, terminationReason: 'generations_complete',
      metaModel: null, targetModel: null, judgeModel: null,
      metaProvider: null, targetProvider: null, judgeProvider: null,
      hyperparameters: null,
    }
    view.rerender(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter><EvolutionDashboard runId="phase-selection" /></MemoryRouter>
      </QueryClientProvider>,
    )

    const inspector = screen.getByRole('complementary', { name: 'Candidate inspector' })
    expect(within(inspector).getByText('persisted-best')).toBeInTheDocument()
    expect(within(inspector).queryByText('live-selected')).not.toBeInTheDocument()
  })

  it('derives historicalSummary from results when WS has no events', () => {
    // WS state has no events (lineageEventCount=0)
    Object.assign(mockEvolutionState, {
      ...mockInitialState,
      status: 'complete',
      summary: {
        ...mockInitialState.summary,
        lineageEventCount: 0,
      },
    })

    // Results have seed events
    mockRunResults.data = {
      lineageEvents: [
        {
          candidateId: 'seed-1',
          parentIds: [],
          generation: 0,
          island: 0,
          fitnessScore: -3.5,
          normalizedScore: -0.8,
          rejected: false,
          mutationType: 'seed',
          survived: true,
        },
        {
          candidateId: 'seed-2',
          parentIds: [],
          generation: 0,
          island: 1,
          fitnessScore: -2.0,
          normalizedScore: -0.5,
          rejected: false,
          mutationType: 'seed',
          survived: true,
        },
      ],
      caseResults: [],
      seedCaseResults: [],
      generationRecords: [],
      bestCandidateId: 'seed-2',
      bestTemplate: null,
      totalCostUsd: 0.3,
      bestFitnessScore: -2.0,
      bestNormalizedScore: -0.5,
      generationsCompleted: 1,
      terminationReason: 'max_generations',
      metaModel: null,
      targetModel: null,
      judgeModel: null,
      metaProvider: null,
      targetProvider: null,
      judgeProvider: null,
      hyperparameters: null,
    }

    renderWithProviders(<EvolutionDashboard runId="test-run-3" />)

    const inspector = screen.getByRole('complementary', { name: 'Candidate inspector' })
    expect(within(inspector).getByText('seed-2')).toBeInTheDocument()
    expect(within(inspector).getByText('-2.000')).toBeInTheDocument()
  })
})
