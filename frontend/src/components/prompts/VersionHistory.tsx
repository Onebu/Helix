import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  listVersionsApiPromptsPromptIdVersionsGet,
  activateVersionApiPromptsPromptIdVersionsVersionActivatePut,
} from '@/client/sdk.gen'
import type { PromptVersionResponse } from '@/client/types.gen'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import VersionDiffViewer from './VersionDiffViewer'

interface VersionHistoryProps {
  promptId: string
}

export default function VersionHistory({ promptId }: VersionHistoryProps) {
  const queryClient = useQueryClient()
  const [expandedVersion, setExpandedVersion] = useState<number | null>(null)
  const [selectedForDiff, setSelectedForDiff] = useState<Set<number>>(new Set())
  const [showDiff, setShowDiff] = useState(false)

  const { data: versionsResp, isLoading } = useQuery({
    queryKey: ['prompt-versions', promptId],
    queryFn: () =>
      listVersionsApiPromptsPromptIdVersionsGet({
        path: { prompt_id: promptId },
      }),
    enabled: !!promptId,
  })

  const versions = useMemo(() => {
    const list = (versionsResp?.data ?? []) as PromptVersionResponse[]
    // API returns ascending order; display newest first
    return [...list].reverse()
  }, [versionsResp])

  const activateMutation = useMutation({
    mutationFn: (version: number) =>
      activateVersionApiPromptsPromptIdVersionsVersionActivatePut({
        path: { prompt_id: promptId, version },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['prompt-versions', promptId] })
      queryClient.invalidateQueries({ queryKey: ['prompts', promptId] })
    },
  })

  function toggleExpand(version: number) {
    setExpandedVersion((prev) => (prev === version ? null : version))
  }

  function toggleDiffSelection(version: number) {
    setSelectedForDiff((prev) => {
      const next = new Set(prev)
      if (next.has(version)) {
        next.delete(version)
      } else {
        // Allow max 2 selections
        if (next.size >= 2) {
          // Replace the oldest selection
          const [first] = next
          next.delete(first)
        }
        next.add(version)
      }
      return next
    })
    setShowDiff(false)
  }

  // Find the two selected versions for diff comparison
  const diffVersions = useMemo(() => {
    if (selectedForDiff.size !== 2) return null
    const [a, b] = Array.from(selectedForDiff).sort((x, y) => x - y)
    const fromVer = versions.find((v) => v.version === a)
    const toVer = versions.find((v) => v.version === b)
    if (!fromVer || !toVer) return null
    return { from: fromVer, to: toVer }
  }, [selectedForDiff, versions])

  function formatDate(dateStr: string): string {
    try {
      const date = new Date(dateStr)
      const now = new Date()
      const diffMs = now.getTime() - date.getTime()
      const diffMins = Math.floor(diffMs / 60000)
      const diffHours = Math.floor(diffMs / 3600000)
      const diffDays = Math.floor(diffMs / 86400000)

      if (diffMins < 1) return 'just now'
      if (diffMins < 60) return `${diffMins}m ago`
      if (diffHours < 24) return `${diffHours}h ago`
      if (diffDays < 7) return `${diffDays}d ago`
      return date.toLocaleDateString()
    } catch {
      return dateStr
    }
  }

  if (isLoading) {
    return (
      <div className="text-sm text-muted-foreground">Loading versions...</div>
    )
  }

  if (versions.length === 0) {
    return (
      <div className="text-sm text-muted-foreground">No versions found.</div>
    )
  }

  return (
    <div className="space-y-3">
      {/* Version list */}
      {versions.map((ver) => (
        <div
          key={ver.version}
          className="rounded-lg border border-border bg-card/50 overflow-hidden"
        >
          {/* Version row header */}
          <div className="flex items-center gap-3 px-4 py-3">
            {/* Diff checkbox — only show when there are 2+ versions to compare */}
            {versions.length >= 2 && (
              <input
                type="checkbox"
                checked={selectedForDiff.has(ver.version)}
                onChange={() => toggleDiffSelection(ver.version)}
                className="h-4 w-4 rounded border-border bg-secondary text-success focus:ring-success/50"
                title="Select for diff comparison"
              />
            )}

            {/* Version label */}
            <Badge variant="secondary" className="font-mono text-xs">
              v{ver.version}
            </Badge>

            {/* Active badge */}
            {ver.is_active && (
              <Badge className="bg-success/10 text-success border-success/20">
                Active
              </Badge>
            )}

            {/* Timestamp */}
            <span className="text-xs text-muted-foreground">
              {formatDate(ver.created_at)}
            </span>

            {/* Actions */}
            <div className="ml-auto flex items-center gap-2">
              <Button
                variant="ghost"
                size="sm"
                className="text-xs"
                onClick={() => toggleExpand(ver.version)}
              >
                {expandedVersion === ver.version ? 'Hide' : 'View'}
              </Button>
              {!ver.is_active && (
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-xs text-success hover:text-success/80"
                  onClick={() => activateMutation.mutate(ver.version)}
                  disabled={activateMutation.isPending}
                >
                  Activate
                </Button>
              )}
            </div>
          </div>

          {/* Expanded template view */}
          {expandedVersion === ver.version && (
            <div className="border-t border-border px-4 py-3">
              <pre className="font-mono text-xs leading-relaxed text-muted-foreground overflow-x-auto whitespace-pre-wrap max-h-96 overflow-y-auto">
                {ver.template}
              </pre>
            </div>
          )}
        </div>
      ))}

      {/* Compare button (when exactly 2 versions selected) */}
      {selectedForDiff.size === 2 && (
        <div className="flex justify-center">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowDiff(!showDiff)}
          >
            {showDiff ? 'Hide Comparison' : 'Compare Selected Versions'}
          </Button>
        </div>
      )}

      {/* Inline diff viewer */}
      {showDiff && diffVersions && (
        <VersionDiffViewer
          fromTemplate={diffVersions.from.template}
          toTemplate={diffVersions.to.template}
          fromLabel={`v${diffVersions.from.version}`}
          toLabel={`v${diffVersions.to.version}`}
        />
      )}
    </div>
  )
}
