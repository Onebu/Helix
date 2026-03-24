import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import PromptList from '../components/prompts/PromptList'
import PromptDetail from '../components/prompts/PromptDetail'

// Mock Monaco editor
vi.mock('@monaco-editor/react', () => ({
  default: (props: { value?: string }) => (
    <div data-testid="monaco-editor">{props.value}</div>
  ),
}))

// Mock SDK
vi.mock('../client/sdk.gen', () => ({
  listPromptsApiPromptsGet: vi.fn(),
  getPromptApiPromptsPromptIdGet: vi.fn(),
  listCasesApiPromptsPromptIdDatasetGet: vi.fn(),
}))

import {
  listPromptsApiPromptsGet,
  getPromptApiPromptsPromptIdGet,
  listCasesApiPromptsPromptIdDatasetGet,
} from '../client/sdk.gen'

const mockListPrompts = vi.mocked(listPromptsApiPromptsGet)
const mockGetPrompt = vi.mocked(getPromptApiPromptsPromptIdGet)
const mockListCases = vi.mocked(listCasesApiPromptsPromptIdDatasetGet)

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}

const samplePrompts = [
  {
    id: 'ivr-automotor',
    purpose: 'IVR call handling for auto dealership',
    template_variables: ['customer_name', 'language'],
    anchor_variables: ['greeting'],
  },
  {
    id: 'pizza-ivr',
    purpose: 'Pizza ordering IVR',
    template_variables: ['menu'],
    anchor_variables: [],
  },
]

describe('PromptList', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders prompts from API', async () => {
    mockListPrompts.mockResolvedValue({ data: samplePrompts } as never)

    renderWithProviders(<PromptList />)

    await waitFor(() => {
      expect(screen.getByText('ivr-automotor')).toBeInTheDocument()
      expect(screen.getByText('pizza-ivr')).toBeInTheDocument()
    })
  })

  it('filters by search input', async () => {
    mockListPrompts.mockResolvedValue({ data: samplePrompts } as never)
    const user = userEvent.setup()

    renderWithProviders(<PromptList />)

    await waitFor(() => {
      expect(screen.getByText('ivr-automotor')).toBeInTheDocument()
    })

    await user.type(screen.getByPlaceholderText('Search prompts...'), 'pizza')

    expect(screen.queryByText('ivr-automotor')).not.toBeInTheDocument()
    expect(screen.getByText('pizza-ivr')).toBeInTheDocument()
  })

  it('shows loading state with skeleton cards', () => {
    mockListPrompts.mockReturnValue(new Promise(() => {}) as never)

    renderWithProviders(<PromptList />)

    // Loading state now uses skeleton cards instead of text
    // The search input is rendered but disabled during loading
    expect(screen.getByPlaceholderText('Search prompts...')).toBeDisabled()
  })

  it('shows empty state when no prompts match filter', async () => {
    mockListPrompts.mockResolvedValue({ data: samplePrompts } as never)
    const user = userEvent.setup()

    renderWithProviders(<PromptList />)

    await waitFor(() => {
      expect(screen.getByText('ivr-automotor')).toBeInTheDocument()
    })

    await user.type(screen.getByPlaceholderText('Search prompts...'), 'nonexistent')

    expect(screen.getByText('No prompts match your search.')).toBeInTheDocument()
  })

  it('shows empty state when no prompts exist', async () => {
    mockListPrompts.mockResolvedValue({ data: [] } as never)

    renderWithProviders(<PromptList />)

    await waitFor(() => {
      expect(screen.getByText('No prompts yet')).toBeInTheDocument()
    })
  })
})

