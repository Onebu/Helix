import { useEffect, useReducer, useRef } from 'react';
import type {
  EvolutionState,
  EvolutionAction,
  RawEvolutionEvent,
} from '../types/evolution';
import { getWsBaseUrl } from '../lib/api-config';
import { getToken } from '../lib/auth';

export const initialState: EvolutionState = {
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
};

const MAX_CANDIDATES = 500;

export function evolutionReducer(
  state: EvolutionState,
  action: EvolutionAction,
): EvolutionState {
  switch (action.type) {
    case 'ws_connecting':
      return { ...state, status: 'connecting' };
    case 'ws_connected':
      return { ...state, status: 'running' };
    case 'ws_error':
      return { ...state, status: 'error' };
    case 'generation_started':
      return {
        ...state,
        islandCount: action.data.island_count || state.islandCount,
      };
    case 'candidate_evaluated': {
      const candidate = {
        candidateId: action.data.candidate_id,
        generation: action.data.generation,
        fitnessScore: action.data.fitness_score,
        normalizedScore: action.data.normalized_score,
        rejected: action.data.rejected,
        mutationType: action.data.mutation_type,
        island: action.data.island,
      };
      const newCandidates = [...state.candidates, candidate].slice(
        -MAX_CANDIDATES,
      );
      const newCount = state.summary.lineageEventCount + 1;

      // Track seed fitness from seed mutation events only
      let seedFitness = state.summary.seedFitness;
      if (action.data.mutation_type === 'seed') {
        seedFitness = seedFitness === null
          ? action.data.fitness_score
          : Math.max(seedFitness, action.data.fitness_score);
      }

      // Update best fitness — null means no real score yet
      const bestFitness = state.summary.bestFitness === null
        ? action.data.fitness_score
        : Math.max(state.summary.bestFitness, action.data.fitness_score);

      // Track best normalized score (guard against undefined/NaN from WS events)
      const rawNorm = action.data.normalized_score;
      const bestNormalized = rawNorm == null || isNaN(rawNorm)
        ? state.summary.bestNormalized
        : state.summary.bestNormalized === null
          ? rawNorm
          : Math.max(state.summary.bestNormalized, rawNorm);

      return {
        ...state,
        candidates: newCandidates,
        summary: {
          ...state.summary,
          lineageEventCount: newCount,
          seedFitness,
          bestFitness,
          bestNormalized,
          improvementDelta: seedFitness !== null ? bestFitness - seedFitness : 0,
        },
      };
    }
    case 'migration':
      return {
        ...state,
        migrations: [
          ...state.migrations,
          {
            generation: action.data.generation,
            emigrantsPerIsland: action.data.emigrants_per_island,
            timestamp: new Date().toISOString(),
          },
        ],
      };
    case 'island_reset':
      return state; // Visual feedback handled by candidates display
    case 'generation_complete': {
      const gen = {
        generation: action.data.generation,
        label: `Gen ${action.data.generation}`,
        bestFitness: action.data.best_fitness,
        avgFitness: action.data.avg_fitness,
        bestNormalized: action.data.best_normalized,
        avgNormalized: action.data.avg_normalized,
        candidatesEvaluated: action.data.candidates_evaluated,
        costUsd: action.data.cost_usd,
      };
      const bestFitness = state.summary.bestFitness === null
        ? action.data.best_fitness
        : Math.max(state.summary.bestFitness, action.data.best_fitness);

      const bestNormalized = state.summary.bestNormalized === null
        ? action.data.best_normalized
        : Math.max(state.summary.bestNormalized, action.data.best_normalized);

      const seedFitness = state.summary.seedFitness;
      const totalCostUsd = state.summary.totalCostUsd + action.data.cost_usd;

      return {
        ...state,
        generations: [...state.generations, gen],
        summary: {
          ...state.summary,
          bestFitness,
          bestNormalized,
          seedFitness,
          improvementDelta: seedFitness !== null ? bestFitness - seedFitness : 0,
          totalCostUsd,
          generationsCompleted: action.data.generation,
        },
      };
    }
    case 'evolution_complete':
      return {
        ...state,
        status: 'complete',
        summary: {
          ...state.summary,
          bestFitness:
            action.data.best_fitness ?? state.summary.bestFitness,
          bestNormalized:
            action.data.best_normalized ?? state.summary.bestNormalized,
          totalCostUsd:
            action.data.total_cost_usd ?? state.summary.totalCostUsd,
          terminationReason: action.data.termination_reason,
          generationsCompleted:
            action.data.generations_completed ??
            state.summary.generationsCompleted,
          improvementDelta: state.summary.seedFitness !== null
            ? (action.data.best_fitness ?? state.summary.bestFitness ?? 0) - state.summary.seedFitness
            : 0,
        },
      };
    case 'reset':
      return initialState;
    default:
      return state;
  }
}

export function useEvolutionSocket(runId: string | null): EvolutionState {
  const [state, dispatch] = useReducer(evolutionReducer, initialState);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!runId) {
      dispatch({ type: 'reset' });
      return;
    }

    dispatch({ type: 'ws_connecting' });

    const wsBase = getWsBaseUrl();
    const token = getToken();
    const tokenParam = token ? `?token=${encodeURIComponent(token)}` : '';
    const ws = new WebSocket(`${wsBase}/ws/evolution/${runId}${tokenParam}`);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data as string) as Record<string, unknown>;

      // Handle connected message
      if (msg.type === 'connected') {
        // Send subscribe with last_event_id=0 (fresh connection)
        ws.send(JSON.stringify({ type: 'subscribe', last_event_id: 0 }));
        dispatch({ type: 'ws_connected' });
        return;
      }

      // Handle evolution events
      const raw = msg as unknown as RawEvolutionEvent;
      dispatch({
        type: raw.type,
        data: raw.data,
      } as EvolutionAction);
    };

    ws.onerror = () => {
      dispatch({ type: 'ws_error', error: 'WebSocket connection failed' });
    };

    return () => {
      wsRef.current = null;
      if (
        ws.readyState === WebSocket.OPEN ||
        ws.readyState === WebSocket.CONNECTING
      ) {
        ws.close();
      }
    };
  }, [runId]);

  return state;
}
