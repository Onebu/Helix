import { useState, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, X, Save, Loader2, ChevronDown, ChevronRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { getApiBaseUrl } from '@/lib/api-config'

interface MockScenario {
  match_args: Record<string, string>
  response: string
}

interface MockDefinition {
  tool_name: string
  scenarios: MockScenario[]
}

async function fetchMocks(promptId: string): Promise<MockDefinition[]> {
  const resp = await fetch(`${getApiBaseUrl()}/api/prompts/${promptId}/mocks`)
  const data = await resp.json()
  return data.mocks || []
}

async function saveMocks(promptId: string, mocks: MockDefinition[]): Promise<void> {
  await fetch(`${getApiBaseUrl()}/api/prompts/${promptId}/mocks`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mocks }),
  })
}

export function MockEditor({ promptId, toolNames }: { promptId: string; toolNames: string[] }) {
  const queryClient = useQueryClient()
  const [mocks, setMocks] = useState<MockDefinition[]>([])
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [dirty, setDirty] = useState(false)

  const { data: savedMocks, isLoading } = useQuery({
    queryKey: ['mocks', promptId],
    queryFn: () => fetchMocks(promptId),
  })

  useEffect(() => {
    if (savedMocks) {
      setMocks(savedMocks)
      setDirty(false)
    }
  }, [savedMocks])

  const saveMutation = useMutation({
    mutationFn: () => saveMocks(promptId, mocks),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['mocks', promptId] })
      setDirty(false)
    },
  })

  const toggleExpand = (toolName: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(toolName)) next.delete(toolName)
      else next.add(toolName)
      return next
    })
  }

  const getMock = (toolName: string) => mocks.find((m) => m.tool_name === toolName)

  const updateMock = (toolName: string, scenarios: MockScenario[]) => {
    setDirty(true)
    setMocks((prev) => {
      const existing = prev.find((m) => m.tool_name === toolName)
      if (existing) {
        return prev.map((m) => (m.tool_name === toolName ? { ...m, scenarios } : m))
      }
      return [...prev, { tool_name: toolName, scenarios }]
    })
  }

  const addScenario = (toolName: string) => {
    const mock = getMock(toolName)
    const scenarios = mock ? [...mock.scenarios] : []
    scenarios.push({ match_args: {}, response: '{"status": "ok"}' })
    updateMock(toolName, scenarios)
    setExpanded((prev) => new Set(prev).add(toolName))
  }

  const removeScenario = (toolName: string, index: number) => {
    const mock = getMock(toolName)
    if (!mock) return
    updateMock(toolName, mock.scenarios.filter((_, i) => i !== index))
  }

  const updateScenario = (toolName: string, index: number, field: 'match_args' | 'response', value: string) => {
    const mock = getMock(toolName)
    if (!mock) return
    const scenarios = [...mock.scenarios]
    if (field === 'match_args') {
      try {
        scenarios[index] = { ...scenarios[index], match_args: JSON.parse(value) }
      } catch {
        // Don't update if invalid JSON
        return
      }
    } else {
      scenarios[index] = { ...scenarios[index], response: value }
    }
    updateMock(toolName, scenarios)
  }

  if (isLoading) return <p className="text-xs text-muted-foreground py-2">Loading mocks...</p>

  if (toolNames.length === 0) {
    return <p className="text-xs text-muted-foreground italic py-2">No tools defined. Add tools to configure mocks.</p>
  }

  return (
    <div className="space-y-2">
      {toolNames.map((toolName) => {
        const mock = getMock(toolName)
        const scenarioCount = mock?.scenarios.length ?? 0
        const isExpanded = expanded.has(toolName)

        return (
          <div key={toolName} className="rounded-md border border-border">
            <button
              onClick={() => toggleExpand(toolName)}
              className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-muted/50 transition-colors"
            >
              {isExpanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
              <code className="text-xs font-mono font-medium">{toolName}</code>
              <Badge variant="secondary" className="text-[10px] ml-auto">
                {scenarioCount} {scenarioCount === 1 ? 'scenario' : 'scenarios'}
              </Badge>
            </button>

            {isExpanded && (
              <div className="border-t border-border px-3 py-2 space-y-2">
                {(mock?.scenarios ?? []).map((scenario, idx) => (
                  <div key={idx} className="rounded border border-border/60 bg-muted/20 p-2 space-y-1.5">
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] font-medium text-muted-foreground uppercase">
                        Scenario {idx + 1}
                      </span>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-5 w-5"
                        onClick={() => removeScenario(toolName, idx)}
                      >
                        <X className="h-3 w-3" />
                      </Button>
                    </div>
                    <div className="space-y-1">
                      <label className="text-[10px] text-muted-foreground">Match args (JSON, {} = catch-all, "*" = wildcard)</label>
                      <Input
                        className="h-7 text-xs font-mono"
                        defaultValue={JSON.stringify(scenario.match_args)}
                        onBlur={(e) => updateScenario(toolName, idx, 'match_args', e.target.value)}
                      />
                    </div>
                    <div className="space-y-1">
                      <label className="text-[10px] text-muted-foreground">Response (Jinja2 template, args available as context)</label>
                      <Textarea
                        className="text-xs font-mono min-h-[60px]"
                        defaultValue={scenario.response}
                        onBlur={(e) => updateScenario(toolName, idx, 'response', e.target.value)}
                        rows={2}
                      />
                    </div>
                  </div>
                ))}

                <Button
                  variant="outline"
                  size="sm"
                  className="w-full text-xs"
                  onClick={() => addScenario(toolName)}
                >
                  <Plus className="h-3 w-3 mr-1" />
                  Add Scenario
                </Button>
              </div>
            )}
          </div>
        )
      })}

      {dirty && (
        <Button
          size="sm"
          className="w-full"
          onClick={() => saveMutation.mutate()}
          disabled={saveMutation.isPending}
        >
          {saveMutation.isPending ? (
            <><Loader2 className="h-3 w-3 mr-1 animate-spin" />Saving...</>
          ) : (
            <><Save className="h-3 w-3 mr-1" />Save Mocks</>
          )}
        </Button>
      )}
    </div>
  )
}
