import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { setCsrfToken } from '../src/api/client'
import { AuthContext, type AuthContextValue } from '../src/auth/AuthProvider'
import { TenantsPage } from '../src/pages/TenantsPage'

const auth: AuthContextValue = {
  status: 'authenticated',
  user: { id: 'platform-1', email: 'admin@example.com', display_name: '总部管理员', status: 'active', is_platform_admin: true },
  tenant: null,
  membership: null,
  tenants: [],
  csrfToken: 'csrf',
  login: vi.fn(), logout: vi.fn(), selectTenant: vi.fn(), refresh: vi.fn(),
}

function json(data: unknown) {
  return Promise.resolve(new Response(JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json' } }))
}

describe('central tenant control', () => {
  afterEach(() => { setCsrfToken(undefined); vi.restoreAllMocks() })

  it('lets a platform administrator suspend a merchant', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (_input, init) => {
      if (init?.method === 'PATCH') return json({ id: 't1', name: '示例商户', slug: 'demo', status: 'suspended' })
      return json([{ id: 't1', name: '示例商户', slug: 'demo', status: 'active' }])
    })
    setCsrfToken('csrf')
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(<QueryClientProvider client={queryClient}><AuthContext.Provider value={auth}><MemoryRouter><TenantsPage /></MemoryRouter></AuthContext.Provider></QueryClientProvider>)

    expect(await screen.findByText('示例商户')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /停\s*用/ }))
    fireEvent.click(await screen.findByRole('button', { name: /确\s*认\s*停\s*用/ }))

    await waitFor(() => expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'PATCH' && init.body === JSON.stringify({ status: 'suspended' }))).toBe(true))
    await waitFor(() => expect(auth.refresh).toHaveBeenCalled())
  })
})
