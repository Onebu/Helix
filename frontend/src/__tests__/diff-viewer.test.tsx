import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { LineageNode } from '../types/evolution'

// Mock the diff module
vi.mock('diff', () => ({
  createTwoFilesPatch: vi.fn(
    () =>
      '--- a\n+++ b\n@@ -1,3 +1,3 @@\n context line\n-old line\n+new line\n',
  ),
}))

const { default: DiffViewer } = await import(
  '../components/evolution/DiffViewer'
)

function makeWinningPathEvents(): LineageNode[] {
  return [
    {
      candidateId: 'seed-001',
      parentIds: [],
      generation: 0,
      island: 0,
      fitnessScore: 0.2,
      normalizedScore: 0,
      rejected: false,
      mutationType: 'seed',
      survived: true,
      template: 'You are a helpful assistant.\nBe concise.\nAnswer questions.',
    },
    {
      candidateId: 'cand-002',
      parentIds: ['seed-001'],
      generation: 1,
      island: 0,
      fitnessScore: 0.6,
      normalizedScore: 0,
      rejected: false,
      mutationType: 'rcc',
      survived: true,
      template:
        'You are a helpful assistant.\nBe concise and accurate.\nAnswer questions thoroughly.',
    },
    {
      candidateId: 'cand-003',
      parentIds: ['cand-002'],
      generation: 2,
      island: 0,
      fitnessScore: 0.95,
      normalizedScore: 0,
      rejected: false,
      mutationType: 'structural',
      survived: true,
      template:
        'You are an expert assistant.\nBe concise and accurate.\nAnswer questions thoroughly and cite sources.',
    },
  ]
}

describe('DiffViewer', () => {
  it('renders one diff step per winning path transition (N-1 steps for N winning path nodes)', () => {
    const events = makeWinningPathEvents()
    render(<DiffViewer lineageEvents={events} bestCandidateId="cand-003" />)
    // 3 nodes on winning path -> 2 diff steps
    const steps = screen.getAllByText(/Step \d+/)
    expect(steps.length).toBe(2)
  })

  it('each step header shows candidate ID (short), fitness, and mutation badge', () => {
    const events = makeWinningPathEvents()
    render(<DiffViewer lineageEvents={events} bestCandidateId="cand-003" />)
    // Step 1: seed-001 -> cand-002
    expect(screen.getByText('cand-002')).toBeInTheDocument()
    expect(screen.getByText('0.600')).toBeInTheDocument()
    expect(screen.getByText('rcc')).toBeInTheDocument()
    // Step 2: cand-002 -> cand-003
    expect(screen.getByText('cand-003')).toBeInTheDocument()
    expect(screen.getByText('0.950')).toBeInTheDocument()
    expect(screen.getByText('structural')).toBeInTheDocument()
  })

  it('added lines are rendered with green color class', () => {
    const events = makeWinningPathEvents()
    const { container } = render(
      <DiffViewer lineageEvents={events} bestCandidateId="cand-003" />,
    )
    const addedLines = container.querySelectorAll('[data-diff-type="add"]')
    expect(addedLines.length).toBeGreaterThan(0)
    // Check that added lines have green text color class
    const firstAdded = addedLines[0] as HTMLElement
    expect(firstAdded.className).toMatch(/diff-add/)
  })

  it('deleted lines are rendered with red color class and line-through', () => {
    const events = makeWinningPathEvents()
    const { container } = render(
      <DiffViewer lineageEvents={events} bestCandidateId="cand-003" />,
    )
    const deletedLines = container.querySelectorAll('[data-diff-type="del"]')
    expect(deletedLines.length).toBeGreaterThan(0)
    const firstDeleted = deletedLines[0] as HTMLElement
    expect(firstDeleted.className).toMatch(/diff-del/)
    expect(firstDeleted.className).toMatch(/line-through/)
  })

  it('shows "No diff data available" when winning path has fewer than 2 nodes with templates', () => {
    // Only one node with a template
    const events: LineageNode[] = [
      {
        candidateId: 'solo',
        parentIds: [],
        generation: 0,
        island: 0,
        fitnessScore: 0.5,
        normalizedScore: 0,
        rejected: false,
        mutationType: 'seed',
        survived: true,
        template: 'some template',
      },
    ]
    render(<DiffViewer lineageEvents={events} bestCandidateId="solo" />)
    expect(screen.getByText('No diff data available')).toBeInTheDocument()
  })

  it('seed template (first step) is displayed as initial context', () => {
    const events = makeWinningPathEvents()
    render(<DiffViewer lineageEvents={events} bestCandidateId="cand-003" />)
    expect(screen.getByText('Initial Template')).toBeInTheDocument()
  })

  it('shows migration annotation when winning path crosses islands', () => {
    const events: LineageNode[] = [
      {
        candidateId: 'seed-orig',
        parentIds: [],
        generation: 0,
        island: 0,
        fitnessScore: -5.0,
        normalizedScore: 0,
        rejected: false,
        mutationType: 'seed',
        survived: true,
        template: 'Original seed template',
      },
      {
        candidateId: 'migrated-to-1',
        parentIds: ['seed-orig'],
        generation: 1,
        island: 1,
        fitnessScore: -2.0,
        normalizedScore: 0,
        rejected: false,
        mutationType: 'migrated',
        survived: true,
        template: 'Migrated template on island 1',
      },
    ]
    render(<DiffViewer lineageEvents={events} bestCandidateId="migrated-to-1" />)
    expect(screen.getByText(/Migrated from Island 0/)).toBeInTheDocument()
    expect(screen.getByText(/Island 1/)).toBeInTheDocument()
  })

  it('does not show migration annotation for same-island diff steps', () => {
    const events = makeWinningPathEvents() // all island 0
    const { container } = render(
      <DiffViewer lineageEvents={events} bestCandidateId="cand-003" />,
    )
    // No migration annotations should exist
    const migrationAnnotations = container.querySelectorAll('.text-mutation-fresh')
    expect(migrationAnnotations.length).toBe(0)
  })
})
