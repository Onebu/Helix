import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AccessibleLineageView from '@/components/evolution/AccessibleLineageView'
import type { LineageNode } from '@/types/evolution'

const nodes: LineageNode[] = [
  {
    candidateId: 'seed',
    parentIds: [],
    generation: 0,
    island: 0,
    fitnessScore: -4,
    normalizedScore: 0.5,
    rejected: false,
    mutationType: 'seed',
    survived: true,
    template: 'Original prompt',
  },
  {
    candidateId: 'child',
    parentIds: ['seed'],
    generation: 1,
    island: 1,
    fitnessScore: -1,
    normalizedScore: 0.9,
    rejected: false,
    mutationType: 'rcc',
    survived: true,
    template: 'Improved prompt',
  },
]

describe('AccessibleLineageView', () => {
  it('offers graph and list views with equivalent candidate selection', async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    render(
      <AccessibleLineageView
        nodes={nodes}
        selectedId="seed"
        bestCandidateId="child"
        onSelect={onSelect}
      />,
    )

    const child = screen.getByRole('button', {
      name: /candidate child.*generation 2.*island 2.*full fitness.*-1\.000.*feasible/i,
    })
    await user.click(child)
    expect(onSelect).toHaveBeenCalledWith('child')

    await user.click(screen.getByRole('tab', { name: 'List view' }))
    const treeItem = screen.getByRole('treeitem', {
      name: /candidate child.*generation 2.*island 2.*full fitness.*-1\.000.*feasible/i,
    })
    expect(treeItem).toBeVisible()
    await user.click(treeItem)
    expect(onSelect).toHaveBeenLastCalledWith('child')
  })

  it('activates graph nodes and follows known lineage edges with the keyboard', async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    render(
      <AccessibleLineageView
        nodes={nodes}
        selectedId="seed"
        bestCandidateId="child"
        onSelect={onSelect}
      />,
    )

    const seed = screen.getByRole('button', { name: /candidate seed.*generation 1/i })
    seed.focus()
    await user.keyboard('{ArrowRight}')
    const child = screen.getByRole('button', { name: /candidate child.*generation 2/i })
    expect(child).toHaveFocus()
    expect(child).toHaveAttribute('data-focused', 'true')

    await user.keyboard('{Space}')
    expect(onSelect).toHaveBeenCalledWith('child')
    await user.keyboard('{ArrowLeft}')
    expect(seed).toHaveFocus()
    await user.keyboard('{Enter}')
    expect(onSelect).toHaveBeenLastCalledWith('seed')
  })

  it('uses focusable treeitems with roving chronological keyboard navigation', async () => {
    const user = userEvent.setup()
    render(
      <AccessibleLineageView
        nodes={nodes}
        selectedId="seed"
        bestCandidateId="child"
        onSelect={vi.fn()}
      />,
    )

    await user.click(screen.getByRole('tab', { name: 'List view' }))
    const seed = screen.getByRole('treeitem', { name: /candidate seed/i })
    const child = screen.getByRole('treeitem', { name: /candidate child/i })
    expect(seed).toHaveAttribute('tabindex', '0')
    expect(child).toHaveAttribute('tabindex', '-1')

    seed.focus()
    await user.keyboard('{ArrowDown}')
    expect(child).toHaveFocus()
    expect(child).toHaveAttribute('tabindex', '0')
    await user.keyboard('{ArrowUp}')
    expect(seed).toHaveFocus()
    await user.keyboard('{End}')
    expect(child).toHaveFocus()
    await user.keyboard('{Home}')
    expect(seed).toHaveFocus()
  })
})
