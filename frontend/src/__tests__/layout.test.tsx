import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Routes, Route } from 'react-router-dom'
import AppShell from '../components/layout/AppShell'
import PromptsPage from '../pages/PromptsPage'

function renderWithProviders(ui: React.ReactElement, { route = '/' } = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>
        {ui}
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('AppShell', () => {
  it('renders sidebar with Prompts as primary nav item', () => {
    renderWithProviders(
      <Routes>
        <Route element={<AppShell />}>
          <Route path="*" element={<div>content</div>} />
        </Route>
      </Routes>
    )

    // Both mobile and desktop sidebars render nav items
    expect(screen.getAllByText('Prompts').length).toBeGreaterThanOrEqual(1)
  })

  it('Prompts nav link points to /prompts', () => {
    renderWithProviders(
      <Routes>
        <Route element={<AppShell />}>
          <Route path="*" element={<div>content</div>} />
        </Route>
      </Routes>
    )

    const promptLinks = screen.getAllByText('Prompts')
    expect(promptLinks[0].closest('a')).toHaveAttribute('href', '/prompts')
  })

  it('renders outlet for child content at /prompts', () => {
    renderWithProviders(
      <Routes>
        <Route element={<AppShell />}>
          <Route path="/prompts" element={<PromptsPage />} />
        </Route>
      </Routes>,
      { route: '/prompts' }
    )

    expect(screen.getByText('Prompts', { selector: 'h1' })).toBeInTheDocument()
  })

  it('displays app name in sidebar header', () => {
    renderWithProviders(
      <Routes>
        <Route element={<AppShell />}>
          <Route path="*" element={<div>content</div>} />
        </Route>
      </Routes>
    )

    // Both mobile and desktop sidebars render the app name
    expect(screen.getAllByText('Helix').length).toBeGreaterThanOrEqual(1)
  })

  it('opens the mobile navigation as a labelled Radix sheet', async () => {
    const user = userEvent.setup()
    renderWithProviders(
      <Routes>
        <Route element={<AppShell />}>
          <Route path="*" element={<div>content</div>} />
        </Route>
      </Routes>
    )

    await user.click(screen.getByRole('button', { name: 'Open navigation menu' }))
    expect(screen.getByRole('dialog', { name: 'Navigation' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Close navigation menu' })).toBeVisible()
  })

  it('gives every sidebar button an accessible name', () => {
    renderWithProviders(
      <Routes>
        <Route element={<AppShell />}>
          <Route path="*" element={<div>content</div>} />
        </Route>
      </Routes>
    )

    for (const button of screen.getAllByRole('button')) {
      expect(button).toHaveAccessibleName()
    }
    expect(screen.getByRole('link', { name: 'Skip to main content' })).toBeInTheDocument()
  })
})
