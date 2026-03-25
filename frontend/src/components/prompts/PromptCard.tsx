import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { FileText } from 'lucide-react'

interface PromptCardProps {
  id: string
  purpose: string
  variableCount: number
  anchorCount: number
}

export function PromptCard({ id, purpose, variableCount, anchorCount }: PromptCardProps) {
  const { t } = useTranslation()

  return (
    <Link to={`/prompts/${id}`} className="group">
      <Card className="relative overflow-hidden rounded-lg border border-border bg-card text-card-foreground shadow-sm transition-[box-shadow,border-color] duration-300 cursor-pointer group-hover:shadow-lg group-hover:shadow-primary/5 group-hover:border-primary/50">
        <div className="absolute inset-0 rounded-lg bg-gradient-to-r from-primary/10 via-primary/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300 pointer-events-none" />
        <CardHeader>
          <div className="flex items-start gap-2">
            <FileText className="h-4 w-4 text-primary shrink-0 mt-0.5" />
            <CardTitle className="text-base font-semibold">{id}</CardTitle>
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
