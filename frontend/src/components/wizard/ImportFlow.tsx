import { useTranslation } from 'react-i18next'
import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import Editor from '@monaco-editor/react'
import {
  Upload,
  FileText,
  Loader2,
  Save,
  AlertCircle,
  Variable,
  X,
  Wrench,
} from 'lucide-react'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
  extractVariablesApiPromptsExtractVariablesPost,
  createPromptApiPromptsPost,
} from '@/client/sdk.gen'
import { SLUG_PATTERN } from './constants'

interface VariableBinding {
  name: string
  description: string
  isAnchor: boolean
}

interface ToolDef {
  type: string
  function: {
    name: string
    description?: string
    parameters?: Record<string, unknown>
  }
  [key: string]: unknown
}

function parseToolsFile(content: string): { tools: ToolDef[]; error?: string } {
  try {
    const parsed = JSON.parse(content)

    // Accept array directly or { tools: [...] } wrapper
    const arr = Array.isArray(parsed)
      ? parsed
      : Array.isArray(parsed?.tools)
        ? parsed.tools
        : null

    if (!arr) {
      return { tools: [], error: 'Expected a JSON array of tool definitions or an object with a "tools" key.' }
    }

    // Validate each entry has function.name
    const valid: ToolDef[] = []
    for (const item of arr) {
      if (item?.function?.name) {
        valid.push(item as ToolDef)
      } else if (item?.name) {
        // Bare function definition — wrap in OpenAI format
        valid.push({ type: 'function', function: item })
      }
    }

    if (valid.length === 0) {
      return { tools: [], error: 'No valid tool definitions found. Each tool needs at least a "function.name" field.' }
    }

    return { tools: valid }
  } catch {
    return { tools: [], error: 'Invalid JSON file.' }
  }
}

