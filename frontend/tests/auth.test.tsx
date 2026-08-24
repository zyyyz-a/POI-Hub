import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from '../src/main'

const tenant = {
  id: 'tenant-demo', tenant_id: 'tenant-demo', tenant_name: '示例租户',
  user_id: 'user-1', email: 'admin@example.com', display_name: '平台管理员',
  role: 'tenant_admin' as const, status: 'active',
}
const user = { id: 'user-1', email: 'admin@example.com', display_name: '平台管理员', status: 'active', is_platform_admin: false }

function response(data: unknown, status = 200) {
  return Promise.resolve(new Response(status === 204 ? null : JSON.stringify(data), {
    status, headers: { 'Content-Type': 'application/json' },
  }))
}

describe('authentication flow', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    sessionStorage.clear()
    window.history.replaceState({}, '', '/dashboard')
  })

  it('redirects unauthenticated users to sign in and signs in with a tenant', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockImplementationOnce(() => response({ detail: '请先登录' }, 401))
      .mockImplementationOnce(() => response({ user, tenants: [tenant], csrf_token: 'csrf-1' }))
      .mockImplementationOnce(() => response({
        user, tenant: { id: 'tenant-demo', name: '示例租户', slug: 'demo', status: 'active' }, membership: tenant,
        tenants: [tenant],
      }))
      .mockImplementation(() => response({
        user, tenant: { id: 'tenant-demo', name: '示例租户', slug: 'demo', status: 'active' }, membership: tenant,
        summary: { pending_audits: 2, failed_operations: 1, low_stock: 3, unmapped_stores: 1 },
      }))

    render(<App />)
    expect(await screen.findByRole('heading', { name: '登录 POI Hub' })).toBeInTheDocument()
    expect(screen.getByText('本地生活 / 门店点位')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('邮箱'), { target: { value: user.email } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'password' } })
    fireEvent.click(screen.getByRole('button', { name: /登.*录/ }))

    expect(await screen.findByRole('heading', { name: '运营总览' })).toBeInTheDocument()
    expect(screen.getByText('示例租户')).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/auth/select-tenant', expect.objectContaining({ method: 'POST' }))
  })

  it('restores an authenticated session and rotates its CSRF token', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockImplementationOnce(() => response({
        user, tenant: { id: 'tenant-demo', name: '示例租户', slug: 'demo', status: 'active' }, membership: tenant,
      }))
      .mockImplementationOnce(() => response({ csrf_token: 'csrf-restored' }))
      .mockImplementation(() => response({ summary: {} }))

    render(<App />)
    expect(await screen.findByRole('heading', { name: '运营总览' })).toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/auth/csrf', expect.objectContaining({ credentials: 'include' }))
  })

  it('restores multiple memberships without session storage', async () => {
    const secondTenant = { ...tenant, id: 'membership-2', tenant_id: 'tenant-2', tenant_name: '第二租户' }
    vi.spyOn(globalThis, 'fetch')
      .mockImplementationOnce(() => response({
        user, tenant: null, membership: null, tenants: [tenant, secondTenant],
      }))
      .mockImplementationOnce(() => response({ csrf_token: 'csrf-restored' }))

    render(<App />)

    expect(await screen.findByRole('heading', { name: '选择工作租户' })).toBeInTheDocument()
    expect(screen.getByText('租户选择')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /第二租户/ })).toBeInTheDocument()
    expect(screen.getAllByText('租户管理员')).toHaveLength(2)
    expect(sessionStorage.getItem('poi-hub-tenants')).toBeNull()
  })

  it('requires an explicit choice when the user can access multiple tenants', async () => {
    const secondTenant = { ...tenant, id: 'membership-2', tenant_id: 'tenant-2', tenant_name: '第二租户' }
    vi.spyOn(globalThis, 'fetch')
      .mockImplementationOnce(() => response({}, 401))
      .mockImplementationOnce(() => response({ user, tenants: [tenant, secondTenant], csrf_token: 'csrf-1' }))
      .mockImplementationOnce(() => response({
        user, tenant: { id: 'tenant-2', name: '第二租户', slug: 'second', status: 'active' }, membership: secondTenant,
      }))
      .mockImplementation(() => response({ summary: {} }))

    render(<App />)
    await screen.findByRole('heading', { name: '登录 POI Hub' })
    fireEvent.change(screen.getByLabelText('邮箱'), { target: { value: user.email } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'password' } })
    fireEvent.click(screen.getByRole('button', { name: /登.*录/ }))

    expect(await screen.findByRole('heading', { name: '选择工作租户' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /第二租户/ }))
    expect(await screen.findByRole('heading', { name: '运营总览' })).toBeInTheDocument()
  })

  it('shows a login error when credentials are rejected', async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockImplementationOnce(() => response({}, 401))
      .mockImplementationOnce(() => response({ detail: '邮箱或密码错误' }, 401))

    render(<App />)
    await screen.findByRole('heading', { name: '登录 POI Hub' })
    fireEvent.change(screen.getByLabelText('邮箱'), { target: { value: 'bad@example.com' } })
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'bad' } })
    fireEvent.click(screen.getByRole('button', { name: /登.*录/ }))
    expect(await screen.findByText('邮箱或密码错误')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole('heading', { name: '运营总览' })).not.toBeInTheDocument())
  })

  it('keeps protected pages inaccessible while session lookup is unauthorized', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => response({}, 401))
    window.history.pushState({}, '', '/dashboard')
    render(<App />)
    expect(await screen.findByRole('heading', { name: '登录 POI Hub' })).toBeInTheDocument()
  })

  it('shows a navigable not-found page for unknown routes', async () => {
    window.history.replaceState({}, '', '/not-ready')
    vi.spyOn(globalThis, 'fetch')
      .mockImplementationOnce(() => response({
        user, tenant: { id: 'tenant-demo', name: '示例租户', slug: 'demo', status: 'active' },
        membership: tenant, tenants: [tenant],
      }))
      .mockImplementationOnce(() => response({ csrf_token: 'csrf-restored' }))

    render(<App />)

    expect(await screen.findByRole('heading', { name: '页面不存在' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '返回运营总览' })).toHaveAttribute('href', '/dashboard')
    expect(screen.queryByText('页面正在准备中')).not.toBeInTheDocument()
  })
})
