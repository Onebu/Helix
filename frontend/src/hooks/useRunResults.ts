import { useState, useEffect } from 'react';
import type { RunResults, LineageNode, CaseResultData, GenerationRecordData } from '../types/evolution';
import type { CaseResultResponse, LineageEventResponse, RunResultsResponse } from '../client/types.gen';
import { apiJson, ApiError } from '../lib/api-fetch';

interface UseRunResultsReturn {
  data: RunResults | null;
  loading: boolean;
  error: string | null;
}

/** Transform a snake_case lineage event object to camelCase LineageNode. */
function transformLineageEvent(raw: LineageEventResponse): LineageNode {
  const evidence = raw as LineageEventResponse & {
    cases_passed?: number;
    total_cases?: number;
  };
  return {
    candidateId: raw.candidate_id as string,
    parentIds: (raw.parent_ids as string[]) ?? [],
    generation: raw.generation as number,
    island: (raw.island as number) ?? 0,
    fitnessScore: (raw.fitness_score as number) ?? 0,
    normalizedScore: (raw.normalized_score as number) ?? 0,
    rejected: (raw.rejected as boolean) ?? false,
    mutationType: (raw.mutation_type as string) ?? 'rcc',
    survived: (raw.survived as boolean) ?? true,
    template: raw.template ?? undefined,
    casesPassed: evidence.cases_passed,
    totalCases: evidence.total_cases,
  };
}

/** Transform a snake_case case result object to camelCase CaseResultData. */
function transformCaseResult(raw: CaseResultResponse): CaseResultData {
  return {
    caseId: raw.case_id as string,
    tier: (raw.tier as string) ?? 'normal',
    score: raw.score as number,
    passed: (raw.passed as boolean) ?? false,
    reason: (raw.reason as string) ?? '',
    expected: raw.expected as Record<string, unknown> | null | undefined,
    actualContent: raw.actual_content as string | null | undefined,
    actualToolCalls: raw.actual_tool_calls as Record<string, unknown>[] | null | undefined,
    criteriaResults: raw.criteria_results?.map(cr => ({
      criterion: cr.criterion as string,
      passed: cr.passed as boolean,
      reason: cr.reason as string,
    })) ?? null,
  };
}

/**
 * Fetch completed run results (lineage events, case results, best candidate)
 * from the history API.
 */
export function useRunResults(runId: string, refetchKey?: number): UseRunResultsReturn {
  const [data, setData] = useState<RunResults | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setLoading(false);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    async function fetchWithRetry(attempt = 0): Promise<RunResults> {
      const encodedRunId = encodeURIComponent(runId);
      let raw: RunResultsResponse;

      // Try UUID lookup first
      try {
        raw = await apiJson<RunResultsResponse>(
          `/api/history/run/by-uuid/${encodedRunId}/results`,
        );
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 404) throw error;
        // Fall back to integer ID (backward compat for old URLs)
        try {
          raw = await apiJson<RunResultsResponse>(
            `/api/history/run/${encodedRunId}/results`,
          );
        } catch (fallbackError) {
          if (fallbackError instanceof ApiError && fallbackError.status === 404 && attempt < 2) {
            // Retry with delay (race condition safety net for persistence lag)
            await new Promise(r => setTimeout(r, 1500));
            return fetchWithRetry(attempt + 1);
          }
          throw fallbackError;
        }
      }

      return {
        promptId: raw.prompt_id ?? null,
        lineageEvents: (raw.lineage_events ?? []).map(transformLineageEvent),
        caseResults: (raw.case_results ?? []).map(transformCaseResult),
        seedCaseResults: (raw.seed_case_results ?? []).map(transformCaseResult),
        generationRecords: (raw.generation_records ?? []).map(
          (gr): GenerationRecordData => ({
            generation: gr.generation,
            bestFitness: gr.best_fitness,
            avgFitness: gr.avg_fitness,
            bestNormalized: gr.best_normalized ?? 0,
            avgNormalized: gr.avg_normalized ?? 0,
            candidatesEvaluated: gr.candidates_evaluated ?? 0,
            costSummary: gr.cost_summary ?? {},
          })
        ),
        bestCandidateId: raw.best_candidate_id ?? null,
        bestTemplate: raw.best_template ?? null,
        totalCostUsd: raw.total_cost_usd ?? 0,
        bestFitnessScore: raw.best_fitness_score ?? null,
        bestNormalizedScore: raw.best_normalized_score ?? null,
        generationsCompleted: raw.generations_completed ?? 0,
        terminationReason: raw.termination_reason ?? null,
        metaModel: raw.meta_model ?? null,
        targetModel: raw.target_model ?? null,
        judgeModel: raw.judge_model ?? null,
        metaProvider: raw.meta_provider ?? null,
        targetProvider: raw.target_provider ?? null,
        judgeProvider: raw.judge_provider ?? null,
        hyperparameters: raw.hyperparameters ?? null,
      };
    }

    fetchWithRetry()
      .then((results) => {
        if (!cancelled) { setData(results); setLoading(false); }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
          setLoading(false);
        }
      });

    return () => { cancelled = true; };
  }, [runId, refetchKey]);

  return { data, loading, error };
}