export function ImportFlow() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [id, setId] = useState('')
  const [purpose, setPurpose] = useState('')
  const [template, setTemplate] = useState('')
  const [fileName, setFileName] = useState<string | null>(null)
  const [variables, setVariables] = useState<VariableBinding[]>([])
  const [tools, setTools] = useState<ToolDef[]>([])
  const [toolsFileName, setToolsFileName] = useState<string | null>(null)
  const [parseErrors, setParseErrors] = useState<string[]>([])
  const [registerError, setRegisterError] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)

  const idValid = SLUG_PATTERN.test(id)
  const idTouched = id.length > 0

  const handleFileContent = useCallback((content: string, name: string) => {
    setTemplate(content)
    setFileName(name)
    setParseErrors([])
    setVariables([])

    const baseName = name.replace(/\.(md|txt|yaml|yml|j2|jinja|jinja2|tmpl)$/i, '')
    const slugified = baseName.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
    if (SLUG_PATTERN.test(slugified)) {
      setId(slugified)
    }
  }, [])

  const handleFileDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setDragOver(false)
      const file = e.dataTransfer.files[0]
      if (file) {
        const reader = new FileReader()
        reader.onload = (ev) => {
          handleFileContent(ev.target?.result as string, file.name)
        }
        reader.readAsText(file)
      }
    },
    [handleFileContent],
  )

  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0]
      if (file) {
        const reader = new FileReader()
        reader.onload = (ev) => {
          handleFileContent(ev.target?.result as string, file.name)
        }
        reader.readAsText(file)
      }
    },
    [handleFileContent],
  )

  const handleToolsFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0]
      if (!file) return
      const reader = new FileReader()
      reader.onload = (ev) => {
        const content = ev.target?.result as string
        const result = parseToolsFile(content)
        setTools(result.tools)
        setToolsFileName(file.name)
        if (result.error) {
          setParseErrors((prev) => [...prev, result.error!])
        }
      }
      reader.readAsText(file)
    },
    [],
  )

  const extractMutation = useMutation({
    mutationFn: () =>
      extractVariablesApiPromptsExtractVariablesPost({
        body: { template },
      }),
    onSuccess: (result) => {
      if (result.data) {
        setVariables(
          result.data.variables.map((name) => ({
            name,
            description: '',
            isAnchor: false,
          })),
        )
        setParseErrors(result.data.errors || [])
      }
    },
    onError: () => {
      setParseErrors(['Failed to extract variables from template'])
    },
  })

  const registerMutation = useMutation({
    mutationFn: () =>
      createPromptApiPromptsPost({
        body: {
          id,
          purpose,
          template,
          variables: variables.map((v) => ({
            name: v.name,
            description: v.description || undefined,
            is_anchor: v.isAnchor,
          })),
          tools: tools.length > 0 ? tools : undefined,
        },
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['prompts'] })
      navigate(`/prompts/${id}/template`)
    },
    onError: (error) => {
      setRegisterError(
        error instanceof Error ? error.message : 'Failed to register prompt',
      )
    },
  })

  const updateVariable = (index: number, updates: Partial<VariableBinding>) => {
    setVariables((prev) =>
      prev.map((v, i) => (i === index ? { ...v, ...updates } : v)),
    )
  }

  const removeVariable = (index: number) => {
    setVariables((prev) => prev.filter((_, i) => i !== index))
  }

  const removeTool = (index: number) => {
    setTools((prev) => prev.filter((_, i) => i !== index))
    if (tools.length <= 1) setToolsFileName(null)
  }

  const canExtract = template.trim().length > 0
  const canRegister =
    idValid && purpose.trim().length > 0 && template.trim().length > 0

  return (
    <div className="max-w-2xl mx-auto space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <Upload className="h-5 w-5" />
            {t('import.uploadTemplate')}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div
            className={`border-2 border-dashed rounded-lg p-8 text-center transition-colors ${
              dragOver
                ? 'border-primary bg-primary/5'
                : 'border-border hover:border-muted-foreground/50'
            }`}
            onDragOver={(e) => {
              e.preventDefault()
              setDragOver(true)
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleFileDrop}
          >
            <FileText className="h-10 w-10 text-muted-foreground mx-auto mb-3" />
            <p className="text-sm text-muted-foreground mb-3">
              {t('import.dropFile')}
            </p>
            <label>
              <input
                type="file"
                accept=".md,.txt,.yaml,.yml,.j2,.jinja,.jinja2,.tmpl"
                onChange={handleFileSelect}
                className="hidden"
              />
              <Button variant="outline" size="sm" asChild>
                <span>{t('import.browseFiles')}</span>
              </Button>
            </label>
            {fileName && (
              <p className="text-sm text-foreground mt-3 font-mono">
                {fileName}
              </p>
            )}
            <p className="text-xs text-muted-foreground mt-2">
              {t('import.supportedFormats')}
            </p>
          </div>

          <p className="text-xs text-muted-foreground">
            {t('import.orPaste')}
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">{t('import.templateContent')}</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="rounded-md border border-border overflow-hidden">
            <Editor
              height="300px"
              language="markdown"
              value={template}
              onChange={(value) => setTemplate(value || '')}
              options={{
                minimap: { enabled: false },
                scrollBeyondLastLine: false,
                fontSize: 13,
                lineNumbers: 'on',
                wordWrap: 'on',
              }}
              theme="vs-dark"
            />
          </div>
        </CardContent>
      </Card>

      {/* Tools import (optional) */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <Wrench className="h-5 w-5" />
            {t('import.toolDefinitions')}
            <span className="text-sm font-normal text-muted-foreground">
              {t('wizard.descriptionOptional')}
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-3">
            <label className="flex-1">
              <input
                type="file"
                accept=".json"
                onChange={handleToolsFileSelect}
                className="hidden"
              />
              <Button variant="outline" size="sm" className="w-full" asChild>
                <span>
                  <Upload className="h-4 w-4 mr-2" />
                  {t('import.uploadToolsJson')}
                </span>
              </Button>
            </label>
            {toolsFileName && (
              <span className="text-sm text-muted-foreground font-mono">
                {toolsFileName}
              </span>
            )}
          </div>

          {tools.length > 0 && (
            <div className="space-y-2">
              {tools.map((tool, index) => (
                <div
                  key={tool.function.name}
                  className="flex items-center gap-3 rounded-md border border-border p-2"
                >
                  <Wrench className="h-4 w-4 text-muted-foreground shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-mono font-medium truncate">
                      {tool.function.name}
                    </p>
                    {tool.function.description && (
                      <p className="text-xs text-muted-foreground truncate">
                        {tool.function.description}
                      </p>
                    )}
                  </div>
                  <Badge variant="secondary" className="shrink-0">
                    {Object.keys(tool.function.parameters?.properties ?? {}).length || 0} params
                  </Badge>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 shrink-0"
                    onClick={() => removeTool(index)}
                  >
                    <X className="h-3 w-3" />
                  </Button>
                </div>
              ))}
            </div>
          )}

          <p className="text-xs text-muted-foreground">
            {t('import.toolsHint')}
          </p>
        </CardContent>
      </Card>

      {canExtract && (
        <Button
          onClick={() => extractMutation.mutate()}
          disabled={extractMutation.isPending}
          variant="outline"
          className="w-full"
        >
          {extractMutation.isPending ? (
            <>
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              {t('import.extracting')}
            </>
          ) : (
            <>
              <Variable className="h-4 w-4 mr-2" />
              {t('import.extractVariables')}
            </>
          )}
        </Button>
      )}

      {parseErrors.length > 0 && (
        <div className="rounded-md border border-destructive/50 bg-destructive/10 p-3">
          <div className="flex items-center gap-2 text-sm text-destructive">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <div>
              {parseErrors.map((err, i) => (
                <p key={i}>{err}</p>
              ))}
            </div>
          </div>
        </div>
      )}

      {variables.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <Variable className="h-5 w-5" />
              {t('import.detectedVariables')}
              <Badge variant="secondary">{variables.length}</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {variables.map((variable, index) => (
              <div
                key={variable.name}
                className="flex flex-col gap-2 rounded-md border border-border p-3"
              >
                <div className="flex items-center gap-3">
                  <code className="text-sm font-mono bg-muted px-2 py-0.5 rounded">
                    {'{{ ' + variable.name + ' }}'}
                  </code>
                  <div className="flex-1">
                    <Input
                      placeholder={t('import.variableDescriptionPlaceholder')}
                      value={variable.description}
                      onChange={(e) =>
                        updateVariable(index, { description: e.target.value })
                      }
                      className="h-8 text-sm"
                    />
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 shrink-0"
                    onClick={() => removeVariable(index)}
                  >
                    <X className="h-3 w-3" />
                  </Button>
                </div>
                <label className="flex items-center gap-2 text-xs ml-1">
                  <input
                    type="checkbox"
                    checked={variable.isAnchor}
                    onChange={(e) =>
                      updateVariable(index, { isAnchor: e.target.checked })
                    }
                    className="rounded border-input"
                  />
                  <span className="text-foreground">
                    {t('wizard.anchorVariable')}
                  </span>
                  <span className="text-muted-foreground">
                    {t('wizard.anchorPreserved')}
                  </span>
                </label>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {(variables.length > 0 || extractMutation.isSuccess) && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">{t('import.promptDetails')}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <label
                htmlFor="import-id"
                className="text-sm font-medium text-foreground"
              >
                {t('wizard.promptId')}
              </label>
              <Input
                id="import-id"
                placeholder={t('wizard.promptIdPlaceholder')}
                value={id}
                onChange={(e) => setId(e.target.value)}
              />
              {idTouched && !idValid && (
                <p className="text-sm text-destructive">
                  {t('wizard.promptIdError')}
                </p>
              )}
            </div>

            <div className="space-y-2">
              <label
                htmlFor="import-purpose"
                className="text-sm font-medium text-foreground"
              >
                {t('wizard.purposeLabel')}
              </label>
              <Input
                id="import-purpose"
                placeholder={t('wizard.purposePlaceholder')}
                value={purpose}
                onChange={(e) => setPurpose(e.target.value)}
              />
            </div>
          </CardContent>
        </Card>
      )}

      {canRegister && (
        <Button
          onClick={() => {
            setRegisterError(null)
            registerMutation.mutate()
          }}
          disabled={registerMutation.isPending}
          className="w-full"
          size="lg"
        >
          {registerMutation.isPending ? (
            <>
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              {t('import.registering')}
            </>
          ) : (
            <>
              <Save className="h-4 w-4 mr-2" />
              {t('import.registerPrompt')}
            </>
          )}
        </Button>
      )}

      {registerError && (
        <p className="text-sm text-destructive">{registerError}</p>
      )}
    </div>
  )
}
