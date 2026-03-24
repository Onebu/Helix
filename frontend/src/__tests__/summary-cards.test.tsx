import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import SummaryCards from '../components/evolution/SummaryCards'
import type { SummaryData } from '../types/evolution'

const sampleSummary: SummaryData = {
  bestFitness: 0.8765,
  bestNormalized: -0.12,
  seedFitness: 0.4321,
  improvementDelta: 0.4444,
  terminationReason: 'max_generations',
  lineageEventCount: 42,
  totalCostUsd: 1.2345,
  generationsCompleted: 5,
}

describe('SummaryCards', () => {
  it('renders all 6 card labels', () => {
    render(<SummaryCards data={sampleSummary} />)
    expect(screen.getByText('Best Fitness')).toBeInTheDocument()
    expect(screen.getByText('Seed Fitness')).toBeInTheDocument()
    expect(screen.getByText('Improvement')).toBeInTheDocument()
    expect(screen.getByText('Stop Reason')).toBeInTheDocument()
    expect(screen.getByText('Lineage Events')).toBeInTheDocument()
    expect(screen.getByText('Total Cost')).toBeInTheDocument()
  })

  it('displays formatted values (fitness to 2 decimal places, cost with $ prefix)', () => {
    render(<SummaryCards data={sampleSummary} />)
    expect(screen.getByText('0.88 (-0.12 norm)')).toBeInTheDocument()
    expect(screen.getByText('0.43')).toBeInTheDocument()
    expect(screen.getByText('+0.44')).toBeInTheDocument()
    expect(screen.getByText('$1.2345')).toBeInTheDocument()
    expect(screen.getByText('42')).toBeInTheDocument()
  })

  it('shows "Running..." when terminationReason is null', () => {
    const runningSummary: SummaryData = {
      ...sampleSummary,
      terminationReason: null,
    }
    render(<SummaryCards data={runningSummary} />)
    expect(screen.getByText('Running...')).toBeInTheDocument()
  })

  describe('null safety', () => {
    it('renders without crash when all nullable fields are null', () => {
      const nullSummary: SummaryData = {
        bestFitness: null,
        bestNormalized: null,
        seedFitness: null,
        improvementDelta: 0,
        terminationReason: null,
        lineageEventCount: 0,
        totalCostUsd: 0,
        generationsCompleted: 0,
      }
      render(<SummaryCards data={nullSummary} />)

      // All 6 cards render
      expect(screen.getByText('Best Fitness')).toBeInTheDocument()
      expect(screen.getByText('Seed Fitness')).toBeInTheDocument()
      expect(screen.getByText('Improvement')).toBeInTheDocument()
      expect(screen.getByText('Stop Reason')).toBeInTheDocument()
      expect(screen.getByText('Lineage Events')).toBeInTheDocument()
      expect(screen.getByText('Total Cost')).toBeInTheDocument()

      // Dashes for null fitness values
      const dashes = screen.getAllByText('\u2014')
      expect(dashes.length).toBeGreaterThanOrEqual(3) // Best Fitness, Seed Fitness, Improvement

      // Termination shows Running... when null
      expect(screen.getByText('Running...')).toBeInTheDocument()
    })

    it('suppresses NaN normalized score display', () => {
      const nanNormSummary: SummaryData = {
        bestFitness: 0.75,
        bestNormalized: NaN,
        seedFitness: -2.5,
        improvementDelta: 3.25,
        terminationReason: null,
        lineageEventCount: 5,
        totalCostUsd: 0.5,
        generationsCompleted: 2,
      }
      render(<SummaryCards data={nanNormSummary} />)

      // Best Fitness card shows the fitness value
      expect(screen.getByText(/0\.75/)).toBeInTheDocument()

      // NaN should NOT appear anywhere
      expect(screen.queryByText(/NaN/)).not.toBeInTheDocument()
    })

    it('handles seedFitness null with bestFitness present', () => {
      const partialSummary: SummaryData = {
        bestFitness: 0.5,
        bestNormalized: null,
        seedFitness: null,
        improvementDelta: 0,
        terminationReason: null,
        lineageEventCount: 1,
        totalCostUsd: 0.1,
        generationsCompleted: 1,
      }
      render(<SummaryCards data={partialSummary} />)

      // Improvement card shows dash (not crash from null arithmetic)
      // Best Fitness shows 0.50 (no progress %)
      expect(screen.getByText(/0\.50/)).toBeInTheDocument()

      // Seed Fitness shows dash
      const seedCard = screen.getByText('Seed Fitness').closest('div')
      expect(seedCard).toBeInTheDocument()

      // Improvement shows dash since seedFitness is null
      const improvementCard = screen.getByText('Improvement').closest('div')
      expect(improvementCard).toBeInTheDocument()
      // The improvement value is a dash
      expect(improvementCard?.parentElement?.textContent).toContain('\u2014')
    })
  })
})
