import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { EvolutionState, SummaryData } from '../types/evolution'

// Use vi.hoisted to create mock state that vi.mock factories can reference
const { mockEvolutionState, mockRunResults, mockInitialState } = vi.hoisted(() => {
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

  return { mockEvolutionState, mockRunResults, mockInitialState }
})

// --- Mock hooks (paths relative to test file) ---
vi.mock('../hooks/useEvolutionSocket', () => ({
  useEvolutionSocket: () => mockEvolutionState,
  initialState: mockInitialState,
}))

vi.mock('../hooks/useRunResults', () => ({
  useRunResults: () => mockRunResults,
}))

// Mock SDK function used by useQuery in the component
vi.mock('../client/sdk.gen', () => ({
  getRunStatusApiEvolutionRunIdStatusGet: vi.fn().mockResolvedValue({ data: null }),
}))

// --- Mock child components to avoid import cascades ---
vi.mock('../components/evolution/FitnessChart', () => ({
  default: () => <div data-testid="fitness-chart">FitnessChart</div>,
}))
vi.mock('../components/evolution/IslandsView', () => ({
  default: () => <div data-testid="islands-view">IslandsView</div>,
}))
vi.mock('../components/evolution/GenerationTable', () => ({
  default: () => <div data-testid="generation-table">GenerationTable</div>,
}))
vi.mock('../components/evolution/PhyloTree', () => ({
  default: () => <div data-testid="phylo-tree">PhyloTree</div>,
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
vi.mock('../components/evolution/Islands3D', () => ({
  default: () => <div data-testid="islands-3d">Islands3D</div>,
}))
vi.mock('../components/evolution/Lineage3D', () => ({
  default: () => <div data-testid="lineage-3d">Lineage3D</div>,
}))

// --- Mock SummaryCards to inspect props ---
vi.mock('../components/evolution/SummaryCards', () => ({
  default: ({ data }: { data: SummaryData }) => (
    <div data-testid="summary-cards" data-seed-fitness={data.seedFitness}>
      SummaryCards
    </div>
  ),
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
  vi.clearAllMocks()
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
  it('shows live overview without tabs when status is running', () => {
    // Set up running state
    Object.assign(mockEvolutionState, {
      ...mockInitialState,
      status: 'running',
      summary: { ...mockInitialState.summary },
    })
    mockRunResults.data = null

    renderWithProviders(<EvolutionDashboard runId="test-run-1" />)

    // SummaryCards and FitnessChart should be present
    expect(screen.getByTestId('summary-cards')).toBeInTheDocument()
    expect(screen.getByTestId('fitness-chart')).toBeInTheDocument()

    // No segmented button group should be rendered (no sub-nav in live view)
    expect(screen.queryByText('Lineage')).not.toBeInTheDocument()
    expect(screen.queryByText('Prompt Diffs')).not.toBeInTheDocument()
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

    // Segmented button group should be rendered with expected buttons
    expect(screen.getByText('Overview')).toBeInTheDocument()
    expect(screen.getByText('Prompt Diffs')).toBeInTheDocument()
    expect(screen.getByText('Mutation Stats')).toBeInTheDocument()
    expect(screen.getByText('Case Results')).toBeInTheDocument()
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

    // SummaryCards should receive seedFitness derived from seed events
    // The best seed fitness is max(-3.5, -2.0) = -2.0
    const summaryCards = screen.getByTestId('summary-cards')
    expect(summaryCards).toBeInTheDocument()
    expect(summaryCards.getAttribute('data-seed-fitness')).toBe('-2')
  })
})
