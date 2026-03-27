import { useTranslation } from 'react-i18next'
import { useModels } from '../../hooks/useModels'
import type { ModelInfo } from '../../hooks/useModels'
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/select'

interface ModelRoleSelectorProps {
  role: string
  provider: string | null
  model: string | null
  onProviderChange: (provider: string | null) => void
  onModelChange: (model: string | null) => void
}

/** Format context length for display (e.g., 128000 -> "128K") */
function formatContextLength(contextLength: number | null): string | null {
  if (contextLength == null) return null
  if (contextLength >= 1_000_000) {
    return `${(contextLength / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`
  }
  return `${Math.round(contextLength / 1000)}K`
}

/** Format pricing for display (e.g., 2.5 -> "$2.50/1M") */
function formatPrice(price: number | null): string | null {
  if (price == null) return null
  return `$${price.toFixed(2)}/1M`
}

/** Format a model entry's metadata for the dropdown display */
function ModelMeta({ model }: { model: ModelInfo }) {
  const ctx = formatContextLength(model.context_length)
  const inPrice = formatPrice(model.input_price_per_mtok)
  const outPrice = formatPrice(model.output_price_per_mtok)

  const parts: string[] = []
  if (ctx) parts.push(`${ctx} ctx`)
  if (inPrice && outPrice) parts.push(`${inPrice} in | ${outPrice} out`)
  else if (inPrice) parts.push(`${inPrice} in`)

  if (parts.length === 0) return null

  return (
    <span className="text-xs text-muted-foreground ml-2 shrink-0">
      {parts.join(' -- ')}
    </span>
  )
}

/**
 * Reusable provider + model dropdown pair for a single role (Meta, Target, or Judge).
 * Selecting a provider fetches the model list from GET /api/models/?provider=X.
 * Changing provider clears the model selection.
 */
export default function ModelRoleSelector({
  role,
  provider,
  model,
  onProviderChange,
  onModelChange,
}: ModelRoleSelectorProps) {
  const { t } = useTranslation()
  const { data: models, isLoading, isError } = useModels(provider)

  function handleProviderChange(value: string) {
    if (value === '__default__') {
      onProviderChange(null)
      onModelChange(null)
    } else {
      onProviderChange(value)
      onModelChange(null) // Clear model when provider changes
    }
  }

  function handleModelChange(value: string) {
    if (value === '__default__') {
      onModelChange(null)
    } else {
      onModelChange(value)
    }
  }

  return (
    <div className="space-y-1.5">
      <label className="block text-xs font-medium text-muted-foreground">{role}</label>
      <div className="flex gap-2">
        {/* Provider dropdown */}
        <div className="w-[140px] shrink-0">
          <Select
            value={provider ?? '__default__'}
            onValueChange={handleProviderChange}
          >
            <SelectTrigger className="h-8 text-xs" data-testid={`${role.toLowerCase()}-provider`}>
              <SelectValue placeholder={t('evolution.provider')} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__default__">{t('evolution.serverDefault')}</SelectItem>
              <SelectItem value="gemini">Gemini</SelectItem>
              <SelectItem value="openrouter">OpenRouter</SelectItem>
              <SelectItem value="openai">OpenAI</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {/* Model dropdown */}
        <div className="flex-1 min-w-0">
          <Select
            value={model ?? '__default__'}
            onValueChange={handleModelChange}
            disabled={!provider || isLoading}
          >
            <SelectTrigger className="h-8 text-xs" data-testid={`${role.toLowerCase()}-model`}>
              <SelectValue
                placeholder={
                  isLoading ? t('evolution.loadingModels') :
                  isError ? t('evolution.errorLoadingModels') :
                  !provider ? t('evolution.selectProviderFirst') :
                  t('evolution.serverDefault')
                }
              />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__default__">{t('evolution.serverDefault')}</SelectItem>
              {models?.map((m) => (
                <SelectItem key={m.id} value={m.id} textValue={m.name}>
                  <span className="flex items-center gap-1 w-full">
                    <span className="truncate">{m.name}</span>
                    <ModelMeta model={m} />
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
    </div>
  )
}
