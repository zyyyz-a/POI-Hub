import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthContext, type AuthContextValue } from '../src/auth/AuthProvider'
import { setCsrfToken } from '../src/api/client'
import { ConnectionsPage } from '../src/pages/ConnectionsPage'
import { MembersPage } from '../src/pages/MembersPage'
import { OrdersPage } from '../src/pages/OrdersPage'
import { AccountingPage } from '../src/pages/AccountingPage'
import { OperationsPage } from '../src/pages/OperationsPage'
import { WebhooksPage } from '../src/pages/WebhooksPage'
import { ProductsPage } from '../src/pages/ProductsPage'
import { PoisPage } from '../src/pages/PoisPage'

const auth: AuthContextValue = {
  status: 'authenticated',
  user: { id: 'u1', email: 'admin@example.com', display_name: 'Admin', status: 'active', is_platform_admin: false },
  tenant: { id: 't1', name: 'Demo Tenant', slug: 'demo', status: 'active' },
  membership: { id: 'm1', tenant_id: 't1', tenant_name: 'Demo Tenant', user_id: 'u1', email: 'admin@example.com', display_name: 'Admin', role: 'tenant_admin', status: 'active' },
  tenants: [], csrfToken: 'csrf', login: vi.fn(), logout: vi.fn(), selectTenant: vi.fn(), refresh: vi.fn(),
}

function json(data: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } }))
}

function renderPage(page: React.ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}><AuthContext.Provider value={auth}><MemoryRouter>{page}</MemoryRouter></AuthContext.Provider></QueryClientProvider>)
}

type FetchCall = [input: unknown, init?: RequestInit]

function callsFor(mock: { mock: { calls: readonly (readonly unknown[])[] } }, path: string): FetchCall[] {
  return mock.mock.calls.filter(([input]) => String(input).includes(path)).map(call => call as FetchCall)
}

