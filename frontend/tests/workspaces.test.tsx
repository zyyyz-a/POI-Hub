import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { AuthContext, type AuthContextValue } from '../src/auth/AuthProvider'
import { StoresPage } from '../src/pages/StoresPage'
import { ProductsPage } from '../src/pages/ProductsPage'
import { OrdersPage } from '../src/pages/OrdersPage'
import { AccountingPage } from '../src/pages/AccountingPage'

const auth: AuthContextValue = {
  status: 'authenticated',
  user: { id: 'u1', email: 'operator@example.com', display_name: '运营员', status: 'active', is_platform_admin: false },
  tenant: { id: 't1', name: '示例租户', slug: 'demo', status: 'active' },
  membership: { id: 'm1', tenant_id: 't1', tenant_name: '示例租户', user_id: 'u1', email: 'operator@example.com', display_name: '运营员', role: 'operator', status: 'active' },
  tenants: [], csrfToken: 'csrf', login: vi.fn(), logout: vi.fn(), selectTenant: vi.fn(), refresh: vi.fn(),
}

function renderPage(page: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}><AuthContext.Provider value={auth}><MemoryRouter>{page}</MemoryRouter></AuthContext.Provider></QueryClientProvider>)
}

describe('workspace pages', () => {
  it('renders stores with loading and data states', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify([{ id: 's1', code: 'S-01', name: '西湖门店', address: '杭州市西湖区', status: 'active', version: 1 }]), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    renderPage(<StoresPage />)
    expect(await screen.findByText('西湖门店')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '门店管理' })).toBeInTheDocument()
  })

  it('shows product, order, and accounting workspaces', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const path = String(input)
      const payload = path.includes('/products') ? [{ id: 'p1', name: '双人套餐', merchant_product_id: 'P-1', remote_status: 'listed', skus: [] }] : path.includes('/orders') ? [{ id: 'o1', external_order_id: 'O-1', status: 'paid', total_amount: 9900 }] : { fund_count: 1, bill_count: 1, difference_count: 0, funds: [], bills: [] }
      return new Response(JSON.stringify(payload), { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
    renderPage(<><ProductsPage /><OrdersPage /><AccountingPage /></>)
    expect(await screen.findByText('双人套餐')).toBeInTheDocument()
    expect(await screen.findByText('O-1')).toBeInTheDocument()
    expect(await screen.findByText('资金与对账')).toBeInTheDocument()
  })
})
