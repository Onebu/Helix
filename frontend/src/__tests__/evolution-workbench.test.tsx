import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { EvolutionState, RunResults } from '@/types/evolution'

const { evolutionState, runResults, mockAcceptVersion } = vi.hoisted(() => ({
  evolutionState: {
    status: 'complete',
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
  } as EvolutionState,
  runResults: {
    promptId: 'prompt-1',
    lineageEvents: [
      {
        candidateId: 'seed-1',
        parentIds: [],
        generation: 0,
        island: 0,
        fitnessScore: -4,
        normalizedScore: 0.5,
        rejected: false,
        mutationType: 'seed',
        survived: true,
        template: 'Original prompt',
      },
      {
        candidateId: 'parent-2',
        parentIds: ['seed-1'],
        generation: 1,
        island: 1,
        fitnessScore: -2,
        normalizedScore: 0.75,
        rejected: false,
        mutationType: 'rcc',
        survived: true,
        template: 'Second parent prompt',
      },
      {
        candidateId: 'child-1',
        parentIds: ['seed-1', 'parent-2'],
        generation: 2,
        island: 1,
        fitnessScore: -1,
        normalizedScore: 0.9,
        rejected: false,
        mutationType: 'rcc',
        survived: true,
        template: 'Improved prompt',
      },
    ],
    caseResults: Array.from({ length: 12 }, (_, index) => ({
      caseId: `case-${index}`,
      tier: 'normal',
      score: index < 11 ? 0 : -1,
      passed: index < 11,
      reason: '',
    })),
    seedCaseResults: Array.from({ length: 12 }, (_, index) => ({
      caseId: `case-${index}`,
      tier: 'normal',
      score: 0,
      passed: true,
      reason: '',
    })),
    generationRecords: [],
    bestCandidateId: 'child-1',
    bestTemplate: 'Improved prompt',
    totalCostUsd: 1.25,
    bestFitnessScore: -1,
    bestNormalizedScore: 0.9,
    generationsCompleted: 3,
    terminationReason: 'generations_complete',
    metaModel: 'meta-model',
    targetModel: 'target-model',
    judgeModel: 'judge-model',
    metaProvider: 'provider',
    targetProvider: 'provider',
    judgeProvider: 'provider',
    hyperparameters: { n_islands: 2 },
  } as RunResults,
  mockAcceptVersion: vi.fn(),
}))

vi.mock('@/hooks/useEvolutionSocket', () => ({
  useEvolutionSocket: () => evolutionState,
}))

vi.mock('@/hooks/useRunResults', () => ({
  useRunResults: () => ({ data: runResults, loading: false, error: null }),
}))

vi.mock('@/client/sdk.gen', () => ({
  getRunStatusApiEvolutionRunIdStatusGet: vi.fn().mockResolvedValue({ data: null }),
  acceptVersionApiPromptsPromptIdVersionsAcceptPost: mockAcceptVersion,
  listCasesApiPromptsPromptIdDatasetGet: vi.fn().mockResolvedValue({ data: [] }),
}))

vi.mock('@/components/evolution/FitnessChart', () => ({
  default: () => <div data-testid="fitness-chart">Fitness chart</div>,
}))
vi.mock('@/components/evolution/GenerationTable', () => ({
  default: () => <div data-testid="generation-table">Generation table</div>,
}))
vi.mock('@/components/evolution/IslandsSummary', () => ({
  default: () => <div data-testid="islands-summary">Islands summary</div>,
}))
vi.mock('@/components/evolution/LineageGraph', () => ({
  default: ({ lineageEvents, onSelect }: {
    lineageEvents: Array<{ candidateId: string }>
    onSelect?: (candidateId: string) => void
  }) => (
    <div data-testid="lineage-graph">
      {lineageEvents.map((candidate) => (
        <button
          key={candidate.candidateId}
          type="button"
          aria-label={`Candidate ${candidate.candidateId}`}
          onClick={() => onSelect?.(candidate.candidateId)}
        >
          {candidate.candidateId}
        </button>
      ))}
    </div>
  ),
}))
vi.mock('@/components/evolution/CaseResultsGrid', () => ({
  default: () => <div data-testid="case-results">Case results</div>,
}))

import EvolutionDashboard from '@/components/evolution/EvolutionDashboard'

function renderDashboard() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <EvolutionDashboard runId="run-1" />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function setDesktopInspector(matches: boolean) {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query === '(min-width: 1280px)' ? matches : false,
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }))
}

