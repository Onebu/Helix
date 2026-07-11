import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ModelRoleSelector from '../components/evolution/ModelRoleSelector'
import { useModels } from '../hooks/useModels'

vi.mock('../hooks/useModels', () => ({ useModels: vi.fn() }))

const mockUseModels = vi.mocked(useModels)
const models = [
  {
    id: 'anthropic/claude-sonnet-4',
    name: 'Anthropic: Claude Sonnet 4',
    context_length: 1_000_000,
    input_price_per_mtok: 3,
    output_price_per_mtok: 15,
    provider: 'openrouter',
  },
  {
    id: 'google/gemini-2.5-flash',
    name: 'Google: Gemini 2.5 Flash',
    context_length: 1_000_000,
    input_price_per_mtok: 0.3,
    output_price_per_mtok: 2.5,
    provider: 'openrouter',
  },
  {
    id: 'openai/gpt-4o-mini',
    name: 'OpenAI: GPT-4o-mini',
    context_length: 128_000,
    input_price_per_mtok: 0.15,
    output_price_per_mtok: 0.6,
    provider: 'openrouter',
  },
]

function renderSelector(onModelChange = vi.fn(), model: string | null = null) {
  render(
    <ModelRoleSelector
      role="Meta"
      provider="openrouter"
      model={model}
      onProviderChange={vi.fn()}
      onModelChange={onModelChange}
    />,
  )
  return onModelChange
}

describe('ModelRoleSelector', () => {
  beforeEach(() => {
    mockUseModels.mockReturnValue({
      data: models,
      isLoading: false,
      isError: false,
    } as ReturnType<typeof useModels>)
  })

  it('opens with the complete provider model list and a focused search field', async () => {
    const user = userEvent.setup()
    renderSelector()

    await user.click(screen.getByTestId('meta-model'))

    expect(screen.getByRole('combobox', { name: 'Search models' })).toHaveFocus()
    expect(screen.getAllByRole('option')).toHaveLength(models.length + 1)
    expect(screen.getByRole('option', { name: /Google: Gemini 2\.5 Flash/i })).toBeVisible()
    expect(screen.getByText('Google: Gemini 2.5 Flash')).toHaveClass('whitespace-normal')
  })

  it('names each role control and keeps mobile triggers touch-friendly', () => {
    renderSelector()

    expect(screen.getByTestId('meta-provider')).toHaveAccessibleName('Meta provider: OpenRouter')
    expect(screen.getByTestId('meta-model')).toHaveAccessibleName('Meta model: Server default')
    expect(screen.getByTestId('meta-provider')).toHaveClass('h-10', 'sm:h-8')
    expect(screen.getByTestId('meta-model')).toHaveClass('h-10', 'sm:h-8')
  })

  it('includes the selected model in the trigger accessible name', () => {
    renderSelector(vi.fn(), 'google/gemini-2.5-flash')

    expect(screen.getByTestId('meta-model')).toHaveAccessibleName(
      'Meta model: Google: Gemini 2.5 Flash',
    )
  })

  it('filters by model name or provider model ID', async () => {
    const user = userEvent.setup()
    renderSelector()

    await user.click(screen.getByTestId('meta-model'))
    const search = screen.getByRole('combobox', { name: 'Search models' })
    await user.type(search, 'gemini 2.5')

    expect(screen.getByRole('option', { name: /Google: Gemini 2\.5 Flash/i })).toBeVisible()
    expect(screen.queryByRole('option', { name: /Claude Sonnet/i })).not.toBeInTheDocument()

    await user.clear(search)
    await user.type(search, 'openai/gpt-4o-mini')
    expect(screen.getByRole('option', { name: /OpenAI: GPT-4o-mini/i })).toBeVisible()
  })

  it('shows an empty result and selects the exact model ID', async () => {
    const user = userEvent.setup()
    const onModelChange = renderSelector()

    await user.click(screen.getByTestId('meta-model'))
    const search = screen.getByRole('combobox', { name: 'Search models' })
    await user.type(search, 'no-such-model')
    expect(screen.getByRole('status')).toHaveTextContent('No models match your search.')

    await user.clear(search)
    await user.type(search, 'gemini 2.5 flash')
    await user.click(screen.getByRole('option', { name: /Google: Gemini 2\.5 Flash/i }))

    expect(onModelChange).toHaveBeenCalledWith('google/gemini-2.5-flash')
    expect(screen.queryByRole('combobox', { name: 'Search models' })).not.toBeInTheDocument()
  })

  it('navigates and selects filtered results from the keyboard without tabbing every option', async () => {
    const user = userEvent.setup()
    const onModelChange = renderSelector()

    await user.click(screen.getByTestId('meta-model'))
    const search = screen.getByLabelText('Search models')
    await user.type(search, 'gemini')

    const option = screen.getByRole('option', { name: /Google: Gemini 2\.5 Flash/i })
    expect(search).toHaveAttribute('aria-activedescendant', option.id)
    expect(option).toHaveAttribute('tabindex', '-1')

    await user.keyboard('{ArrowDown}{Enter}')
    expect(onModelChange).toHaveBeenCalledWith('google/gemini-2.5-flash')
  })
})
