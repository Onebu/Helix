import { useState, useEffect } from 'react';
import type { RunResults, LineageNode, CaseResultData, GenerationRecordData } from '../types/evolution';
import { getApiBaseUrl } from '../lib/api-config';

interface UseRunResultsReturn {
  data: RunResults | null;
  loading: boolean;
  error: string | null;
}

/** Transform a snake_case lineage event object to camelCase LineageNode. */
function transformLineageEvent(raw: Record<string, unknown>): LineageNode {
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
    template: raw.template as string | undefined,
  };
}

/** Transform a snake_case case result object to camelCase CaseResultData. */
function transformCaseResult(raw: Record<string, unknown>): CaseResultData {
  return {
    caseId: raw.case_id as string,
    tier: (raw.tier as string) ?? 'normal',
    score: raw.score as number,
    passed: (raw.passed as boolean) ?? false,
    reason: (raw.reason as string) ?? '',
    expected: raw.expected as Record<string, unknown> | null | undefined,
    actualContent: raw.actual_content as string | null | undefined,
    actualToolCalls: raw.actual_tool_calls as Record<string, unknown>[] | null | undefined,
    criteriaResults: (raw.criteria_results as Array<Record<string, unknown>> | null | undefined)?.map(cr => ({
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

    const baseUrl = getApiBaseUrl();

    async function fetchWithRetry(attempt = 0): Promise<RunResults> {
      // Try UUID lookup first
      const uuidUrl = `${baseUrl}/api/history/run/by-uuid/${runId}/results`;
      let resp = await fetch(uuidUrl);

      if (!resp.ok && resp.status === 404) {
        // Fall back to integer ID (backward compat for old URLs)
        const intUrl = `${baseUrl}/api/history/run/${runId}/results`;
        resp = await fetch(intUrl);
      }

      if (!resp.ok) {
        if (resp.status === 404 && attempt < 2) {
          // Retry with delay (race condition safety net for persistence lag)
          await new Promise(r => setTimeout(r, 1500));
          return fetchWithRetry(attempt + 1);
        }
        throw new Error(`Failed to fetch results: ${resp.status}`);
      }

      const raw = await resp.json();
      return {
        promptId: raw.prompt_id ?? null,
        lineageEvents: (raw.lineage_events ?? []).map(transformLineageEvent),
        caseResults: (raw.case_results ?? []).map(transformCaseResult),
        seedCaseResults: (raw.seed_case_results ?? []).map(transformCaseResult),
        generationRecords: (raw.generation_records ?? []).map(
          (gr: Record<string, unknown>): GenerationRecordData => ({
            generation: gr.generation as number,
            bestFitness: gr.best_fitness as number,
            avgFitness: gr.avg_fitness as number,
            bestNormalized: (gr.best_normalized as number) ?? 0,
            avgNormalized: (gr.avg_normalized as number) ?? 0,
            candidatesEvaluated: (gr.candidates_evaluated as number) ?? 0,
            costSummary: (gr.cost_summary as Record<string, unknown>) ?? {},
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
