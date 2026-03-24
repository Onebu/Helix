import { useTranslation } from 'react-i18next'
import { useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { StepIndicator } from './StepIndicator'
import { PurposeStep } from './PurposeStep'
import { VariablesStep } from './VariablesStep'
import { ConstraintsStep } from './ConstraintsStep'
import { ReviewStep } from './ReviewStep'

export interface WizardVariable {
  name: string
  varType: string
  description: string
  isAnchor: boolean
  itemsSchema?: WizardVariable[]
  examples?: string // Comma-separated for simple types, JSON for complex
}

export interface WizardData {
  id: string
  purpose: string
  description: string
  variables: WizardVariable[]
  constraints: string
  behaviors: string
  includeTools: boolean
  toolDescriptions: string
}

// STEP_LABELS moved inside component for i18n

const SLUG_PATTERN = /^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/

function isStepValid(step: number, data: WizardData): boolean {
  switch (step) {
    case 0:
      return SLUG_PATTERN.test(data.id) && data.purpose.trim().length > 0
    case 1:
      return true // variables are optional
    case 2:
      return true // constraints are optional
    case 3:
      return true // review step has its own buttons
    default:
      return false
  }
}

const INITIAL_DATA: WizardData = {
  id: '',
  purpose: '',
  description: '',
  variables: [],
  constraints: '',
  behaviors: '',
  includeTools: false,
  toolDescriptions: '',
}

export function WizardFlow() {
  const { t } = useTranslation()
  const STEP_LABELS = [t('wizard.purpose'), t('wizard.variables'), t('wizard.constraints'), t('wizard.review')]
  const [step, setStep] = useState(0)
  const [data, setData] = useState<WizardData>(INITIAL_DATA)
  const [yaml, setYaml] = useState<string | null>(null)

  const handleNext = () => {
    if (step < STEP_LABELS.length - 1 && isStepValid(step, data)) {
      // Filter out empty variables and empty sub-fields on transition from variables step
      if (step === 1) {
        setData((prev) => ({
          ...prev,
          variables: prev.variables
            .filter((v) => v.name.trim() !== '')
            .map((v) => ({
              ...v,
              itemsSchema: v.itemsSchema
                ? v.itemsSchema.filter((sf) => sf.name.trim() !== '')
                : undefined,
            })),
        }))
      }
      setStep(step + 1)
    }
  }

  const handleBack = () => {
    if (step > 0) {
      setStep(step - 1)
    }
  }

  return (
    <div className="max-w-2xl mx-auto">
      <StepIndicator steps={STEP_LABELS} current={step} />

      {step === 0 && <PurposeStep data={data} onChange={setData} />}
      {step === 1 && <VariablesStep data={data} onChange={setData} />}
      {step === 2 && <ConstraintsStep data={data} onChange={setData} />}
      {step === 3 && <ReviewStep data={data} yaml={yaml} onYamlChange={setYaml} />}

      {/* Navigation buttons (not on Review step - it has its own buttons) */}
      {step < 3 && (
        <div className="flex justify-between mt-6">
          {step > 0 ? (
            <Button
              variant="outline"
              onClick={handleBack}
            >
              <ChevronLeft className="h-4 w-4 mr-1" />
              {t('common.back')}
            </Button>
          ) : (
            <div />
          )}
          <Button
            onClick={handleNext}
            disabled={!isStepValid(step, data)}
          >
            {t('common.next')}
            <ChevronRight className="h-4 w-4 ml-1" />
          </Button>
        </div>
      )}

      {/* Back button on Review step */}
      {step === 3 && (
        <div className="flex justify-start mt-6">
          <Button variant="outline" onClick={handleBack}>
            <ChevronLeft className="h-4 w-4 mr-1" />
            {t('common.back')}
          </Button>
        </div>
      )}
    </div>
  )
}
