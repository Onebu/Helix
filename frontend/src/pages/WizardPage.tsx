import { useTranslation } from 'react-i18next'
import { Wand2, Upload } from 'lucide-react'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { WizardFlow } from '@/components/wizard/WizardFlow'
import { ImportFlow } from '@/components/wizard/ImportFlow'

export default function WizardPage() {
  const { t } = useTranslation()

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-foreground">{t('wizard.title')}</h1>
        <p className="text-muted-foreground text-sm mt-1">
          {t('wizard.subtitle')}
        </p>
      </div>

      <Tabs defaultValue="wizard" className="max-w-2xl mx-auto">
        <TabsList className="grid w-full grid-cols-2 mb-6">
          <TabsTrigger value="wizard" className="gap-2">
            <Wand2 className="h-4 w-4" />
            {t('wizard.createWithWizard')}
          </TabsTrigger>
          <TabsTrigger value="import" className="gap-2">
            <Upload className="h-4 w-4" />
            {t('import.importTemplate')}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="wizard">
          <WizardFlow />
        </TabsContent>
        <TabsContent value="import">
          <ImportFlow />
        </TabsContent>
      </Tabs>
    </div>
  )
}
