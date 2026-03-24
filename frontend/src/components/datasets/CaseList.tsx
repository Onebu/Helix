import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  listCasesApiPromptsPromptIdDatasetGet,
  deleteCaseApiPromptsPromptIdDatasetCaseIdDelete,
} from '@/client/sdk.gen'
import type { TestCaseResponse } from '@/client/types.gen'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { FlaskConical, Sparkles } from 'lucide-react'
import { CaseEditor } from './CaseEditor'
import { CaseImport } from './CaseImport'
import { SynthesisDialog } from './SynthesisDialog'

function TierBadge({ tier }: { tier: string }) {
  switch (tier) {
    case 'critical':
      return <Badge variant="destructive">{tier}</Badge>
    case 'low':
      return <Badge variant="outline">{tier}</Badge>
    default:
      return <Badge variant="secondary">{tier}</Badge>
  }
}

function ScorerFlags({ expectedOutput }: { expectedOutput: Record<string, unknown> | null }) {
  if (!expectedOutput) return null
  const flags: React.ReactNode[] = []
  if (expectedOutput.require_content === true) {
    flags.push(
      <Badge key="rc" variant="outline" className="bg-emerald-500/10 text-emerald-400 border-emerald-500/20" title="Require Content — response must not be empty">
        RC
      </Badge>
    )
  }
  if (expectedOutput.match_args != null) {
    flags.push(
      <Badge key="ma" variant="outline" className="bg-blue-500/10 text-blue-400 border-blue-500/20" title="Match Args — response must call the expected tool">
        MA
      </Badge>
    )
  }
  if (expectedOutput.must_contain != null) {
    flags.push(
      <Badge key="mc" variant="outline" className="bg-amber-500/10 text-amber-400 border-amber-500/20" title="Must Contain — response must include specific text">
        MC
      </Badge>
    )
  }
  if (expectedOutput.behavior_criteria != null) {
    flags.push(
      <Badge key="bj" variant="outline" className="bg-purple-500/10 text-purple-400 border-purple-500/20" title="Behavior Judge — LLM evaluates against criteria">
        BJ
      </Badge>
    )
  }
  if (flags.length === 0) return null
  return <span className="flex gap-1">{flags}</span>
}

