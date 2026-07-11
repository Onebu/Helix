import { useEffect, useId, useMemo, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, ChevronDown, Search } from 'lucide-react'
import { useModels } from '../../hooks/useModels'
import type { ModelInfo } from '../../hooks/useModels'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/select'
import { cn } from '@/lib/utils'

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
    <span className="mt-1 block text-[11px] leading-tight text-muted-foreground">
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
  const [modelPickerOpen, setModelPickerOpen] = useState(false)
  const [modelQuery, setModelQuery] = useState('')
  const [activeIndex, setActiveIndex] = useState(0)
  const listboxId = useId()

  const selectedModel = models?.find((item) => item.id === model)
  const filteredModels = useMemo(() => {
    const query = modelQuery.trim().toLowerCase()
    if (!query) return models ?? []
    return (models ?? []).filter(
      (item) => item.name.toLowerCase().includes(query) || item.id.toLowerCase().includes(query),
    )
  }, [modelQuery, models])
  const searching = modelQuery.trim().length > 0
  const optionCount = filteredModels.length + (searching ? 0 : 1)
  const activeOptionId = optionCount > 0
    ? `${listboxId}-option-${Math.min(activeIndex, optionCount - 1)}`
    : undefined

  useEffect(() => {
    if (!modelPickerOpen || !activeOptionId) return
    document.getElementById(activeOptionId)?.scrollIntoView?.({ block: 'nearest' })
  }, [activeOptionId, modelPickerOpen])

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
    setModelPickerOpen(false)
    setModelQuery('')
  }

  function handleSearchKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (optionCount === 0) return
    const boundedIndex = Math.min(activeIndex, optionCount - 1)
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActiveIndex(Math.min(boundedIndex + 1, optionCount - 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActiveIndex(Math.max(boundedIndex - 1, 0))
    } else if (event.key === 'Home') {
      event.preventDefault()
      setActiveIndex(0)
    } else if (event.key === 'End') {
      event.preventDefault()
      setActiveIndex(optionCount - 1)
    } else if (event.key === 'Enter') {
      event.preventDefault()
      if (!searching && boundedIndex === 0) {
        handleModelChange('__default__')
      } else {
        const modelIndex = searching ? boundedIndex : boundedIndex - 1
        const activeModel = filteredModels[modelIndex]
        if (activeModel) handleModelChange(activeModel.id)
      }
    }
  }

  const modelTriggerLabel = isLoading ? t('evolution.loadingModels')
    : isError ? t('evolution.errorLoadingModels')
    : !provider ? t('evolution.selectProviderFirst')
    : selectedModel?.name ?? model ?? t('evolution.serverDefault')
  const providerTriggerLabel = provider == null
    ? t('evolution.serverDefault')
    : ({ gemini: 'Gemini', openrouter: 'OpenRouter', openai: 'OpenAI' }[provider] ?? provider)
  const providerAccessibleName = t('evolution.controlWithValue', {
    label: t('evolution.providerForRole', { role }),
    value: providerTriggerLabel,
  })
  const modelAccessibleName = t('evolution.controlWithValue', {
    label: t('evolution.modelForRole', { role }),
    value: modelTriggerLabel,
  })

  return (
    <fieldset className="min-w-0 space-y-1.5">
      <legend className="block text-xs font-medium text-muted-foreground">{role}</legend>
      <div className="flex gap-2">
        {/* Provider dropdown */}
        <div className="w-[140px] shrink-0">
          <Select
            value={provider ?? '__default__'}
            onValueChange={handleProviderChange}
          >
            <SelectTrigger
              aria-label={providerAccessibleName}
              className="h-10 text-xs sm:h-8"
              data-testid={`${role.toLowerCase()}-provider`}
            >
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

        {/* Searchable model picker */}
        <div className="flex-1 min-w-0">
          <Popover
            open={modelPickerOpen}
            onOpenChange={(open) => {
              setModelPickerOpen(open)
              setModelQuery('')
              const selectedIndex = model == null
                ? 0
                : (models?.findIndex((item) => item.id === model) ?? -1) + 1
              setActiveIndex(open && selectedIndex > 0 ? selectedIndex : 0)
            }}
          >
            <PopoverTrigger asChild>
              <Button
                type="button"
                variant="outline"
                aria-label={modelAccessibleName}
                aria-expanded={modelPickerOpen}
                disabled={!provider || isLoading}
                className="h-10 w-full justify-between px-3 text-xs font-normal sm:h-8"
                data-testid={`${role.toLowerCase()}-model`}
              >
                <span className="min-w-0 truncate">{modelTriggerLabel}</span>
                <ChevronDown className="size-3.5 text-muted-foreground" aria-hidden="true" />
              </Button>
            </PopoverTrigger>
            <PopoverContent align="start" className="w-[min(32rem,calc(100vw-2rem))] p-0">
              <div className="flex items-center gap-2 border-b px-3">
                <Search className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                <input
                  autoFocus
                  type="search"
                  role="combobox"
                  aria-label={t('evolution.modelSearchPlaceholder')}
                  aria-autocomplete="list"
                  aria-controls={listboxId}
                  aria-expanded={modelPickerOpen}
                  aria-activedescendant={activeOptionId}
                  placeholder={t('evolution.modelSearchPlaceholder')}
                  value={modelQuery}
                  onChange={(event) => {
                    setModelQuery(event.target.value)
                    setActiveIndex(0)
                  }}
                  onKeyDown={handleSearchKeyDown}
                  className="h-10 min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
                />
              </div>
              <div
                role="listbox"
                id={listboxId}
                aria-label={t('evolution.modelForRole', { role })}
                className="max-h-72 overflow-y-auto p-1"
              >
                {!searching && (
                  <button
                    type="button"
                    role="option"
                    id={`${listboxId}-option-0`}
                    tabIndex={-1}
                    aria-selected={model == null}
                    onPointerMove={() => setActiveIndex(0)}
                    onClick={() => handleModelChange('__default__')}
                    className={cn(
                      'flex min-h-11 w-full items-center gap-2 rounded-sm px-2 py-2 text-left text-sm hover:bg-accent focus-visible:bg-accent focus-visible:outline-none',
                      activeIndex === 0 && 'bg-accent',
                    )}
                  >
                    <Check className={cn('size-4 shrink-0', model == null ? 'opacity-100' : 'opacity-0')} />
                    {t('evolution.serverDefault')}
                  </button>
                )}
                {filteredModels.map((item, index) => {
                  const optionIndex = index + (searching ? 0 : 1)
                  return (
                    <button
                      key={item.id}
                      type="button"
                      role="option"
                      id={`${listboxId}-option-${optionIndex}`}
                      tabIndex={-1}
                      aria-selected={model === item.id}
                      onPointerMove={() => setActiveIndex(optionIndex)}
                      onClick={() => handleModelChange(item.id)}
                      className={cn(
                        'flex min-h-11 w-full items-center gap-2 rounded-sm px-2 py-2 text-left text-sm hover:bg-accent focus-visible:bg-accent focus-visible:outline-none',
                        activeIndex === optionIndex && 'bg-accent',
                      )}
                    >
                      <Check className={cn('size-4 shrink-0', model === item.id ? 'opacity-100' : 'opacity-0')} />
                      <span className="min-w-0 flex-1">
                        <span className="block whitespace-normal break-words leading-tight">{item.name}</span>
                        <ModelMeta model={item} />
                      </span>
                    </button>
                  )
                })}
                {filteredModels.length === 0 && (
                  <p role="status" aria-live="polite" className="px-3 py-6 text-center text-sm text-muted-foreground">
                    {t('evolution.noMatchingModels')}
                  </p>
                )}
              </div>
            </PopoverContent>
          </Popover>
        </div>
      </div>
    </fieldset>
  )
}
