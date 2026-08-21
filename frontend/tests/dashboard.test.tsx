import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { DashboardPage } from '../src/pages/DashboardPage'

function response(data: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  }))
}

describe('dashboard states', () => {
  afterEach(() => vi.restoreAllMocks())

  it('keeps the metrics region busy while loading', () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => new Promise(() => undefined))
    render(<DashboardPage />)
    expect(screen.getByLabelText('运营指标')).toHaveAttribute('aria-busy', 'true')
  })

  it('renders aggregate values returned by the API', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => response({
      summary: { pending_audits: 8, failed_operations: 2, low_stock: 4, unmapped_stores: 6 },
    }))
    render(<DashboardPage />)
    expect(await screen.findByText('8')).toBeInTheDocument()
    expect(screen.getByText('待处理审计')).toBeInTheDocument()
    expect(screen.getByText('6')).toBeInTheDocument()
    expect(screen.getByLabelText('运营指标')).toHaveAttribute('aria-busy', 'false')
  })

  it('shows a recoverable error state', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => response({ detail: '汇总服务暂不可用' }, 503))
    render(<DashboardPage />)
    expect(await screen.findByText('汇总服务暂不可用')).toBeInTheDocument()
    expect(screen.getByText('请稍后重试，或前往操作中心查看详细信息。')).toBeInTheDocument()
  })
})
