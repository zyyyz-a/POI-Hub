import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthContext, type AuthContextValue } from '../src/auth/AuthProvider'
import { DashboardPage } from '../src/pages/DashboardPage'

function response(data: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': status >= 400 ? 'application/problem+json' : 'application/json' },
  }))
}

function authValue(tenantId: string): AuthContextValue {
  const tenantName = tenantId === 'tenant-1' ? '第一租户' : '第二租户'
  return {
    status: 'authenticated',
    user: { id: 'user-1', email: 'admin@example.com', display_name: '管理员', status: 'active', is_platform_admin: false },
    tenant: { id: tenantId, name: tenantName, slug: tenantId, status: 'active' },
    membership: {
      id: `membership-${tenantId}`, tenant_id: tenantId, tenant_name: tenantName, user_id: 'user-1',
      email: 'admin@example.com', display_name: '管理员', role: 'tenant_admin', status: 'active',
    },
    tenants: [],
    csrfToken: 'csrf',
    login: async () => undefined,
    logout: async () => undefined,
    selectTenant: async () => undefined,
    refresh: async () => undefined,
  }
}

function renderDashboard(initialTenantId = 'tenant-1') {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const ui = (tenantId: string) => (
    <QueryClientProvider client={queryClient}>
      <AuthContext.Provider value={authValue(tenantId)}>
        <DashboardPage />
      </AuthContext.Provider>
    </QueryClientProvider>
  )
  const view = render(ui(initialTenantId))
  return {
    ...view,
    switchTenant: (tenantId: string) => view.rerender(ui(tenantId)),
  }
}

describe('dashboard states', () => {
  afterEach(() => vi.restoreAllMocks())

  it('shows only a loading state while the current tenant request is pending', () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => new Promise(() => undefined))
    renderDashboard()

    expect(screen.getByLabelText('运营指标')).toHaveAttribute('aria-busy', 'true')
    expect(screen.queryByText('连接正常')).not.toBeInTheDocument()
    expect(screen.queryByText('Mock 正常')).not.toBeInTheDocument()
  })

  it('renders all aggregate values backed by the dashboard API', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => response({
      summary: { pending_audits: 8, failed_operations: 2, low_stock: 4, unmapped_stores: 6 },
    }))
    renderDashboard()

    expect(await screen.findByText('2')).toBeInTheDocument()
    expect(screen.getByText('今日运营')).toBeInTheDocument()
    expect(screen.getByText('6')).toBeInTheDocument()
    expect(screen.getByText('失败操作')).toBeInTheDocument()
    expect(screen.getByText('待映射门店')).toBeInTheDocument()
    expect(screen.getByText('待处理审核')).toBeInTheDocument()
    expect(screen.getByText('低库存商品')).toBeInTheDocument()
    expect(screen.getAllByText('8')).toHaveLength(1)
    expect(screen.getAllByText('4')).toHaveLength(1)
    expect(screen.queryByText('连接正常')).not.toBeInTheDocument()
    expect(screen.getByLabelText('运营指标')).toHaveAttribute('aria-busy', 'false')
  })

  it('shows an error without zero metrics or health claims', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => response({
      detail: { message: '汇总服务暂不可用', code: 'dashboard_unavailable' },
    }, 503))
    renderDashboard()

    expect(await screen.findByText('汇总服务暂不可用')).toBeInTheDocument()
    expect(screen.getByText('请稍后重试，或前往操作中心查看详细信息。')).toBeInTheDocument()
    expect(screen.queryByLabelText('运营指标')).not.toBeInTheDocument()
    expect(screen.queryByText('连接正常')).not.toBeInTheDocument()
  })

  it('omits aggregate cards missing from the dashboard response', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => response({
      summary: { failed_operations: 3 },
    }))
    renderDashboard()

    expect(await screen.findByText('3')).toBeInTheDocument()
    expect(screen.getByText('失败操作')).toBeInTheDocument()
    expect(screen.queryByText('待映射门店')).not.toBeInTheDocument()
    expect(screen.queryByText('待处理审核')).not.toBeInTheDocument()
    expect(screen.queryByText('低库存商品')).not.toBeInTheDocument()
  })

  it('drops stale metrics and refetches when the active tenant changes', async () => {
    let resolveSecond!: (value: Response | PromiseLike<Response>) => void
    const secondResponse = new Promise<Response>(resolve => { resolveSecond = resolve })
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockImplementationOnce(() => response({ summary: { failed_operations: 37, unmapped_stores: 41 } }))
      .mockImplementationOnce(() => secondResponse)
    const view = renderDashboard('tenant-1')

    expect(await screen.findByText('37')).toBeInTheDocument()
    view.switchTenant('tenant-2')

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    expect(screen.queryByText('37')).not.toBeInTheDocument()
    expect(screen.getByLabelText('运营指标')).toHaveAttribute('aria-busy', 'true')

    resolveSecond(new Response(JSON.stringify({
      summary: { failed_operations: 73, unmapped_stores: 79 },
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    expect(await screen.findByText('73')).toBeInTheDocument()
  })
})
