import { useTranslation } from 'react-i18next'
import type { GenerationData } from '../../types/evolution'
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from '@/components/ui/table'

interface GenerationTableProps {
  data: GenerationData[]
  isLive?: boolean
}

export default function GenerationTable({ data, isLive = false }: GenerationTableProps) {
  const { t } = useTranslation()
  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden overflow-x-auto">
      <div className="px-4 py-3 border-b border-border">
        <h3 className="text-sm font-semibold text-foreground">{t('evolution.generationDetails')}</h3>
      </div>
      {data.length === 0 ? (
        <div className="flex items-center justify-center py-12 gap-2">
          {isLive && (
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-primary"></span>
            </span>
          )}
          <p className="text-muted-foreground">{isLive ? t('evolution.evaluatingCandidates') : t('evolution.waitingForData')}</p>
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('evolution.generation')}</TableHead>
              <TableHead>{t('evolution.bestFitness')}</TableHead>
              <TableHead>{t('evolution.avgFitness')}</TableHead>
              <TableHead>{t('evolution.bestNorm')}</TableHead>
              <TableHead>{t('evolution.avgNorm')}</TableHead>
              <TableHead>{t('evolution.candidates')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.map((gen) => (
              <TableRow key={gen.generation}>
                <TableCell>{gen.label}</TableCell>
                <TableCell>{Number(gen.bestFitness ?? 0).toFixed(4)}</TableCell>
                <TableCell>{Number(gen.avgFitness ?? 0).toFixed(4)}</TableCell>
                <TableCell>{Number(gen.bestNormalized ?? 0).toFixed(4)}</TableCell>
                <TableCell>{Number(gen.avgNormalized ?? 0).toFixed(4)}</TableCell>
                <TableCell>{gen.candidatesEvaluated}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  )
}
