import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import GenerationTable from '../components/evolution/GenerationTable'
import type { GenerationData } from '../types/evolution'

const sampleGenerations: GenerationData[] = [
  { generation: 0, label: 'Seed', bestFitness: 0.5, avgFitness: 0.3, bestNormalized: -0.5, avgNormalized: -0.7, candidatesEvaluated: 4, costUsd: 0.01 },
  { generation: 1, label: 'Gen 1', bestFitness: 0.7, avgFitness: 0.5, bestNormalized: -0.3, avgNormalized: -0.5, candidatesEvaluated: 8, costUsd: 0.02 },
  { generation: 2, label: 'Gen 2', bestFitness: 0.9, avgFitness: 0.7, bestNormalized: -0.1, avgNormalized: -0.3, candidatesEvaluated: 8, costUsd: 0.03 },
]

describe('GenerationTable', () => {
  it('renders table headers (Generation, Best Fitness, Avg Fitness, Candidates)', () => {
    render(<GenerationTable data={sampleGenerations} />)
    expect(screen.getByText('Generation')).toBeInTheDocument()
    expect(screen.getByText('Best Fitness')).toBeInTheDocument()
    expect(screen.getByText('Avg Fitness')).toBeInTheDocument()
    expect(screen.getByText('Candidates')).toBeInTheDocument()
  })

  it('renders correct number of rows matching generations data', () => {
    render(<GenerationTable data={sampleGenerations} />)
    // 3 data rows (one per generation)
    const rows = screen.getAllByRole('row')
    // 1 header row + 3 data rows = 4
    expect(rows).toHaveLength(4)
    // Check specific cell values
    expect(screen.getByText('Seed')).toBeInTheDocument()
    expect(screen.getByText('Gen 1')).toBeInTheDocument()
    expect(screen.getByText('Gen 2')).toBeInTheDocument()
  })

  it('shows "Waiting for data..." when generations array is empty', () => {
    render(<GenerationTable data={[]} />)
    expect(screen.getByText('Waiting for data...')).toBeInTheDocument()
  })

  it('preserves the accessible full value of long generation labels', () => {
    const longLabel = 'Generation with an unusually long imported identifier'
    render(<GenerationTable data={[{ ...sampleGenerations[0], label: longLabel }]} />)

    expect(screen.getByTitle(longLabel)).toHaveTextContent(longLabel)
  })
})
