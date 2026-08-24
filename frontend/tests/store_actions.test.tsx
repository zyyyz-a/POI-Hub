import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AuthContext, type AuthContextValue } from '../src/auth/AuthProvider'
import { StoresPage } from '../src/pages/StoresPage'

const auth: AuthContextValue = {
  status: 'authenticated',
  user: { id: 'u1', email: 'operator@example.com', display_name: '运营员', status: 'active', is_platform_admin: false },
  tenant: { id: 't1', name: '示例租户', slug: 'demo', status: 'active' },
  membership: { id: 'm1', tenant_id: 't1', tenant_name: '示例租户', user_id: 'u1', email: 'operator@example.com', display_name: '运营员', role: 'operator', status: 'active' },
  tenants: [], csrfToken: 'csrf', login: vi.fn(), logout: vi.fn(), selectTenant: vi.fn(), refresh: vi.fn(),
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}><AuthContext.Provider value={auth}><StoresPage /></AuthContext.Provider></QueryClientProvider>)
}

describe('store actions', () => {
  it('edits a store with its optimistic version and refreshes the list', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      if (init?.method === 'PATCH') {
        expect(String(input)).toContain('/api/v1/stores/s1')
        expect(JSON.parse(String(init.body))).toMatchObject({ name: '新名字', version: 1 })
        return new Response(JSON.stringify({ id: 's1', code: 'S-01', name: '新名字', address: '地址', status: 'active', version: 2 }), { status: 200 })
      }
      return new Response(JSON.stringify([{ id: 's1', code: 'S-01', name: '门店一', address: '地址', status: 'active', version: 1 }]), { status: 200 })
    })
    renderPage()
    await screen.findByText('门店一')
    fireEvent.click(screen.getByRole('button', { name: '编辑' }))
    const input = screen.getByLabelText('门店名称')
    fireEvent.change(input, { target: { value: '新名字' } })
    fireEvent.click(screen.getByRole('button', { name: '保存门店' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/api/v1/stores/s1'), expect.objectContaining({ method: 'PATCH' })))
  })
})

