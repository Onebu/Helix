import { useTranslation } from 'react-i18next'
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from '@/components/ui/select'

interface ThinkingBudgetControlProps {
  provider: string | null
  modelId: string | null
  thinkingBudget: number | null
  thinkingLevel: string | null
  onBudgetChange: (v: number | null) => void
  onLevelChange: (v: string | null) => void
}

/** Budget tier options for Gemini 2.5 series models.
 * Note: budget=0 ("Off") removed — Gemini 2.5 models reject it with 400. */
const BUDGET_OPTIONS = [
  { value: '__default__', label: 'Server default' },
  { value: '-1', label: 'Dynamic (auto)' },
  { value: '1024', label: 'Low (1K tokens)' },
  { value: '8192', label: 'Medium (8K tokens)' },
  { value: '24576', label: 'High (24K tokens)' },
] as const

/** Thinking level options for Gemini 3.x series models */
const LEVEL_OPTIONS = [
  { value: '__default__', label: 'Server default' },
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
] as const

/** Check if model ID indicates a Gemini 2.5 series model.
 * Explicit 3.x patterns return false; everything else (2.5, aliases, unknowns)
 * defaults to true since current latest aliases point to 2.5 series. */
function isGemini25(modelId: string): boolean {
  // Explicit 3.x detection takes priority -- these models use thinking level
  if (/3\.\d|gemini-3/.test(modelId)) return false
  // Explicit 2.5 match, OR aliases/unknowns default to 2.5 (current latest series)
  return true
}

/**
 * Conditional thinking control that shows model-series-appropriate settings.
 * - Gemini 2.5: thinking budget (token count) dropdown
 * - Gemini 3.x: thinking level (low/medium/high) dropdown
 * - Non-Gemini or no model: renders nothing
 */
export default function ThinkingBudgetControl({
  provider,
  modelId,
  thinkingBudget,
  thinkingLevel,
  onBudgetChange,
  onLevelChange,
}: ThinkingBudgetControlProps) {
  // Only show for Gemini provider with a selected model
  const { t } = useTranslation()
  if (provider !== 'gemini' || !modelId) return null

  if (isGemini25(modelId)) {
    // 2.5 series: budget dropdown (integer token count)
    const currentValue = thinkingBudget === null ? '__default__' : String(thinkingBudget)

    return (
      <Select
        value={currentValue}
        onValueChange={(v) => {
          if (v === '__default__') {
            onBudgetChange(null)
          } else {
            onBudgetChange(parseInt(v, 10))
          }
        }}
      >
        <SelectTrigger className="h-8 text-xs w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {BUDGET_OPTIONS.map((opt) => (
            <SelectItem key={opt.value} value={opt.value}>
              {opt.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    )
  }

  // 3.x series: level dropdown (enum string)
  const currentValue = thinkingLevel ?? '__default__'

  return (
    <Select
      value={currentValue}
      onValueChange={(v) => {
        if (v === '__default__') {
          onLevelChange(null)
        } else {
          onLevelChange(v)
        }
      }}
    >
      <SelectTrigger className="h-8 text-xs w-full">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {LEVEL_OPTIONS.map((opt) => (
          <SelectItem key={opt.value} value={opt.value}>
            {opt.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
