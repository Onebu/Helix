import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useQueryClient } from '@tanstack/react-query'
import { deletePromptApiPromptsPromptIdDelete } from '@/client/sdk.gen'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { FileText, Trash2 } from 'lucide-react'

interface PromptCardProps {
  id: string
  purpose: string
  variableCount: number
  anchorCount: number
}

export function PromptCard({ id, purpose, variableCount, anchorCount }: PromptCardProps) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const handleDelete = async (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (!confirming) {
      setConfirming(true)
      return
    }
    setDeleting(true)
    try {
      await deletePromptApiPromptsPromptIdDelete({ path: { prompt_id: id } })
      await queryClient.invalidateQueries({ queryKey: ['prompts'] })
    } finally {
      setDeleting(false)
      setConfirming(false)
    }
  }

  const cancelDelete = (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setConfirming(false)
  }

  return (
    <Link to={`/prompts/${id}`} className="group">
      <Card className="relative overflow-hidden rounded-lg border border-border bg-card text-card-foreground shadow-sm transition-[box-shadow,border-color] duration-300 cursor-pointer group-hover:shadow-lg group-hover:shadow-primary/5 group-hover:border-primary/50">
        <div className="absolute inset-0 rounded-lg bg-gradient-to-r from-primary/10 via-primary/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none" />
        <CardHeader>
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-start gap-2 min-w-0">
              <FileText className="h-4 w-4 text-primary shrink-0 mt-0.5" />
              <CardTitle className="text-base font-semibold">{id}</CardTitle>
            </div>
            {confirming ? (
              <span className="flex gap-1 shrink-0" onClick={(e) => e.preventDefault()}>
                <Button variant="destructive" size="sm" className="h-6 text-xs px-2" onClick={handleDelete} disabled={deleting}>
                  {t('common.confirm')}
                </Button>
                <Button variant="ghost" size="sm" className="h-6 text-xs px-2" onClick={cancelDelete}>
                  {t('common.cancel')}
                </Button>
              </span>
            ) : (
              <button
                onClick={handleDelete}
                className="opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-destructive p-1 shrink-0"
                title={t('common.delete')}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
          <CardDescription className="line-clamp-2">{purpose}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex gap-2">
            <Badge variant="secondary">{t('prompts.vars', { count: variableCount })}</Badge>
            <Badge variant="outline">{t('prompts.anchors', { count: anchorCount })}</Badge>
          </div>
        </CardContent>
      </Card>
    </Link>
  )
}