function CaseListSkeleton() {
  const { t } = useTranslation()
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t('datasets.name')}</TableHead>
          <TableHead>{t('datasets.tier')}</TableHead>
          <TableHead>{t('datasets.flags')}</TableHead>
          <TableHead>{t('datasets.tags')}</TableHead>
          <TableHead className="text-right">{t('datasets.actions')}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {[1, 2, 3].map((i, idx) => (
          <TableRow key={i} className={idx % 2 === 1 ? 'bg-muted/30' : ''}>
            <TableCell><Skeleton className="h-4 w-[150px]" /></TableCell>
            <TableCell><Skeleton className="h-5 w-16 rounded-full" /></TableCell>
            <TableCell><Skeleton className="h-5 w-10 rounded-full" /></TableCell>
            <TableCell><Skeleton className="h-4 w-[100px]" /></TableCell>
            <TableCell><Skeleton className="h-6 w-[80px] ml-auto" /></TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}

export function CaseList({ promptId }: { promptId: string }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [editorOpen, setEditorOpen] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [editingCase, setEditingCase] = useState<TestCaseResponse | undefined>(undefined)
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)
  const [synthDialogOpen, setSynthDialogOpen] = useState(false)

  const { data: cases, isLoading } = useQuery({
    queryKey: ['datasets', promptId],
    queryFn: () =>
      listCasesApiPromptsPromptIdDatasetGet({
        path: { prompt_id: promptId },
      }),
  })

  const deleteMutation = useMutation({
    mutationFn: (caseId: string) =>
      deleteCaseApiPromptsPromptIdDatasetCaseIdDelete({
        path: { prompt_id: promptId, case_id: caseId },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['datasets', promptId] })
      setConfirmDeleteId(null)
    },
  })

  const caseList = cases?.data ?? []

  if (isLoading) {
    return (
      <div>
        <div className="flex items-center justify-between mb-4">
          <Skeleton className="h-4 w-[100px]" />
          <div className="flex gap-2">
            <Skeleton className="h-8 w-[70px]" />
            <Skeleton className="h-8 w-[80px]" />
          </div>
        </div>
        <CaseListSkeleton />
      </div>
    )
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-muted-foreground">
          {t('datasets.testCases', { count: caseList.length })}
        </p>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => setSynthDialogOpen(true)}>
            <Sparkles className="h-4 w-4 mr-1" />
            {t('datasets.generateTests')}
          </Button>
          <Button variant="outline" size="sm" onClick={() => setImportOpen(true)}>
            {t('common.import')}
          </Button>
          <Button
            size="sm"
            onClick={() => {
              setEditingCase(undefined)
              setEditorOpen(true)
            }}
          >
            {t('datasets.addCase')}
          </Button>
        </div>
      </div>

      {/* Table or Empty State */}
      {caseList.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16">
          <div className="rounded-xl border-2 border-dashed border-border p-8 text-center max-w-md">
            <FlaskConical className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
            <h3 className="text-lg font-semibold text-foreground mb-2">{t('datasets.noTestCasesYet')}</h3>
            <p className="text-sm text-muted-foreground mb-4">
              {t('datasets.noTestCasesDescription')}
            </p>
            <Button
              onClick={() => {
                setEditingCase(undefined)
                setEditorOpen(true)
              }}
            >
              {t('datasets.addTestCase')}
            </Button>
          </div>
        </div>
      ) : (
        <div className="rounded-lg border border-border overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('datasets.name')}</TableHead>
                <TableHead>{t('datasets.tier')}</TableHead>
                <TableHead>{t('datasets.flags')}</TableHead>
                <TableHead>{t('datasets.tags')}</TableHead>
                <TableHead className="text-right">{t('datasets.actions')}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {caseList.map((tc, idx) => (
                <TableRow key={tc.id} className={idx % 2 === 1 ? 'bg-muted/30' : ''}>
                  <TableCell className="font-medium">{tc.name || tc.id}</TableCell>
                  <TableCell>
                    <TierBadge tier={tc.tier} />
                  </TableCell>
                  <TableCell>
                    <ScorerFlags expectedOutput={tc.expected_output} />
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {tc.tags?.map((tag) => (
                        <Badge key={tag} variant="secondary" className="text-xs font-normal">
                          {tag}
                        </Badge>
                      ))}
                    </div>
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex gap-2 justify-end">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          setEditingCase(tc)
                          setEditorOpen(true)
                        }}
                      >
                        {t('common.edit')}
                      </Button>
                      {confirmDeleteId === tc.id ? (
                        <span className="flex gap-1">
                          <Button
                            variant="destructive"
                            size="sm"
                            onClick={() => deleteMutation.mutate(tc.id)}
                          >
                            {t('common.confirm')}
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setConfirmDeleteId(null)}
                          >
                            {t('common.cancel')}
                          </Button>
                        </span>
                      ) : (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-destructive hover:text-destructive"
                          onClick={() => setConfirmDeleteId(tc.id)}
                        >
                          {t('common.delete')}
                        </Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Dialogs */}
      <CaseEditor
        promptId={promptId}
        existingCase={editingCase}
        open={editorOpen}
        onOpenChange={setEditorOpen}
      />
      <CaseImport
        promptId={promptId}
        open={importOpen}
        onOpenChange={setImportOpen}
      />
      <SynthesisDialog
        promptId={promptId}
        open={synthDialogOpen}
        onOpenChange={setSynthDialogOpen}
        onComplete={() => queryClient.invalidateQueries({ queryKey: ['datasets', promptId] })}
      />
    </div>
  )
}