describe('domain page interactions', () => {
  afterEach(() => { setCsrfToken(undefined); vi.restoreAllMocks() })

  it('creates a connection and sends secret fields in the request body', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      if (String(input).includes('/connections') && init?.method === 'POST') return json({ id: 'c1', capability: 'local_life', mode: 'mock', status: 'active', mock_scenario: 'healthy' }, 201)
      return json([])
    })
    setCsrfToken('csrf')
    renderPage(<ConnectionsPage />)
    expect(await screen.findByRole('heading', { level: 2 })).toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button')[1])
    fireEvent.mouseDown(screen.getAllByRole('combobox')[0])
    fireEvent.click(await screen.findByText('微信团购本地生活'))
    fireEvent.change(screen.getByLabelText('AppSecret'), { target: { value: 'secret-value' } })
    fireEvent.click(screen.getByRole('button', { name: '创建连接' }))
    await waitFor(() => expect(callsFor(fetchMock, '/api/v1/connections').some(([, init]) => init?.method === 'POST')).toBe(true))
    const call = callsFor(fetchMock, '/api/v1/connections').find(([, init]) => init?.method === 'POST')
    expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ capability: 'local_life', secrets: { app_secret: 'secret-value' } })
  })

  it('creates a member invitation and displays the returned invite token', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => String(input).includes('/members/invitations') ? json({ invite_token: 'invite-123' }, 201) : json([]))
    renderPage(<MembersPage />)
    await screen.findByRole('heading', { level: 2 })
    fireEvent.click(screen.getAllByRole('button')[1])
    fireEvent.change(screen.getAllByRole('textbox')[0], { target: { value: 'new@example.com' } })
    fireEvent.click(screen.getByRole('button', { name: '创建邀请' }))
    expect(await screen.findByDisplayValue('invite-123')).toBeInTheDocument()
    expect(callsFor(fetchMock, '/api/v1/members/invitations')).toHaveLength(1)
  })

  it('retries a failed operation from the operations page', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => String(input).includes('/operations/op-1/retry') ? json({ id: 'op-1', command_type: 'poi.sync', status: 'queued' }) : json([{ id: 'op-1', command_type: 'poi.sync', status: 'failed', attempt_count: 2, error_message: 'timeout' }]))
    renderPage(<OperationsPage />)
    await screen.findByText('timeout')
    fireEvent.click(screen.getByRole('button', { name: '重试' }))
    await waitFor(() => expect(callsFor(fetchMock, '/api/v1/operations/op-1/retry')).toHaveLength(1))
  })

  it('retries a failed webhook only when the row is retryable', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => String(input).includes('/webhook-events/event-1/retry') ? json({ id: 'event-1', event_type: 'product_audit', status: 'received', attempt_count: 2 }) : json([{ id: 'event-1', event_type: 'product_audit', status: 'failed', attempt_count: 1, error_message: 'bad signature' }, { id: 'event-2', event_type: 'payment', status: 'processed', attempt_count: 1 }]))
    renderPage(<WebhooksPage />)
    await screen.findByText('bad signature')
    const retry = screen.getByRole('button', { name: '重新处理' })
    expect(retry).toBeEnabled()
    fireEvent.click(retry)
    await waitFor(() => expect(callsFor(fetchMock, '/api/v1/webhook-events/event-1/retry')).toHaveLength(1))
  })

  it('submits voucher consumption with the selected store', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const path = String(input)
      if (path.includes('/vouchers/v-1/consume')) return json({ operation: { id: 'op-v', status: 'queued', command_type: 'voucher.consume' }, voucher: { id: 'v-1', state: 'consumed' } }, 202)
      if (path.includes('/stores')) return json([{ id: 's-1', name: 'Test Store' }])
      if (path.includes('/vouchers')) return json([{ id: 'v-1', code_masked: '****1234', state: 'available' }])
      return json([])
    })
    renderPage(<OrdersPage />)
    await screen.findByText('****1234')
    fireEvent.click(screen.getByRole('button', { name: /核\s*销/ }))
    fireEvent.mouseDown(screen.getAllByRole('combobox').at(-1)!)
    fireEvent.click(await screen.findByText('Test Store'))
    fireEvent.click(screen.getByRole('button', { name: '确认核销' }))
    await waitFor(() => expect(callsFor(fetchMock, '/api/v1/local-life/vouchers/v-1/consume')).toHaveLength(1))
    const call = callsFor(fetchMock, '/api/v1/local-life/vouchers/v-1/consume')[0]
    expect(JSON.parse(String(call[1]?.body))).toMatchObject({ store_id: 's-1' })
  })

  it('shows accounting difference warning and submits a sync command', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const path = String(input)
      if (path.includes('/accounting/sync')) return json({ operation: { id: 'op-a', status: 'queued', command_type: 'accounting.sync' }, summary: { fund_count: 1, bill_count: 1, difference_count: 1, difference: 100 } }, 202)
      if (path.includes('/connections')) return json([{ id: 'c-a', capability: 'local_life' }])
      return json({ fund_count: 1, bill_count: 1, difference_count: 1, difference: 100, funds: [], bills: [] })
    })
    renderPage(<AccountingPage />)
    expect(await screen.findByText('发现已关联订单的对账差异')).toBeInTheDocument()
    fireEvent.mouseDown(screen.getAllByRole('combobox')[0])
    fireEvent.click(await screen.findByText('c-a', { selector: '.ant-select-item-option-content' }))
    fireEvent.change(screen.getByPlaceholderText('微信商品 ID'), { target: { value: 'product-1' } })
    fireEvent.change(screen.getByLabelText('账单日期'), { target: { value: '2026-08-24' } })
    fireEvent.click(screen.getByRole('button', { name: '同步账单' }))
    await waitFor(() => expect(callsFor(fetchMock, '/api/v1/local-life/accounting/sync')).toHaveLength(1))
  })

  it('delists a product from its lifecycle menu', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const path = String(input)
      if (path.includes('/products/p-1/actions/delist')) return json({ operation_id: 'op-p', status: 'queued' }, 202)
      if (path.includes('/products')) return json([{ id: 'p-1', name: '套餐', merchant_product_id: 'merchant-p1', remote_status: 'listed', skus: [] }])
      return json([])
    })
    renderPage(<ProductsPage />)
    expect(await screen.findByText('merchant-p1')).toBeInTheDocument()
    fireEvent.mouseEnter(screen.getByRole('button', { name: '生命周期' }))
    fireEvent.click(await screen.findByRole('menuitem', { name: '下架' }))
    await waitFor(() => expect(callsFor(fetchMock, '/api/v1/local-life/products/p-1/actions/delist')).toHaveLength(1))
    const call = callsFor(fetchMock, '/api/v1/local-life/products/p-1/actions/delist')[0]
    expect(JSON.parse(String(call[1]?.body))).toHaveProperty('idempotency_key')
  })

  it('syncs POIs using a service POI connection', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const path = String(input)
      if (path.includes('/pois/sync')) return json({ operation_id: 'op-poi', status: 'queued' }, 202)
      if (path.includes('/connections')) return json([{ id: 'poi-c-1', capability: 'service_poi' }])
      if (path.includes('/pois')) return json([{ id: 'poi-1', external_poi_id: 'wx-poi-1', name: '门店 POI', address: '地址', remote_status: 'active' }])
      return json([])
    })
    renderPage(<PoisPage />)
    expect(await screen.findByText('wx-poi-1')).toBeInTheDocument()
    fireEvent.mouseDown(screen.getAllByRole('combobox')[0])
    fireEvent.click(await screen.findByText('poi-c-1', { selector: '.ant-select-item-option-content' }))
    await waitFor(() => expect(callsFor(fetchMock, '/api/v1/pois/sync')).toHaveLength(1))
    const call = callsFor(fetchMock, '/api/v1/pois/sync')[0]
    expect(JSON.parse(String(call[1]?.body))).toMatchObject({ connection_id: 'poi-c-1' })
  })
})
