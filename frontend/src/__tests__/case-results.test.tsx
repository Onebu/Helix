import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import type { CaseResultData } from '../types/evolution'

vi.mock('../lib/scoring', () => ({
  scoreColor: (score: number) =>
    score === 0 ? '#22c55e' : score > -1 ? '#f59e0b' : '#ef4444',
}))

import CaseResultsGrid from '../components/evolution/CaseResultsGrid'

// --- Helper factory ---
function makeCase(overrides: Partial<CaseResultData> = {}): CaseResultData {
  return {
    caseId: 'test-case-1',
    tier: 'normal',
    score: 0.85,
    passed: true,
    reason: 'Matched expected output',
    expected: { tool_name: 'transfer', args: { destination: '100' } },
    actualContent: 'Transferring you now',
    actualToolCalls: [{ name: 'transfer', arguments: { destination: '100' } }],
    ...overrides,
  }
}

describe('CaseResultsGrid', () => {
  it('renders a row for each case result with case_id, tier, pass/fail, score, and reason', () => {
    const cases: CaseResultData[] = [
      makeCase({ caseId: 'case-alpha', tier: 'critical', passed: false, score: 0.2, reason: 'Missing tool call' }),
      makeCase({ caseId: 'case-beta', tier: 'normal', passed: true, score: 0.9, reason: 'Matched' }),
    ]
    render(<CaseResultsGrid caseResults={cases} />)
    expect(screen.getByText('case-alpha')).toBeInTheDocument()
    expect(screen.getByText('case-beta')).toBeInTheDocument()
    expect(screen.getByText('critical')).toBeInTheDocument()
    expect(screen.getByText('0.200')).toBeInTheDocument()
    expect(screen.getByText('0.900')).toBeInTheDocument()
  })

  it('colors tier badges: critical=red, normal=blue, low=slate', () => {
    const cases: CaseResultData[] = [
      makeCase({ caseId: 'c1', tier: 'critical' }),
      makeCase({ caseId: 'c2', tier: 'normal' }),
      makeCase({ caseId: 'c3', tier: 'low' }),
    ]
    render(<CaseResultsGrid caseResults={cases} />)
    const criticalBadge = screen.getByText('critical')
    const normalBadge = screen.getByText('normal')
    const lowBadge = screen.getByText('low')
    expect(criticalBadge.className).toContain('text-red')
    expect(normalBadge.className).toContain('text-blue')
    expect(lowBadge.className).toContain('text-slate')
  })

  it('expands a row when clicked to show expected vs actual', () => {
    const cases: CaseResultData[] = [
      makeCase({
        caseId: 'expand-me',
        expected: { tool: 'transfer' },
        actualContent: 'Here is the response',
      }),
    ]
    render(<CaseResultsGrid caseResults={cases} />)
    // Click the row to expand
    fireEvent.click(screen.getByText('expand-me'))
    // Should show expected and actual sections
    expect(screen.getByText('Expected')).toBeInTheDocument()
    expect(screen.getByText('Actual')).toBeInTheDocument()
    expect(screen.getByText(/"tool"/)).toBeInTheDocument()
    expect(screen.getByText(/Here is the response/)).toBeInTheDocument()
  })

  it('collapses an expanded row when clicked again', () => {
    const cases: CaseResultData[] = [
      makeCase({ caseId: 'toggle-me', expected: { tool: 'transfer' } }),
    ]
    render(<CaseResultsGrid caseResults={cases} />)
    fireEvent.click(screen.getByText('toggle-me'))
    expect(screen.getByText('Expected')).toBeInTheDocument()
    // Click again to collapse
    fireEvent.click(screen.getByText('toggle-me'))
    expect(screen.queryByText('Expected')).not.toBeInTheDocument()
  })

  it('shows "No case results" when caseResults array is empty', () => {
    render(<CaseResultsGrid caseResults={[]} />)
    expect(screen.getByText('No case results')).toBeInTheDocument()
  })

  it('shows green checkmark for passed, red X for failed', () => {
    const cases: CaseResultData[] = [
      makeCase({ caseId: 'pass-case', passed: true }),
      makeCase({ caseId: 'fail-case', passed: false }),
    ]
    render(<CaseResultsGrid caseResults={cases} />)
    const passIcon = screen.getByTestId('result-pass-pass-case')
    const failIcon = screen.getByTestId('result-fail-fail-case')
    expect(passIcon).toBeInTheDocument()
    expect(failIcon).toBeInTheDocument()
  })

  it('renders behavior criteria breakdown when criteriaResults present', () => {
    const cases: CaseResultData[] = [
      makeCase({
        caseId: 'criteria-case',
        criteriaResults: [
          { criterion: 'greets in Spanish', passed: true, reason: 'Greeting detected' },
          { criterion: 'confirms department', passed: true, reason: 'Department confirmed' },
          { criterion: 'transfers correctly', passed: false, reason: 'Wrong destination' },
        ],
      }),
    ]
    render(<CaseResultsGrid caseResults={cases} />)
    fireEvent.click(screen.getByText('criteria-case'))
    expect(screen.getByText('Behavior Criteria')).toBeInTheDocument()
    expect(screen.getByText(/greets in Spanish/)).toBeInTheDocument()
    expect(screen.getByText(/confirms department/)).toBeInTheDocument()
    expect(screen.getByText(/transfers correctly/)).toBeInTheDocument()
    expect(screen.getByText(/Wrong destination/)).toBeInTheDocument()
  })

  it('does not render criteria section when criteriaResults is null', () => {
    const cases: CaseResultData[] = [
      makeCase({ caseId: 'no-criteria' }),
    ]
    render(<CaseResultsGrid caseResults={cases} />)
    fireEvent.click(screen.getByText('no-criteria'))
    expect(screen.queryByText('Behavior Criteria')).not.toBeInTheDocument()
  })

  it('shows correct pass/fail icons for criteria', () => {
    const cases: CaseResultData[] = [
      makeCase({
        caseId: 'icon-case',
        criteriaResults: [
          { criterion: 'passed criterion', passed: true, reason: 'OK' },
          { criterion: 'failed criterion', passed: false, reason: 'Not OK' },
        ],
      }),
    ]
    render(<CaseResultsGrid caseResults={cases} />)
    fireEvent.click(screen.getByText('icon-case'))
    // Check for unicode checkmark and cross
    expect(screen.getByText('\u2713')).toBeInTheDocument()
    expect(screen.getByText('\u2717')).toBeInTheDocument()
  })

  it('shows summary stats bar with pass/fail counts', () => {
    const cases: CaseResultData[] = [
      makeCase({ caseId: 'c1', passed: true }),
      makeCase({ caseId: 'c2', passed: true }),
      makeCase({ caseId: 'c3', passed: false }),
    ]
    render(<CaseResultsGrid caseResults={cases} />)
    expect(screen.getByText(/2 passed/i)).toBeInTheDocument()
    expect(screen.getByText(/1 failed/i)).toBeInTheDocument()
  })

  it('displays test case name instead of UUID when caseNames map is provided', () => {
    const uuid = '550e8400-e29b-41d4-a716-446655440000'
    const cases: CaseResultData[] = [makeCase({ caseId: uuid, tier: 'normal', passed: true })]
    const caseNames = new Map([[uuid, 'My Friendly Test Name']])
    render(<CaseResultsGrid caseResults={cases} caseNames={caseNames} />)
    expect(screen.getByText('My Friendly Test Name')).toBeInTheDocument()
    expect(screen.queryByText(uuid)).not.toBeInTheDocument()
  })

  it('falls back to caseId when no caseNames provided', () => {
    const uuid = '550e8400-e29b-41d4-a716-446655440000'
    const cases: CaseResultData[] = [makeCase({ caseId: uuid, tier: 'normal', passed: true })]
    render(<CaseResultsGrid caseResults={cases} />)
    expect(screen.getByText(uuid)).toBeInTheDocument()
  })

  it('adds title attribute with full reason text to reason cell', () => {
    const longReason = 'This is a very long reason that definitely exceeds the fifty character truncation limit used in the display'
    const cases: CaseResultData[] = [makeCase({ caseId: 'reason-case', reason: longReason })]
    render(<CaseResultsGrid caseResults={cases} />)
    const row = screen.getByText('reason-case').closest('tr')
    const reasonCell = row?.querySelector('td:last-child')
    expect(reasonCell).toHaveAttribute('title', longReason)
  })
})
