import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AuthContext, type AuthContextValue } from '../src/auth/AuthProvider'
import { MappingsPage } from '../src/pages/MappingsPage'

const auth: AuthContextValue = {
  status: 'authenticated',
  user: { id: 'u1', email: 'operator@example.com', display_name: '运营员', status: 'active', is_platform_admin: false },
  tenant: { id: 't1', name: '示例租户', slug: 'demo', status: 'active' },
  membership: { id: 'm1', tenant_id: 't1', tenant_name: '示例租户', user_id: 'u1', email: 'operator@example.com', display_name: '运营员', role: 'operator', status: 'active' },
  tenants: [], csrfToken: 'csrf', login: vi.fn(), logout: vi.fn(), selectTenant: vi.fn(), refresh: vi.fn(),
}

describe('mapping actions', () => {
  it('manually binds a selected store and POI', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const path = String(input)
      if (path.endsWith('/stores')) return new Response(JSON.stringify([{ id: 's1', code: 'S1', name: '门店一', address: '地址', status: 'active' }]), { status: 200 })
      if (path.endsWith('/pois')) return new Response(JSON.stringify([{ id: 'p1', external_poi_id: 'P1', name: 'POI 一', address: '地址', remote_status: 'approved' }]), { status: 200 })
      if (path.endsWith('/match-candidates')) return new Response(JSON.stringify([]), { status: 200 })
      if (path.endsWith('/store-poi-mappings') && !init?.method) return new Response(JSON.stringify([]), { status: 200 })
      if (path.endsWith('/store-poi-mappings/manual')) {
        expect(JSON.parse(String(init?.body))).toEqual({ store_id: 's1', service_poi_id: 'p1' })
        return new Response(JSON.stringify({ id: 'm1', store_id: 's1', service_poi_id: 'p1', state: 'active' }), { status: 201 })
      }
      return new Response(JSON.stringify([]), { status: 200 })
    })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><AuthContext.Provider value={auth}><MappingsPage /></AuthContext.Provider></QueryClientProvider>)
    fireEvent.click(await screen.findByRole('button', { name: '手动绑定' }))
    fireEvent.mouseDown(screen.getByLabelText('门店'))
    fireEvent.click(await screen.findByText('门店一（S1）'))
    fireEvent.mouseDown(screen.getByLabelText('服务 POI'))
    fireEvent.click(await screen.findByText('POI 一（P1）'))
    fireEvent.click(screen.getByRole('button', { name: '确认绑定' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/store-poi-mappings/manual'), expect.objectContaining({ method: 'POST' })))
  })
})

