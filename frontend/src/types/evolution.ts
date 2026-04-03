// --- Event shapes (matching backend EvolutionEvent.data) ---

export interface GenerationStartedData {
  generation: number;
  island_count: number;
}

export interface CandidateEvaluatedData {
  generation: number;
  candidate_id: string;
  fitness_score: number;
  normalized_score: number;
  rejected: boolean;
  mutation_type: string;
  island: number;
}

export interface MigrationEventData {
  generation: number;
  emigrants_per_island: number;
}

export interface IslandResetData {
  generation: number;
  islands_reset: number[];
}

export interface GenerationCompleteData {
  generation: number;
  best_fitness: number;
  avg_fitness: number;
  best_normalized: number;
  avg_normalized: number;
  candidates_evaluated: number;
  cost_usd: number;
}

export interface EvolutionCompleteData {
  termination_reason: string;
  best_fitness: number;
  best_normalized?: number;
  total_cost_usd: number;
  generations_completed: number;
  error?: string | null;
}

// --- Raw WebSocket event envelope ---

export interface RawEvolutionEvent {
  event_id: number;
  run_id: string;
  type: string;
  timestamp: string;
  data: Record<string, unknown>;
}

// --- Derived visualization data ---

export interface GenerationData {
  generation: number;
  label: string; // "Seed", "Gen 1", "Gen 2", ...
  bestFitness: number;
  avgFitness: number;
  bestNormalized: number;
  avgNormalized: number;
  candidatesEvaluated: number;
  costUsd: number;
}

export interface CandidateData {
  candidateId: string;
  generation: number;
  fitnessScore: number;
  normalizedScore: number;
  rejected: boolean;
  mutationType: string;
  island: number;
}

export interface MigrationData {
  generation: number;
  emigrantsPerIsland: number;
  timestamp: string;
}

export interface SummaryData {
  bestFitness: number | null;
  bestNormalized: number | null;
  seedFitness: number | null;
  improvementDelta: number;
  terminationReason: string | null;
  lineageEventCount: number;
  totalCostUsd: number;
  generationsCompleted: number;
}

// --- Hook state and actions ---

export type EvolutionStatus =
  | 'idle'
  | 'connecting'
  | 'running'
  | 'complete'
  | 'error';

export interface EvolutionState {
  status: EvolutionStatus;
  generations: GenerationData[];
  candidates: CandidateData[];
  migrations: MigrationData[];
  summary: SummaryData;
  islandCount: number;
}

export type EvolutionAction =
  | { type: 'ws_connecting' }
  | { type: 'ws_connected' }
  | { type: 'ws_error'; error: string }
  | { type: 'generation_started'; data: GenerationStartedData }
  | { type: 'candidate_evaluated'; data: CandidateEvaluatedData }
  | { type: 'migration'; data: MigrationEventData }
  | { type: 'island_reset'; data: IslandResetData }
  | { type: 'generation_complete'; data: GenerationCompleteData }
  | { type: 'evolution_complete'; data: EvolutionCompleteData }
  | { type: 'reset' };

// --- Design color constants ---
// Mutation type colors — categorical palette matching CSS tokens (--mutation-*)
export const MUTATION_COLORS: Record<string, string> = {
  rcc: '#22c55e',
  structural: '#f59e0b',
  fresh: '#8b5cf6',
  migrated: '#3b82f6',
  reset: '#ef4444',
  seed: '#94a3b8',
};

export const MUTATION_FALLBACK = '#64748b';

/** Return a hex color with appended alpha (e.g. '#22c55e' + 0.13 → '#22c55e21') */
export function mutationBg(type: string): string {
  return `${MUTATION_COLORS[type] ?? MUTATION_FALLBACK}1a`;
}

/** Return the mutation color for a type, or the fallback slate. */
export function mutationColor(type: string): string {
  return MUTATION_COLORS[type] ?? MUTATION_FALLBACK;
}

// Score feedback colors — match CSS tokens (--score-*)
export const SCORE_POSITIVE = '#22c55e';
export const SCORE_NEGATIVE = '#ef4444';
export const SCORE_NEUTRAL = '#94a3b8';

// --- Post-run inspection types (Phase 19) ---

export interface CriterionResult {
  criterion: string;
  passed: boolean;
  reason: string;
}

export interface LineageNode {
  candidateId: string;
  parentIds: string[];
  generation: number;
  island: number;
  fitnessScore: number;
  normalizedScore: number;
  rejected: boolean;
  mutationType: string;
  survived: boolean;
  template?: string;
}

export interface CaseResultData {
  caseId: string;
  tier: string;
  score: number;
  passed: boolean;
  reason: string;
  expected?: Record<string, unknown> | null;
  actualContent?: string | null;
  actualToolCalls?: Record<string, unknown>[] | null;
  criteriaResults?: CriterionResult[] | null;
}

export interface MutationStat {
  count: number;
  improved: number;
  avgDelta: number;
}

export interface GenerationRecordData {
  generation: number;
  bestFitness: number;
  avgFitness: number;
  bestNormalized: number;
  avgNormalized: number;
  candidatesEvaluated: number;
  costSummary: Record<string, unknown>;
}

export interface RunResults {
  promptId: string | null;
  lineageEvents: LineageNode[];
  caseResults: CaseResultData[];
  seedCaseResults: CaseResultData[];
  generationRecords: GenerationRecordData[];
  bestCandidateId: string | null;
  bestTemplate: string | null;
  totalCostUsd: number;
  bestFitnessScore: number | null;
  bestNormalizedScore: number | null;
  generationsCompleted: number;
  terminationReason: string | null;
  metaModel: string | null;
  targetModel: string | null;
  judgeModel: string | null;
  metaProvider: string | null;
  targetProvider: string | null;
  judgeProvider: string | null;
  hyperparameters: Record<string, unknown> | null;
}
