import { useTranslation } from 'react-i18next'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import type { WizardData } from './WizardFlow'
import { SLUG_PATTERN } from './constants'

interface PurposeStepProps {
  data: WizardData
  onChange: (data: WizardData) => void
}

export function PurposeStep({ data, onChange }: PurposeStepProps) {
  const { t } = useTranslation()
  const idTouched = data.id.length > 0
  const idValid = SLUG_PATTERN.test(data.id)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">{t('wizard.purpose')}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <label htmlFor="wizard-id" className="text-sm font-medium text-foreground">
            {t('wizard.promptId')}
          </label>
          <Input
            id="wizard-id"
            placeholder={t('wizard.promptIdPlaceholder')}
            value={data.id}
            onChange={(e) => onChange({ ...data, id: e.target.value })}
          />
          {idTouched && !idValid && (
            <p className="text-sm text-destructive">
              {t('wizard.promptIdError')}
            </p>
          )}
        </div>

        <div className="space-y-2">
          <label htmlFor="wizard-purpose" className="text-sm font-medium text-foreground">
            {t('wizard.purposeLabel')}
          </label>
          <Input
            id="wizard-purpose"
            placeholder={t('wizard.purposePlaceholder')}
            value={data.purpose}
            onChange={(e) => onChange({ ...data, purpose: e.target.value })}
          />
        </div>

        <div className="space-y-2">
          <label htmlFor="wizard-description" className="text-sm font-medium text-foreground">
            {t('wizard.descriptionLabel')} <span className="text-muted-foreground font-normal">{t('wizard.descriptionOptional')}</span>
          </label>
          <Textarea
            id="wizard-description"
            placeholder={t('wizard.descriptionPlaceholder')}
            value={data.description}
            onChange={(e) => onChange({ ...data, description: e.target.value })}
            rows={3}
          />
        </div>
      </CardContent>
    </Card>
  )
}
