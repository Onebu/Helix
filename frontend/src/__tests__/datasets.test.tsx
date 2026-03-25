import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { CaseList } from '../components/datasets/CaseList'
import { CaseEditor } from '../components/datasets/CaseEditor'
import { CaseImport } from '../components/datasets/CaseImport'
import type { TestCaseResponse } from '../client/types.gen'

// Mock Sheet for inline rendering (Radix portals don't work well in jsdom)
vi.mock('@/components/ui/sheet', () => ({
  Sheet: ({ children, open }: { children: React.ReactNode; open: boolean }) =>
    open ? <div data-testid="sheet">{children}</div> : null,
  SheetContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SheetHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SheetTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
  SheetDescription: ({ children }: { children: React.ReactNode }) => <p>{children}</p>,
}))

// Mock Dialog for inline rendering
vi.mock('@/components/ui/dialog', () => ({
  Dialog: ({ children, open }: { children: React.ReactNode; open: boolean }) =>
    open ? <div data-testid="dialog">{children}</div> : null,
  DialogContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
  DialogDescription: ({ children }: { children: React.ReactNode }) => <p>{children}</p>,
}))

// Mock the SDK functions
vi.mock('../client/sdk.gen', () => ({
  listCasesApiPromptsPromptIdDatasetGet: vi.fn(),
  deleteCaseApiPromptsPromptIdDatasetCaseIdDelete: vi.fn(),
  addCaseApiPromptsPromptIdDatasetPost: vi.fn(),
  updateCaseApiPromptsPromptIdDatasetCaseIdPut: vi.fn(),
  importCasesApiPromptsPromptIdDatasetImportPost: vi.fn(),
}))

import {
  listCasesApiPromptsPromptIdDatasetGet,
  deleteCaseApiPromptsPromptIdDatasetCaseIdDelete,
  addCaseApiPromptsPromptIdDatasetPost,
  importCasesApiPromptsPromptIdDatasetImportPost,
} from '../client/sdk.gen'

const mockListCases = vi.mocked(listCasesApiPromptsPromptIdDatasetGet)
const mockDeleteCase = vi.mocked(deleteCaseApiPromptsPromptIdDatasetCaseIdDelete)
const mockAddCase = vi.mocked(addCaseApiPromptsPromptIdDatasetPost)
const mockImport = vi.mocked(importCasesApiPromptsPromptIdDatasetImportPost)

