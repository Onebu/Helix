import type { ReactNode } from 'react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'

interface EvolutionWorkspaceProps {
  progress: ReactNode
  lineage: ReactNode
  cases: ReactNode
}

export default function EvolutionWorkspace({ progress, lineage, cases }: EvolutionWorkspaceProps) {
  const { t } = useTranslation()
  const [activeTab, setActiveTab] = useState('progress')

  return (
    <Tabs value={activeTab} onValueChange={setActiveTab} className="min-w-0">
      <TabsList className="h-auto min-h-[3.25rem] w-full justify-start overflow-x-auto overflow-y-hidden whitespace-nowrap">
        <TabsTrigger className="min-h-11 shrink-0" value="progress">{t('evolution.progress')}</TabsTrigger>
        <TabsTrigger className="min-h-11 shrink-0" value="lineage">{t('evolution.lineage')}</TabsTrigger>
        <TabsTrigger className="min-h-11 shrink-0" value="cases">{t('evolution.cases')}</TabsTrigger>
      </TabsList>
      <TabsContent value="progress" className="mt-4">{progress}</TabsContent>
      <TabsContent value="lineage" className="mt-4">{lineage}</TabsContent>
      <TabsContent value="cases" className="mt-4">{cases}</TabsContent>
    </Tabs>
  )
}
