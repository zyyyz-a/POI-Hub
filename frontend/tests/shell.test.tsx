import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import { AppShell } from '../src/layout/AppShell'
import { AuthContext, type AuthContextValue } from '../src/auth/AuthProvider'

const baseAuth: AuthContextValue = {
  status: 'authenticated',
  user: { id: 'u1', email: 'operator@example.com', display_name: '运营员', status: 'active', is_platform_admin: false },
  tenant: { id: 't1', name: '示例租户', slug: 'demo', status: 'active' },
  membership: { id: 'm1', tenant_id: 't1', tenant_name: '示例租户', user_id: 'u1', email: 'operator@example.com', display_name: '运营员', role: 'operator', status: 'active' },
  tenants: [], csrfToken: 'csrf', login: async () => undefined, logout: async () => undefined, selectTenant: async () => undefined, refresh: async () => undefined,
}

function renderShell(auth: Partial<AuthContextValue> = {}) {
  return render(
    <AuthContext.Provider value={{ ...baseAuth, ...auth }}>
      <MemoryRouter initialEntries={['/dashboard']}>
        <AppShell><div>页面内容</div></AppShell>
      </MemoryRouter>
    </AuthContext.Provider>,
  )
}

describe('application shell', () => {
  it('hides member administration from operators', () => {
    renderShell()
    expect(screen.queryByText('成员管理')).not.toBeInTheDocument()
    expect(screen.getByText('门店管理')).toBeInTheDocument()
    expect(screen.getByText('页面内容')).toBeInTheDocument()
    expect(screen.getByText('中央 SaaS 服务')).toBeInTheDocument()
  })

  it('shows member administration to tenant administrators', () => {
    renderShell({ membership: { ...baseAuth.membership!, role: 'tenant_admin' }, user: { ...baseAuth.user!, display_name: '租户管理员' } })
    expect(screen.getByText('成员管理')).toBeInTheDocument()
    expect(screen.queryByText('系统设置')).not.toBeInTheDocument()
  })

  it('renders a tenant switcher and calls selection handler', async () => {
    const selectTenant = vi.fn().mockResolvedValue(undefined)
    renderShell({ tenants: [
      { ...baseAuth.membership!, id: 'm2', tenant_id: 't2', tenant_name: '第二租户' },
    ], selectTenant })
    fireEvent.click(screen.getByRole('button', { name: /示例租户/ }))
    fireEvent.click(screen.getByRole('menuitem', { name: /第二租户/ }))
    await waitFor(() => expect(selectTenant).toHaveBeenCalledWith('t2'))
  })
})