const mockCases: TestCaseResponse[] = [
  {
    id: 'case-1',
    name: 'Transfer to sales',
    description: 'Test sales transfer',
    tier: 'critical',
    variables: { intent: 'sales' },
    expected_output: { require_content: true, tool_name: 'transfer' },
    tags: ['transfer', 'sales'],
    chat_history: [{ role: 'user', content: 'I want to buy' }],
  },
  {
    id: 'case-2',
    name: 'Greeting test',
    description: null,
    tier: 'normal',
    variables: {},
    expected_output: { match_args: 'subset' },
    tags: [],
    chat_history: [],
  },
]

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('CaseList', () => {
  it('renders test cases with tier badges', async () => {
    mockListCases.mockResolvedValue({ data: mockCases } as never)

    renderWithProviders(<CaseList promptId="test-prompt" />)

    await waitFor(() => {
      expect(screen.getByText('Transfer to sales')).toBeInTheDocument()
    })
    expect(screen.getByText('Greeting test')).toBeInTheDocument()
    expect(screen.getByText('critical')).toBeInTheDocument()
    expect(screen.getByText('normal')).toBeInTheDocument()
  })

  it('shows scorer flag indicators', async () => {
    mockListCases.mockResolvedValue({ data: mockCases } as never)

    renderWithProviders(<CaseList promptId="test-prompt" />)

    await waitFor(() => {
      expect(screen.getByText('RC')).toBeInTheDocument()
    })
    expect(screen.getByText('MA')).toBeInTheDocument()
  })

  it('shows empty state when no cases', async () => {
    mockListCases.mockResolvedValue({ data: [] } as never)

    renderWithProviders(<CaseList promptId="test-prompt" />)

    await waitFor(() => {
      expect(screen.getByText('No test cases yet')).toBeInTheDocument()
    })
    expect(screen.getByText('Add your first test case or import from a file.')).toBeInTheDocument()
  })

  it('delete button calls deleteTestCase', async () => {
    mockListCases.mockResolvedValue({ data: mockCases } as never)
    mockDeleteCase.mockResolvedValue({} as never)

    renderWithProviders(<CaseList promptId="test-prompt" />)

    await waitFor(() => {
      expect(screen.getByText('Transfer to sales')).toBeInTheDocument()
    })

    // Find all Delete buttons and click the first one
    const deleteButtons = screen.getAllByText('Delete')
    fireEvent.click(deleteButtons[0])

    // Should show confirm button
    const confirmBtn = screen.getByText('Confirm')
    fireEvent.click(confirmBtn)

    await waitFor(() => {
      expect(mockDeleteCase).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { prompt_id: 'test-prompt', case_id: 'case-1' },
        })
      )
    })
  })

  it('opens Add Case editor when button clicked', async () => {
    mockListCases.mockResolvedValue({ data: [] } as never)

    renderWithProviders(<CaseList promptId="test-prompt" />)

    await waitFor(() => {
      expect(screen.getByText('Add Test Case')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Add Test Case'))

    await waitFor(() => {
      // Sheet opens with editor title in h2 element
      expect(screen.getByText('Add Test Case', { selector: 'h2' })).toBeInTheDocument()
    })
  })
})

describe('CaseEditor', () => {
  it('pre-populates for edit mode', () => {
    renderWithProviders(
      <CaseEditor
        promptId="test-prompt"
        existingCase={mockCases[0]}
        open={true}
        onOpenChange={() => {}}
      />
    )

    expect(screen.getByText('Edit Test Case')).toBeInTheDocument()
    expect(screen.getByDisplayValue('Transfer to sales')).toBeInTheDocument()
    expect(screen.getByDisplayValue('Test sales transfer')).toBeInTheDocument()
  })

  it('submits new case on create', async () => {
    mockAddCase.mockResolvedValue({ data: mockCases[0] } as never)

    renderWithProviders(
      <CaseEditor
        promptId="test-prompt"
        open={true}
        onOpenChange={() => {}}
      />
    )

    const nameInput = screen.getByPlaceholderText('Test case name')
    fireEvent.change(nameInput, { target: { value: 'New case' } })

    fireEvent.click(screen.getByText('Create'))

    await waitFor(() => {
      expect(mockAddCase).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { prompt_id: 'test-prompt' },
          body: expect.objectContaining({ name: 'New case', tier: 'normal' }),
        })
      )
    })
  })

  it('renders behavior criteria textarea', () => {
    renderWithProviders(
      <CaseEditor
        promptId="test-prompt"
        open={true}
        onOpenChange={() => {}}
      />
    )

    expect(screen.getByText('Behavior Criteria (one per line)')).toBeInTheDocument()
    const textarea = screen.getByPlaceholderText(/greets warmly in Spanish/)
    expect(textarea).toBeInTheDocument()
  })

  it('loads existing behavior criteria from case', () => {
    const caseWithBehavior: TestCaseResponse = {
      id: 'case-bh',
      name: 'Behavior case',
      description: null,
      tier: 'normal',
      variables: {},
      expected_output: { behavior: ['criterion 1', 'criterion 2'] },
      tags: [],
      chat_history: [],
    }

    renderWithProviders(
      <CaseEditor
        promptId="test-prompt"
        existingCase={caseWithBehavior}
        open={true}
        onOpenChange={() => {}}
      />
    )

    const textarea = screen.getByPlaceholderText(/greets warmly in Spanish/) as HTMLTextAreaElement
    expect(textarea.value).toBe('criterion 1\ncriterion 2')
  })

  it('behavior criteria textarea has correct placeholder', () => {
    renderWithProviders(
      <CaseEditor
        promptId="test-prompt"
        open={true}
        onOpenChange={() => {}}
      />
    )

    const textarea = screen.getByPlaceholderText(/greets warmly in Spanish/)
    expect(textarea).toHaveAttribute(
      'placeholder',
      'greets warmly in Spanish\nconfirms department before transfer\ntransfers to correct department'
    )
  })

  it('scorer flags toggle sets require_content', async () => {
    mockAddCase.mockResolvedValue({ data: mockCases[0] } as never)

    renderWithProviders(
      <CaseEditor
        promptId="test-prompt"
        open={true}
        onOpenChange={() => {}}
      />
    )

    // Toggle require_content switch
    const toggle = screen.getByRole('switch')
    fireEvent.click(toggle)

    fireEvent.click(screen.getByText('Create'))

    await waitFor(() => {
      expect(mockAddCase).toHaveBeenCalledWith(
        expect.objectContaining({
          body: expect.objectContaining({
            expected_output: expect.objectContaining({ require_content: true }),
          }),
        })
      )
    })
  })
})

describe('CaseImport', () => {
  it('triggers file upload on import', async () => {
    mockImport.mockResolvedValue({ data: mockCases } as never)

    renderWithProviders(
      <CaseImport
        promptId="test-prompt"
        open={true}
        onOpenChange={() => {}}
      />
    )

    expect(screen.getByText('Import Test Cases')).toBeInTheDocument()

    // Simulate file selection
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
    const file = new File(['[{"name":"test"}]'], 'cases.json', { type: 'application/json' })
    fireEvent.change(fileInput, { target: { files: [file] } })

    await waitFor(() => {
      expect(screen.getByText('cases.json')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Import'))

    await waitFor(() => {
      expect(mockImport).toHaveBeenCalledWith(
        expect.objectContaining({
          path: { prompt_id: 'test-prompt' },
          body: expect.objectContaining({ file }),
        })
      )
    })
  })

  it('displays structured error message on import failure', async () => {
    // Mock SDK to reject with error shape matching hey-api SDK
    mockImport.mockRejectedValue({
      body: { detail: "Expected a list of cases or a dict with 'cases' key, got str" },
    })

    renderWithProviders(
      <CaseImport
        promptId="test-prompt"
        open={true}
        onOpenChange={() => {}}
      />
    )

    // Select a file
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement
    const file = new File(['"not-a-list"'], 'bad-data.json', { type: 'application/json' })
    fireEvent.change(fileInput, { target: { files: [file] } })

    await waitFor(() => {
      expect(screen.getByText('bad-data.json')).toBeInTheDocument()
    })

    // Click Import
    fireEvent.click(screen.getByText('Import'))

    // Wait for error display
    await waitFor(() => {
      // File name should appear in the error section
      expect(screen.getByText(/Failed to import bad-data\.json/)).toBeInTheDocument()
    })

    // Error message should be user-friendly (rephrased by CaseImport), not raw [object Object]
    expect(screen.getByText(/Invalid file format/)).toBeInTheDocument()
  })
})
