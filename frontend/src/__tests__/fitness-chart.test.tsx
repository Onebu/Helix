import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import FitnessChart from '../components/evolution/FitnessChart'
import type { GenerationData } from '../types/evolution'

vi.mock('recharts', () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => <div data-testid="chart-container">{children}</div>,
  LineChart: ({ children, data }: { children: React.ReactNode; data?: unknown[] }) => <div data-testid="line-chart" data-point-count={data?.length}>{children}</div>,
  Line: ({ name }: { name: string }) => <div data-testid={`line-${name}`}>{name}</div>,
  XAxis: () => null,
  YAxis: ({ domain }: { domain?: [number, number] }) => <div data-testid="y-axis" data-domain={JSON.stringify(domain)} />,
  CartesianGrid: () => null,
  Tooltip: () => null,
  Legend: () => null,
  ReferenceLine: ({ y, label }: { y: number; label?: { position?: string; offset?: number } }) => (
    <div
      data-testid="reference-line"
      data-y={y}
      data-label-position={label?.position}
      data-label-offset={label?.offset}
    >
      Zero Line
    </div>
  ),
}))

const sampleGenerations: GenerationData[] = [
  { generation: 0, label: 'Seed', bestFitness: 0.5, avgFitness: 0.3, bestNormalized: -0.5, avgNormalized: -0.7, candidatesEvaluated: 4, costUsd: 0.01 },
  { generation: 1, label: 'Gen 1', bestFitness: 0.7, avgFitness: 0.5, bestNormalized: -0.3, avgNormalized: -0.5, candidatesEvaluated: 8, costUsd: 0.02 },
  { generation: 2, label: 'Gen 2', bestFitness: 0.9, avgFitness: 0.7, bestNormalized: -0.1, avgNormalized: -0.3, candidatesEvaluated: 8, costUsd: 0.03 },
]

describe('FitnessChart', () => {
  it('renders "No data yet" message when generations array is empty', () => {
    render(<FitnessChart data={[]} />)
    expect(screen.getByText('No data yet')).toBeInTheDocument()
  })

  it('renders Recharts container when generations data is provided', () => {
    render(<FitnessChart data={sampleGenerations} />)
    expect(screen.getByTestId('chart-container')).toBeInTheDocument()
    expect(screen.getByTestId('line-chart')).toBeInTheDocument()
  })

  it('describes the start, best, and final full-suite fitness in text', () => {
    render(<FitnessChart data={sampleGenerations} />)

    const chart = screen.getByRole('figure', { name: 'Fitness Progression' })
    const summaryId = chart.getAttribute('aria-describedby')
    expect(summaryId).toBeTruthy()
    expect(document.getElementById(summaryId!)).toHaveTextContent(
      'Full-suite fitness: start 0.50, best 0.90, final 0.90.',
    )
  })

  it('renders both "Best Fitness" and "Avg Fitness" legend entries', () => {
    render(<FitnessChart data={sampleGenerations} />)
    expect(screen.getByTestId('line-Best Fitness')).toHaveTextContent('Best Fitness')
    expect(screen.getByTestId('line-Avg Fitness')).toHaveTextContent('Avg Fitness')
  })

  it('renders a ReferenceLine at y=0 for the perfect fitness baseline', () => {
    render(<FitnessChart data={sampleGenerations} />)
    const refLine = screen.getByTestId('reference-line')
    expect(refLine).toBeInTheDocument()
    expect(refLine).toHaveAttribute('data-y', '0')
  })

  it('keeps the perfect-baseline label inside the plot away from the right axis', () => {
    render(<FitnessChart data={sampleGenerations} />)
    const refLine = screen.getByTestId('reference-line')
    expect(refLine).toHaveAttribute('data-label-position', 'insideTopLeft')
    expect(refLine).toHaveAttribute('data-label-offset', '8')
  })

  it('filters out NaN data points before rendering', () => {
    const dataWithNaN: GenerationData[] = [
      { generation: 0, label: 'Seed', bestFitness: 0.5, avgFitness: 0.3, bestNormalized: -0.5, avgNormalized: -0.7, candidatesEvaluated: 4, costUsd: 0.01 },
      { generation: 1, label: 'Gen 1', bestFitness: NaN, avgFitness: 0.5, bestNormalized: -0.3, avgNormalized: -0.5, candidatesEvaluated: 8, costUsd: 0.02 },
      { generation: 2, label: 'Gen 2', bestFitness: 0.9, avgFitness: 0.7, bestNormalized: -0.1, avgNormalized: -0.3, candidatesEvaluated: 8, costUsd: 0.03 },
    ]
    render(<FitnessChart data={dataWithNaN} />)
    const chart = screen.getByTestId('line-chart')
    // NaN point should be filtered: 3 input -> 2 clean
    expect(chart).toHaveAttribute('data-point-count', '2')
  })

  it('filters out Infinity data points', () => {
    const dataWithInfinity: GenerationData[] = [
      { generation: 0, label: 'Seed', bestFitness: 0.5, avgFitness: Infinity, bestNormalized: -0.5, avgNormalized: -0.7, candidatesEvaluated: 4, costUsd: 0.01 },
      { generation: 1, label: 'Gen 1', bestFitness: 0.7, avgFitness: 0.5, bestNormalized: -0.3, avgNormalized: -0.5, candidatesEvaluated: 8, costUsd: 0.02 },
    ]
    render(<FitnessChart data={dataWithInfinity} />)
    const chart = screen.getByTestId('line-chart')
    expect(chart).toHaveAttribute('data-point-count', '1')
  })

  it('shows "No data yet" when all data points have NaN values', () => {
    const allNaN: GenerationData[] = [
      { generation: 0, label: 'Seed', bestFitness: NaN, avgFitness: NaN, bestNormalized: NaN, avgNormalized: NaN, candidatesEvaluated: 0, costUsd: 0 },
    ]
    render(<FitnessChart data={allNaN} />)
    expect(screen.getByText('No data yet')).toBeInTheDocument()
  })

  it('renders Best Normalized line when normalized data is finite', () => {
    render(<FitnessChart data={sampleGenerations} />)
    expect(screen.getByTestId('line-Best Norm.')).toBeInTheDocument()
  })

  it('hides Best Normalized line when all normalized values are non-finite', () => {
    const dataNoNormalized: GenerationData[] = [
      { generation: 0, label: 'Seed', bestFitness: 0.5, avgFitness: 0.3, bestNormalized: NaN, avgNormalized: NaN, candidatesEvaluated: 4, costUsd: 0.01 },
      { generation: 1, label: 'Gen 1', bestFitness: 0.7, avgFitness: 0.5, bestNormalized: Infinity, avgNormalized: NaN, candidatesEvaluated: 8, costUsd: 0.02 },
    ]
    render(<FitnessChart data={dataNoNormalized} />)
    expect(screen.queryByTestId('line-Best Norm.')).not.toBeInTheDocument()
  })
})
