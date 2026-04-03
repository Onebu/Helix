import { useState, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { importCasesApiPromptsPromptIdDatasetImportPost } from '@/client/sdk.gen'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'

interface CaseImportProps {
  promptId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function CaseImport({ promptId, open, onOpenChange }: CaseImportProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [importedCount, setImportedCount] = useState<number | null>(null)
  const [parsedErrorMessage, setParsedErrorMessage] = useState<string | null>(null)

  const importMutation = useMutation({
    mutationFn: (file: File) =>
      importCasesApiPromptsPromptIdDatasetImportPost({
        path: { prompt_id: promptId },
        body: { file },
      }),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['datasets', promptId] })
      const count = Array.isArray(result.data) ? result.data.length : 0
      setImportedCount(count)
      setParsedErrorMessage(null)
    },
    onError: (error: unknown) => {
      let message = t('datasets.importFailed')
      try {
        const err = error as Record<string, unknown>
        if (err.body && typeof err.body === 'object') {
          const body = err.body as Record<string, unknown>
          if (typeof body.detail === 'string') {
            message = body.detail
          } else if (Array.isArray(body.detail)) {
            message = (body.detail as Array<{ msg: string }>)
              .map((e) => e.msg)
              .join('; ')
          }
        } else if (typeof err.message === 'string') {
          message = err.message
        }
      } catch {
        // Fall through to default message
      }
      // Rephrase common backend ValueError message
      if (message.includes('Expected a list of cases')) {
        message = t('datasets.invalidFileFormat')
      }
      setParsedErrorMessage(message)
    },
  })

  function handleImport() {
    if (!selectedFile) return
    importMutation.mutate(selectedFile)
  }

  function handleClose() {
    setSelectedFile(null)
    setImportedCount(null)
    setParsedErrorMessage(null)
    importMutation.reset()
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={(isOpen) => { if (!isOpen) handleClose(); else onOpenChange(true) }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{t('datasets.importTestCases')}</DialogTitle>
          <DialogDescription>{t('datasets.importDescription')}</DialogDescription>
        </DialogHeader>

        {importedCount !== null ? (
          <div className="text-center py-4">
            <p className="text-success text-sm mb-4">
              {t('datasets.importSuccess', { count: importedCount })}
            </p>
            <Button onClick={handleClose}>{t('datasets.done')}</Button>
          </div>
        ) : (
          <>
            <div
              className="border-2 border-dashed border-border rounded-lg p-8 text-center cursor-pointer hover:border-primary/50 transition-colors"
              onClick={() => fileRef.current?.click()}
            >
              <input
                ref={fileRef}
                type="file"
                accept=".json,.yaml,.yml"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0] || null
                  setSelectedFile(file)
                  setParsedErrorMessage(null)
                  importMutation.reset()
                }}
              />
              {selectedFile ? (
                <p className="text-foreground text-sm">{selectedFile.name}</p>
              ) : (
                <p className="text-muted-foreground text-sm">
                  {t('datasets.clickToSelectFile')}
                </p>
              )}
            </div>

            {parsedErrorMessage && (
              <div className="mt-2 rounded-md border border-destructive/50 bg-destructive/10 p-3 space-y-1">
                {selectedFile && (
                  <p className="text-sm font-medium text-destructive">
                    {t('datasets.failedToImport', { name: selectedFile.name })}
                  </p>
                )}
                <p className="text-sm text-destructive/90">
                  {parsedErrorMessage}
                </p>
              </div>
            )}

            <div className="flex justify-end gap-2 mt-4">
              <Button variant="outline" onClick={handleClose}>
                {t('common.cancel')}
              </Button>
              <Button
                onClick={handleImport}
                disabled={!selectedFile || importMutation.isPending}
              >
                {importMutation.isPending ? t('datasets.importing') : t('common.import')}
              </Button>
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