describe('PromptDetail', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Default: no test cases
    mockListCases.mockResolvedValue({ data: [] } as never)
  })

  it('renders template preview and variable schema', async () => {
    mockGetPrompt.mockResolvedValue({
      data: {
        id: 'ivr-automotor',
        purpose: 'IVR call handling',
        template_variables: ['customer_name'],
        anchor_variables: ['greeting'],
        template: 'Hello {{ customer_name }}',
        tools: null,
        variable_definitions: [
          { name: 'customer_name', var_type: 'string', is_anchor: false },
          { name: 'greeting', var_type: 'string', is_anchor: true },
        ],
      },
    } as never)

    renderWithProviders(<PromptDetail promptId="ivr-automotor" />)

    await waitFor(() => {
      // Template preview shows the template text (variable highlighted in its own span)
      expect(screen.getByText('Hello')).toBeInTheDocument()
      expect(screen.getByText('{{ customer_name }}')).toBeInTheDocument()
      // Variables & Schema section shows variable names
      expect(screen.getByText('customer_name')).toBeInTheDocument()
      expect(screen.getByText('greeting')).toBeInTheDocument()
      // Anchor badge shown for greeting
      expect(screen.getByText('anchor')).toBeInTheDocument()
    })
  })

  it('renders tools section with formatted tool cards', async () => {
    mockGetPrompt.mockResolvedValue({
      data: {
        id: 'tool-prompt',
        purpose: 'Tool test',
        template_variables: [],
        anchor_variables: [],
        template: 'Use tools',
        tools: [
          {
            type: 'function',
            function: {
              name: 'lookup_customer',
              description: 'Look up a customer by ID',
              parameters: {
                type: 'object',
                properties: {
                  customer_id: { type: 'string', description: 'The customer ID' },
                },
                required: ['customer_id'],
              },
            },
          },
        ],
        variable_definitions: [],
      },
    } as never)

    renderWithProviders(<PromptDetail promptId="tool-prompt" />)

    await waitFor(() => {
      expect(screen.getByText('Tools (1)')).toBeInTheDocument()
      expect(screen.getByText('lookup_customer')).toBeInTheDocument()
      expect(screen.getByText('Look up a customer by ID')).toBeInTheDocument()
      expect(screen.getByText('customer_id')).toBeInTheDocument()
      expect(screen.getByText('required')).toBeInTheDocument()
    })
  })

  it('shows no-tools message when tools is empty', async () => {
    mockGetPrompt.mockResolvedValue({
      data: {
        id: 'no-tools',
        purpose: 'No tools',
        template_variables: [],
        anchor_variables: [],
        template: 'No tools here',
        tools: [],
        variable_definitions: [],
      },
    } as never)

    renderWithProviders(<PromptDetail promptId="no-tools" />)

    await waitFor(() => {
      expect(screen.getByText('No tools defined for this prompt.')).toBeInTheDocument()
    })
  })

  it('shows test case summary when cases exist', async () => {
    mockGetPrompt.mockResolvedValue({
      data: {
        id: 'with-cases',
        purpose: 'Test',
        template_variables: [],
        anchor_variables: [],
        template: 'Test',
        tools: null,
        variable_definitions: [],
      },
    } as never)
    mockListCases.mockResolvedValue({
      data: [
        { id: '1', tier: 'critical', name: 'c1' },
        { id: '2', tier: 'normal', name: 'c2' },
        { id: '3', tier: 'normal', name: 'c3' },
        { id: '4', tier: 'low', name: 'c4' },
      ],
    } as never)

    renderWithProviders(<PromptDetail promptId="with-cases" />)

    await waitFor(() => {
      expect(screen.getByText('4 test cases')).toBeInTheDocument()
      expect(screen.getByText('1 critical, 2 normal, 1 low')).toBeInTheDocument()
    })
  })

  it('shows loading state with skeleton', () => {
    mockGetPrompt.mockReturnValue(new Promise(() => {}) as never)

    const { container } = renderWithProviders(<PromptDetail promptId="test" />)

    // Loading state now uses skeleton cards instead of "Loading prompt..." text
    // Look for skeleton elements (divs with animate-pulse class)
    const skeletons = container.querySelectorAll('.animate-pulse')
    expect(skeletons.length).toBeGreaterThan(0)
  })
})
