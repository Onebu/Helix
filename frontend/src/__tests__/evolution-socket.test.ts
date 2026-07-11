import { describe, it, expect } from 'vitest'
import { evolutionReducer, initialState } from '../hooks/useEvolutionSocket'
import type {
  EvolutionState,
  CandidateEvaluatedData,
  GenerationCompleteData,
  EvolutionCompleteData,
  MigrationEventData,
} from '../types/evolution'

describe('evolutionReducer', () => {
  it('Test 1: initialState has status idle, empty arrays, zeroed summary', () => {
    expect(initialState.status).toBe('idle')
    expect(initialState.generations).toEqual([])
    expect(initialState.candidates).toEqual([])
    expect(initialState.migrations).toEqual([])
    expect(initialState.summary).toEqual({
      bestFitness: null,
      bestNormalized: null,
      seedFitness: null,
      improvementDelta: 0,
      terminationReason: null,
      lineageEventCount: 0,
      totalCostUsd: 0,
      generationsCompleted: 0,
    })
  })

  it('Test 2: generation_complete appends to generations array with correct label (1-indexed)', () => {
    // Backend now sends generation: 1 for the first generation (1-indexed)
    const data: GenerationCompleteData = {
      generation: 1,
      best_fitness: 0.5,
      avg_fitness: 0.3,
      best_normalized: -0.5,
      avg_normalized: -0.7,
      candidates_evaluated: 4,
      cost_usd: 0.12,
    }

    const state1 = evolutionReducer(initialState, {
      type: 'generation_complete',
      data,
    })

    expect(state1.generations).toHaveLength(1)
    expect(state1.generations[0]).toEqual({
      generation: 1,
      label: '1',
      bestFitness: 0.5,
      avgFitness: 0.3,
      bestNormalized: -0.5,
      avgNormalized: -0.7,
      candidatesEvaluated: 4,
      costUsd: 0.12,
    })
    expect(state1.summary.generationsCompleted).toBe(1)

    // Second generation
    const data2: GenerationCompleteData = {
      generation: 2,
      best_fitness: 0.7,
      avg_fitness: 0.5,
      best_normalized: -0.3,
      avg_normalized: -0.5,
      candidates_evaluated: 6,
      cost_usd: 0.15,
    }

    const state2 = evolutionReducer(state1, {
      type: 'generation_complete',
      data: data2,
    })

    expect(state2.generations).toHaveLength(2)
    expect(state2.generations[1].label).toBe('2')
    expect(state2.summary.generationsCompleted).toBe(2)

    // Third generation
    const data3: GenerationCompleteData = {
      generation: 3,
      best_fitness: 0.85,
      avg_fitness: 0.6,
      best_normalized: -0.15,
      avg_normalized: -0.4,
      candidates_evaluated: 8,
      cost_usd: 0.2,
    }

    const state3 = evolutionReducer(state2, {
      type: 'generation_complete',
      data: data3,
    })

    expect(state3.generations).toHaveLength(3)
    expect(state3.generations[2].label).toBe('3')
    expect(state3.summary.generationsCompleted).toBe(3)
  })

  it('Test 3: candidate_evaluated appends to candidates array (capped at 500)', () => {
    const makeCandidate = (i: number): CandidateEvaluatedData => ({
      generation: 1,
      candidate_id: `cand-${i}`,
      fitness_score: 0.5,
      normalized_score: -0.5,
      rejected: false,
      mutation_type: 'rcc',
      island: 0,
      parent_ids: ['parent-1', 'parent-2'],
      template: `candidate ${i}`,
      cases_passed: 11,
      total_cases: 12,
    })

    // Add single candidate
    const state1 = evolutionReducer(initialState, {
      type: 'candidate_evaluated',
      data: makeCandidate(0),
    })
    expect(state1.candidates).toHaveLength(1)
    expect(state1.candidates[0].candidateId).toBe('cand-0')
    expect(state1.candidates[0]).toMatchObject({
      parentIds: ['parent-1', 'parent-2'],
      template: 'candidate 0',
      casesPassed: 11,
      totalCases: 12,
    })

    // Fill to 500 candidates
    let state = initialState
    for (let i = 0; i < 500; i++) {
      state = evolutionReducer(state, {
        type: 'candidate_evaluated',
        data: makeCandidate(i),
      })
    }
    expect(state.candidates).toHaveLength(500)

    // Add one more -- should still be 500, oldest dropped
    state = evolutionReducer(state, {
      type: 'candidate_evaluated',
      data: makeCandidate(500),
    })
    expect(state.candidates).toHaveLength(500)
    expect(state.candidates[0].candidateId).toBe('cand-1')
    expect(state.candidates[499].candidateId).toBe('cand-500')
  })

  it('Test 4: evolution_complete sets status to complete and updates summary', () => {
    const data: EvolutionCompleteData = {
      termination_reason: 'max_generations',
      best_fitness: 0.95,
      total_cost_usd: 1.23,
      generations_completed: 5,
    }

    const running: EvolutionState = {
      ...initialState,
      status: 'running',
      summary: {
        ...initialState.summary,
        seedFitness: 0.3,
      },
    }

    const state = evolutionReducer(running, {
      type: 'evolution_complete',
      data,
    })

    expect(state.status).toBe('complete')
    expect(state.summary.terminationReason).toBe('max_generations')
    expect(state.summary.bestFitness).toBe(0.95)
    expect(state.summary.totalCostUsd).toBe(1.23)
    expect(state.summary.generationsCompleted).toBe(5)
  })

  it.each([
    ['error', 'failed'],
    ['cancelled', 'cancelled'],
    ['budget_exhausted', 'budget_exhausted'],
  ] as const)('maps terminal reason %s to status %s', (terminationReason, status) => {
    const state = evolutionReducer(
      { ...initialState, status: 'running' },
      {
        type: 'evolution_complete',
        data: {
          termination_reason: terminationReason,
        },
      },
    )

    expect(state.status).toBe(status)
  })

  it('Test 5: tracks seedFitness from first candidate_evaluated with generation=0', () => {
    const seedCandidate: CandidateEvaluatedData = {
      generation: 0,
      candidate_id: 'seed-1',
      fitness_score: 0.4,
      normalized_score: -0.6,
      rejected: false,
      mutation_type: 'seed',
      island: 0,
    }

    const state = evolutionReducer(initialState, {
      type: 'candidate_evaluated',
      data: seedCandidate,
    })

    expect(state.summary.seedFitness).toBe(0.4)

    // Second seed candidate should update seedFitness if better (Math.max)
    const secondSeed: CandidateEvaluatedData = {
      ...seedCandidate,
      candidate_id: 'seed-2',
      fitness_score: 0.6,
      normalized_score: -0.4,
    }

    const state2 = evolutionReducer(state, {
      type: 'candidate_evaluated',
      data: secondSeed,
    })

    expect(state2.summary.seedFitness).toBe(0.6)

    // Non-seed candidate at gen 0 should NOT set seedFitness
    const nonSeed: CandidateEvaluatedData = {
      generation: 0,
      candidate_id: 'rcc-1',
      fitness_score: 0.9,
      normalized_score: -0.1,
      rejected: false,
      mutation_type: 'rcc',
      island: 0,
    }

    const state3 = evolutionReducer(state2, {
      type: 'candidate_evaluated',
      data: nonSeed,
    })

    // seedFitness stays at 0.6 (best seed), not updated by rcc candidate
    expect(state3.summary.seedFitness).toBe(0.6)
  })

  it('Test 6: computes improvementDelta as bestFitness - seedFitness', () => {
    // Set seed fitness via candidate_evaluated gen 0
    let state = evolutionReducer(initialState, {
      type: 'candidate_evaluated',
      data: {
        generation: 0,
        candidate_id: 'seed-1',
        fitness_score: 0.3,
        normalized_score: -0.7,
        rejected: false,
        mutation_type: 'seed',
        island: 0,
      },
    })

    expect(state.summary.seedFitness).toBe(0.3)
    expect(state.summary.bestFitness).toBe(0.3)
    expect(state.summary.improvementDelta).toBe(0)

    // Better candidate in gen 1
    state = evolutionReducer(state, {
      type: 'candidate_evaluated',
      data: {
        generation: 1,
        candidate_id: 'gen1-1',
        fitness_score: 0.8,
        normalized_score: -0.2,
        rejected: false,
        mutation_type: 'rcc',
        island: 0,
      },
    })

    expect(state.summary.bestFitness).toBe(0.8)
    expect(state.summary.improvementDelta).toBeCloseTo(0.5)
  })

  it('Test 7: increments lineageEventCount on each candidate_evaluated', () => {
    const candidate: CandidateEvaluatedData = {
      generation: 1,
      candidate_id: 'c1',
      fitness_score: 0.5,
      normalized_score: -0.5,
      rejected: false,
      mutation_type: 'rcc',
      island: 0,
    }

    let state = initialState
    for (let i = 0; i < 5; i++) {
      state = evolutionReducer(state, {
        type: 'candidate_evaluated',
        data: { ...candidate, candidate_id: `c${i}` },
      })
    }

    expect(state.summary.lineageEventCount).toBe(5)
  })

  it('Test 8: accumulates totalCostUsd from generation_complete events', () => {
    let state = initialState

    state = evolutionReducer(state, {
      type: 'generation_complete',
      data: {
        generation: 1,
        best_fitness: 0.3,
        avg_fitness: 0.2,
        best_normalized: -0.7,
        avg_normalized: -0.8,
        candidates_evaluated: 4,
        cost_usd: 0.10,
      },
    })

    expect(state.summary.totalCostUsd).toBeCloseTo(0.10)

    state = evolutionReducer(state, {
      type: 'generation_complete',
      data: {
        generation: 2,
        best_fitness: 0.5,
        avg_fitness: 0.4,
        best_normalized: -0.5,
        avg_normalized: -0.6,
        candidates_evaluated: 6,
        cost_usd: 0.25,
      },
    })

    expect(state.summary.totalCostUsd).toBeCloseTo(0.35)

    state = evolutionReducer(state, {
      type: 'generation_complete',
      data: {
        generation: 3,
        best_fitness: 0.7,
        avg_fitness: 0.55,
        best_normalized: -0.3,
        avg_normalized: -0.45,
        candidates_evaluated: 8,
        cost_usd: 0.30,
      },
    })

    expect(state.summary.totalCostUsd).toBeCloseTo(0.65)
  })

  it('Test 9: migration events append to migrations array', () => {
    const migration: MigrationEventData = {
      generation: 2,
      emigrants_per_island: 1,
    }

    const state = evolutionReducer(initialState, {
      type: 'migration',
      data: migration,
    })

    expect(state.migrations).toHaveLength(1)
    expect(state.migrations[0].generation).toBe(2)
    expect(state.migrations[0].emigrantsPerIsland).toBe(1)
    expect(state.migrations[0].timestamp).toBeTruthy()

    // Add another
    const state2 = evolutionReducer(state, {
      type: 'migration',
      data: { generation: 4, emigrants_per_island: 2 },
    })

    expect(state2.migrations).toHaveLength(2)
    expect(state2.migrations[1].generation).toBe(4)
  })

  it('Test 10: reset action returns to initialState', () => {
    // Build up some state
    const state: EvolutionState = {
      ...initialState,
      status: 'running',
      generations: [
        {
          generation: 1,
          label: '1',
          bestFitness: 0.5,
          avgFitness: 0.3,
          bestNormalized: -0.5,
          avgNormalized: -0.7,
          candidatesEvaluated: 4,
          costUsd: 0.12,
        },
      ],
      candidates: [
        {
          candidateId: 'c1',
          generation: 0,
          fitnessScore: 0.5,
          normalizedScore: -0.5,
          rejected: false,
          mutationType: 'seed',
          island: 0,
        },
      ],
      migrations: [
        { generation: 1, emigrantsPerIsland: 1, timestamp: '2026-01-01T00:00:00Z' },
      ],
      summary: {
        bestFitness: 0.5,
        bestNormalized: -0.5,
        seedFitness: 0.3,
        improvementDelta: 0.2,
        terminationReason: null,
        lineageEventCount: 1,
        totalCostUsd: 0.12,
        generationsCompleted: 1,
      },
    }

    const resetState = evolutionReducer(state, { type: 'reset' })

    expect(resetState).toEqual(initialState)
  })

  it('ws_connecting sets status to connecting', () => {
    const state = evolutionReducer(initialState, { type: 'ws_connecting' })
    expect(state.status).toBe('connecting')
  })

  it('ws_connected sets status to running', () => {
    const connecting: EvolutionState = { ...initialState, status: 'connecting' }
    const state = evolutionReducer(connecting, { type: 'ws_connected' })
    expect(state.status).toBe('running')
  })

  it('ws_error sets status to error', () => {
    const state = evolutionReducer(initialState, {
      type: 'ws_error',
      error: 'Connection failed',
    })
    expect(state.status).toBe('error')
  })

  describe('NaN guard', () => {
    it('ignores NaN normalized_score in candidate_evaluated', () => {
      const state = evolutionReducer(initialState, {
        type: 'candidate_evaluated',
        data: {
          generation: 0,
          candidate_id: 'nan-test-1',
          fitness_score: 0.5,
          normalized_score: NaN,
          rejected: false,
          mutation_type: 'seed',
          island: 0,
        },
      })

      // bestNormalized should remain null, not become NaN
      expect(state.summary.bestNormalized).toBeNull()
    })

    it('ignores undefined normalized_score in candidate_evaluated', () => {
      const state = evolutionReducer(initialState, {
        type: 'candidate_evaluated',
        data: {
          generation: 0,
          candidate_id: 'undef-test-1',
          fitness_score: 0.5,
          normalized_score: undefined as unknown as number,
          rejected: false,
          mutation_type: 'seed',
          island: 0,
        },
      })

      // bestNormalized should remain null, not become undefined
      expect(state.summary.bestNormalized).toBeNull()
    })

    it('preserves valid bestNormalized when subsequent event has NaN', () => {
      // First dispatch with a valid normalized_score
      const state1 = evolutionReducer(initialState, {
        type: 'candidate_evaluated',
        data: {
          generation: 0,
          candidate_id: 'valid-1',
          fitness_score: 0.5,
          normalized_score: -0.5,
          rejected: false,
          mutation_type: 'seed',
          island: 0,
        },
      })

      expect(state1.summary.bestNormalized).toBe(-0.5)

      // Second dispatch with NaN normalized_score
      const state2 = evolutionReducer(state1, {
        type: 'candidate_evaluated',
        data: {
          generation: 1,
          candidate_id: 'nan-2',
          fitness_score: 0.6,
          normalized_score: NaN,
          rejected: false,
          mutation_type: 'rcc',
          island: 0,
        },
      })

      // bestNormalized should stay at -0.5, not become NaN
      expect(state2.summary.bestNormalized).toBe(-0.5)
    })
  })

  it('evolution_complete improvementDelta uses final bestFitness minus seedFitness', () => {
    // Simulate a run where seed was 0.3 and final best is 0.9
    const running: EvolutionState = {
      ...initialState,
      status: 'running',
      summary: {
        ...initialState.summary,
        seedFitness: 0.3,
        bestFitness: 0.8,
        improvementDelta: 0.5,
      },
    }

    const state = evolutionReducer(running, {
      type: 'evolution_complete',
      data: {
        termination_reason: 'fitness_target',
        best_fitness: 0.9,
        total_cost_usd: 2.0,
        generations_completed: 10,
      },
    })

    expect(state.summary.improvementDelta).toBeCloseTo(0.6)
    expect(state.summary.bestFitness).toBe(0.9)
  })
})