describe('Evolution workbench', () => {
  beforeEach(() => {
    setDesktopInspector(true)
    mockAcceptVersion.mockReset()
    mockAcceptVersion.mockResolvedValue({ data: { version: 2 } })
  })

  it('renders one workspace tab set and selects the completed run winner', () => {
    renderDashboard()

    expect(screen.getByRole('tab', { name: 'Progress' })).toBeVisible()
    expect(screen.getByRole('tab', { name: 'Lineage' })).toBeVisible()
    expect(screen.getByRole('tab', { name: 'Cases' })).toBeVisible()

    const header = screen.getByRole('banner')
    expect(within(header).getByRole('button', { name: 'Accept as new version' })).toBeVisible()
    expect(within(header).getByText('Full evaluations')).toBeVisible()
    expect(within(header).getAllByText('3')).toHaveLength(2)

    const inspector = screen.getByRole('complementary', { name: 'Candidate inspector' })
    expect(within(inspector).getByText('child-1')).toBeVisible()
    expect(within(inspector).getByText('11 / 12')).toBeVisible()
    expect(within(inspector).getByText('2 parents')).toBeVisible()
  })

  it('updates inspector evidence when a lineage candidate is selected', async () => {
    const user = userEvent.setup()
    renderDashboard()

    await user.click(screen.getByRole('tab', { name: 'Lineage' }))
    await user.click(screen.getByRole('button', { name: /candidate seed-1/i }))

    const inspector = screen.getByRole('complementary', { name: 'Candidate inspector' })
    expect(within(inspector).getByText('seed-1')).toBeVisible()
    expect(within(inspector).getByText('12 / 12')).toBeVisible()
    expect(within(inspector).getByText('0 parents')).toBeVisible()
  })

  it('does not invent stored coverage for non-best evolved candidates', async () => {
    const user = userEvent.setup()
    renderDashboard()

    await user.click(screen.getByRole('tab', { name: 'Lineage' }))
    await user.click(screen.getByRole('button', { name: /candidate parent-2/i }))

    const inspector = screen.getByRole('complementary', { name: 'Candidate inspector' })
    expect(within(inspector).getByText('Not available')).toBeVisible()
    expect(within(inspector).getByText('1 parent')).toBeVisible()
  })

  it('keeps progress evidence together without the old overview navigation', () => {
    renderDashboard()

    expect(screen.getByTestId('fitness-chart')).toBeVisible()
    expect(screen.getByTestId('islands-summary')).toBeVisible()
    expect(screen.getByTestId('generation-table')).toBeVisible()
    expect(screen.queryByRole('tab', { name: 'Overview' })).not.toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'Winning Path' })).not.toBeInTheDocument()
  })

  it('keeps workspace tabs scrollable and actions visible without hover', () => {
    const { container } = renderDashboard()

    expect(screen.getByRole('tablist')).toHaveClass('overflow-x-auto', 'whitespace-nowrap')
    expect(container.querySelector('[class*="opacity-0"], [class*="group-hover"]')).toBeNull()
  })

  it('accepts through the throwing SDK mode and reports the stored version', async () => {
    const user = userEvent.setup()
    renderDashboard()

    await user.click(screen.getByRole('button', { name: 'Accept as new version' }))

    await waitFor(() => expect(mockAcceptVersion).toHaveBeenCalledWith(
      expect.objectContaining({ throwOnError: true }),
    ))
    expect(await screen.findByText('Accepted as v2')).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Accept as new version' })).not.toBeInTheDocument()
  })

  it('keeps acceptance available after an API error', async () => {
    const user = userEvent.setup()
    mockAcceptVersion.mockRejectedValueOnce(new Error('Version rejected'))
    renderDashboard()

    await user.click(screen.getByRole('button', { name: 'Accept as new version' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Version rejected')
    expect(screen.getByRole('button', { name: 'Accept as new version' })).toBeVisible()
    expect(screen.queryByText(/Accepted as v-1/)).not.toBeInTheDocument()
  })

  it('opens selected candidate in a labelled sheet on compact layouts', async () => {
    const user = userEvent.setup()
    setDesktopInspector(false)
    renderDashboard()

    expect(screen.queryByRole('dialog', { name: 'Candidate inspector' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('tab', { name: 'Lineage' }))
    const childButton = screen.getByRole('button', { name: /candidate child-1/i })
    await user.click(childButton)

    const dialog = screen.getByRole('dialog', { name: 'Candidate inspector' })
    expect(within(dialog).getByText('11 / 12')).toBeVisible()
    expect(within(dialog).getByText('2 parents')).toBeVisible()
    expect(document.querySelector('.fixed.inset-0.z-50')).toHaveClass('motion-reduce:animate-none')
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog', { name: 'Candidate inspector' })).not.toBeInTheDocument()
    expect(childButton).toHaveFocus()
  })
})
