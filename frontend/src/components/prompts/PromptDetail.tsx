import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { ChevronDown, ChevronRight, FileText, Wrench, FlaskConical, Code2 } from 'lucide-react'
import {
  getPromptApiPromptsPromptIdGet,
  listCasesApiPromptsPromptIdDatasetGet,
} from '@/client/sdk.gen'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Collapsible,
  CollapsibleTrigger,
  CollapsibleContent,
} from '@/components/ui/collapsible'

interface PromptDetailProps {
  promptId: string
  onEditTemplate?: () => void
}

interface VariableDefinition {
  name: string
  var_type?: string
  description?: string | null
  is_anchor?: boolean
  items_schema?: VariableDefinition[] | null
}

interface ToolFunction {
  name: string
  description?: string
  parameters?: {
    type?: string
    properties?: Record<string, ToolParameter>
    required?: string[]
  }
}

interface ToolParameter {
  type?: string
  description?: string
  items?: { type?: string }
  enum?: string[]
}

interface Tool {
  type?: string
  function?: ToolFunction
}

// ---------------------------------------------------------------------------
// Skeleton
// ---------------------------------------------------------------------------

function PromptDetailSkeleton() {
  return (
    <div className="space-y-6">
      <div className="rounded-lg border border-border bg-card overflow-hidden">
        <div className="px-4 py-3 border-b border-border">
          <Skeleton className="h-7 w-[200px]" />
        </div>
        <div className="p-4 space-y-3">
          <Skeleton className="h-4 w-[350px]" />
          <div className="flex gap-2">
            <Skeleton className="h-5 w-16 rounded-full" />
            <Skeleton className="h-5 w-16 rounded-full" />
            <Skeleton className="h-5 w-16 rounded-full" />
          </div>
        </div>
      </div>
      <div className="rounded-lg border border-border bg-card overflow-hidden">
        <div className="p-4">
          <Skeleton className="h-[200px] w-full" />
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Section 1: Template Preview
// ---------------------------------------------------------------------------

const COLLAPSED_LINE_LIMIT = 20

function highlightTemplateVariables(text: string): React.ReactNode[] {
  const parts = text.split(/(\{\{.*?\}\})/g)
  return parts.map((part, i) => {
    if (/^\{\{.*\}\}$/.test(part)) {
      return (
        <span key={i} className="text-primary font-semibold bg-primary/10 rounded px-0.5">
          {part}
        </span>
      )
    }
    return <span key={i}>{part}</span>
  })
}

function TemplatePreviewSection({
  template,
  onEdit,
}: {
  template: string
  onEdit?: () => void
}) {
  const { t } = useTranslation()
  const lines = template.split('\n')
  const isLong = lines.length > COLLAPSED_LINE_LIMIT
  const [expanded, setExpanded] = useState(false)

  const displayText =
    isLong && !expanded
      ? lines.slice(0, COLLAPSED_LINE_LIMIT).join('\n')
      : template

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      <div className="px-4 py-3 border-b border-border flex items-center justify-between">
        <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
          <FileText className="h-4 w-4" />
          {t('prompts.templatePreview')}
        </h3>
        {onEdit && (
          <Button variant="ghost" size="sm" onClick={onEdit}>
            {t('prompts.editTemplate')}
          </Button>
        )}
      </div>
      <div className="p-4">
        <pre className="overflow-auto rounded bg-muted p-4 text-sm text-foreground whitespace-pre-wrap break-words font-mono leading-relaxed">
          {highlightTemplateVariables(displayText)}
          {isLong && !expanded && (
            <span className="text-muted-foreground">{'\n...'}</span>
          )}
        </pre>
        {isLong && (
          <Button
            variant="ghost"
            size="sm"
            className="mt-2"
            onClick={() => setExpanded(!expanded)}
          >
            {expanded
              ? t('prompts.showLess')
              : t('prompts.showAll', { count: lines.length })}
          </Button>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Section 2: Variables & Schema (merged)
// ---------------------------------------------------------------------------

function VariableSchemaRow({ varDef }: { varDef: VariableDefinition }) {
  const [expanded, setExpanded] = useState(false)
  const { t } = useTranslation()
  const hasSubFields = varDef.items_schema && varDef.items_schema.length > 0

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2">
        {hasSubFields ? (
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex items-center gap-1 text-muted-foreground hover:text-foreground transition-colors"
          >
            {expanded ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
          </button>
        ) : (
          <span className="w-5" />
        )}
        <code className="font-mono text-sm font-medium">{varDef.name}</code>
        <Badge variant="secondary" className="text-xs">
          {varDef.var_type === 'array' && hasSubFields
            ? 'array<object>'
            : varDef.var_type || 'string'}
        </Badge>
        {varDef.is_anchor && (
          <Badge
            variant="outline"
            className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30 text-xs"
          >
            {t('prompts.anchor')}
          </Badge>
        )}
        {varDef.description && (
          <span className="text-xs text-muted-foreground truncate">
            {varDef.description}
          </span>
        )}
      </div>

      {expanded && hasSubFields && (
        <div className="ml-7 mt-1 border-l-2 border-primary/20 pl-3 space-y-1">
          {varDef.items_schema!.map((subField, i) => (
            <div key={i} className="flex items-center gap-2 py-0.5">
              <code className="text-sm text-muted-foreground font-mono">
                {subField.name}
              </code>
              <Badge variant="secondary" className="text-xs">
                {subField.var_type || 'string'}
              </Badge>
              {subField.is_anchor && (
                <Badge
                  variant="outline"
                  className="bg-emerald-500/20 text-emerald-400 border-emerald-500/30 text-xs"
                >
                  {t('prompts.anchor')}
                </Badge>
              )}
              {subField.description && (
                <span className="text-xs text-muted-foreground truncate">
                  {subField.description}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function VariablesSchemaSection({
  variableDefs,
}: {
  variableDefs: VariableDefinition[]
}) {
  const { t } = useTranslation()

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      <div className="px-4 py-3 border-b border-border">
        <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
          <Code2 className="h-4 w-4" />
          {t('prompts.variablesAndSchema')}
        </h3>
      </div>
      <div className="p-4">
        {variableDefs.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {t('prompts.noVariables')}
          </p>
        ) : (
          <div className="space-y-2">
            {variableDefs.map((varDef, i) => (
              <VariableSchemaRow key={i} varDef={varDef} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Section 3: Tools (reformatted)
// ---------------------------------------------------------------------------

function formatParamType(param: ToolParameter): string {
  if (param.type === 'array' && param.items?.type) {
    return `${param.items.type}[]`
  }
  if (param.enum && param.enum.length > 0) {
    return `enum(${param.enum.join(', ')})`
  }
  return param.type || 'string'
}

function ToolCard({ tool, index }: { tool: Tool; index: number }) {
  const { t } = useTranslation()
  const [showRaw, setShowRaw] = useState(false)
  const fn = tool.function

  if (!fn) return null

  const properties = fn.parameters?.properties || {}
  const required = new Set(fn.parameters?.required || [])
  const paramEntries = Object.entries(properties)

  return (
    <div className="rounded-lg border bg-muted/30 p-4 space-y-3">
      <div className="flex items-center gap-2">
        <code className="font-mono text-sm font-semibold text-foreground">
          {fn.name}
        </code>
        {index >= 0 && (
          <span className="text-xs text-muted-foreground">#{index + 1}</span>
        )}
      </div>

      {fn.description ? (
        <p className="text-sm text-muted-foreground">{fn.description}</p>
      ) : (
        <p className="text-sm text-muted-foreground italic">
          {t('prompts.noDescription')}
        </p>
      )}

      {paramEntries.length > 0 ? (
        <div className="space-y-1">
          <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
            {t('prompts.parameters')}
          </span>
          <div className="grid gap-1">
            {paramEntries.map(([paramName, param]) => (
              <div key={paramName} className="flex items-center gap-2 pl-2">
                <code className="font-mono text-xs">{paramName}</code>
                <Badge variant="secondary" className="text-xs py-0">
                  {formatParamType(param)}
                </Badge>
                {required.has(paramName) && (
                  <Badge
                    variant="outline"
                    className="text-xs py-0 text-amber-400 border-amber-500/30 bg-amber-500/10"
                  >
                    {t('prompts.required')}
                  </Badge>
                )}
                {param.description && (
                  <span className="text-xs text-muted-foreground truncate">
                    {param.description}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      ) : (
        <p className="text-xs text-muted-foreground italic pl-2">
          {t('prompts.noParameters')}
        </p>
      )}

      <Collapsible>
        <CollapsibleTrigger asChild>
          <Button
            variant="ghost"
            size="sm"
            className="text-xs h-7 px-2"
            onClick={() => setShowRaw(!showRaw)}
          >
            {showRaw ? t('prompts.hideRawJson') : t('prompts.showRawJson')}
          </Button>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <pre className="mt-2 overflow-auto rounded bg-muted p-3 text-xs text-foreground">
            {JSON.stringify(tool, null, 2)}
          </pre>
        </CollapsibleContent>
      </Collapsible>
    </div>
  )
}

function ToolsSection({ tools }: { tools: Tool[] }) {
  const { t } = useTranslation()

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      <div className="px-4 py-3 border-b border-border">
        <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
          <Wrench className="h-4 w-4" />
          {tools.length > 0
            ? t('prompts.toolsCount', { count: tools.length })
            : t('prompts.tools')}
        </h3>
      </div>
      <div className="p-4">
        {tools.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            {t('prompts.noTools')}
          </p>
        ) : (
          <div className="space-y-3">
            {tools.map((tool, i) => (
              <ToolCard key={i} tool={tool} index={i} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Section 4: Test Cases (inline preview)
// ---------------------------------------------------------------------------

interface TestCasePreview {
  tier: string
}

function TestCasesPreviewSection({ promptId }: { promptId: string }) {
  const { t } = useTranslation()

  const { data: casesResp } = useQuery({
    queryKey: ['test-cases', promptId],
    queryFn: () =>
      listCasesApiPromptsPromptIdDatasetGet({
        path: { prompt_id: promptId },
      }),
    enabled: !!promptId,
  })

  const cases = (casesResp?.data || []) as unknown as TestCasePreview[]

  const { total, critical, normal, low } = useMemo(() => {
    let crit = 0
    let norm = 0
    let lo = 0
    for (const tc of cases) {
      const tier = (tc.tier || 'normal').toLowerCase()
      if (tier === 'critical') crit++
      else if (tier === 'low') lo++
      else norm++
    }
    return { total: cases.length, critical: crit, normal: norm, low: lo }
  }, [cases])

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      <div className="px-4 py-3 border-b border-border">
        <h3 className="text-sm font-semibold text-foreground flex items-center gap-2">
          <FlaskConical className="h-4 w-4" />
          {t('prompts.testCases')}
        </h3>
      </div>
      <div className="p-4">
        {total === 0 ? (
          <p className="text-sm text-muted-foreground">
            {t('prompts.noTestCases')}
          </p>
        ) : (
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm text-foreground font-medium">
              {total === 1
                ? t('prompts.testCasesSummaryOne')
                : t('prompts.testCasesSummary', { count: total })}
            </span>
            <span className="text-sm text-muted-foreground">
              {t('prompts.tierBreakdown', { critical, normal, low })}
            </span>
          </div>
        )}
        <div className="mt-3">
          <Button variant="secondary" size="sm" asChild>
            <Link to="../dataset">{t('prompts.viewDatasetTab')}</Link>
          </Button>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main Export
// ---------------------------------------------------------------------------

export default function PromptDetail({ promptId, onEditTemplate }: PromptDetailProps) {
  const { t } = useTranslation()
  const {
    data: prompt,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['prompts', promptId],
    queryFn: () =>
      getPromptApiPromptsPromptIdGet({
        path: { prompt_id: promptId },
      }),
  })

  if (isLoading) {
    return <PromptDetailSkeleton />
  }

  if (error) {
    return <p className="text-destructive">{t('prompts.failedToLoadPrompt')}</p>
  }

  const detail = prompt?.data
  if (!detail) {
    return <p className="text-muted-foreground">{t('prompts.promptNotFound')}</p>
  }

  const variableDefs = (detail.variable_definitions || []) as unknown as VariableDefinition[]
  const tools = (detail.tools || []) as unknown as Tool[]

  return (
    <div className="space-y-6">
      {/* Section 1: Template Preview */}
      <TemplatePreviewSection
        template={detail.template}
        onEdit={onEditTemplate}
      />

      {/* Section 2: Variables & Schema */}
      <VariablesSchemaSection variableDefs={variableDefs} />

      {/* Section 3: Tools */}
      <ToolsSection tools={tools} />

      {/* Section 4: Test Cases */}
      <TestCasesPreviewSection promptId={promptId} />
    </div>
  )
}
