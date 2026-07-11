import { useQuery } from '@tanstack/react-query';
import { apiJson } from '../lib/api-fetch';

export interface ModelInfo {
  id: string;
  name: string;
  context_length: number | null;
  input_price_per_mtok: number | null;
  output_price_per_mtok: number | null;
  provider: string;
}

/**
 * Fetch available models for a given provider from the model browser API.
 * Returns cached data for 5 minutes (matching backend cache TTL).
 * Disabled when provider is null (no fetch until provider is selected).
 */
export function useModels(provider: string | null) {
  return useQuery<ModelInfo[]>({
    queryKey: ['models', provider],
    queryFn: () => apiJson<ModelInfo[]>(`/api/models/?provider=${encodeURIComponent(provider!)}`),
    enabled: !!provider,
    staleTime: 5 * 60 * 1000, // 5 minutes -- matches backend cache TTL
  });
}
