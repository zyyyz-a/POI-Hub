export type Role = 'platform_admin' | 'tenant_admin' | 'operator' | 'verifier' | 'auditor'

export interface User {
  id: string
  email: string
  display_name: string
  status: string
  is_platform_admin: boolean
}

export interface Tenant {
  id: string
  name: string
  slug: string
  status: string
}

export interface Membership {
  id: string
  tenant_id: string
  tenant_name: string
  user_id: string
  email: string
  display_name: string
  role: Role
  status: string
}

export interface MeResponse {
  user: User
  tenant: Tenant | null
  membership: Membership | null
  tenants: Membership[]
}

export interface LoginResponse {
  user: User
  tenants: Membership[]
  csrf_token: string
}

export interface DashboardSummary {
  pending_audits?: number
  failed_operations?: number
  low_stock?: number
  unmapped_stores?: number
  reconciliation_differences?: number
  unhealthy_connections?: number
}

export interface StoreRecord {
  id: string
  code: string
  name: string
  address: string
  status: string
  version?: number
  city?: string | null
  district?: string | null
}

export interface PoiRecord {
  id: string
  connection_id: string
  external_poi_id: string
  name: string
  address: string
  latitude?: number | null
  longitude?: number | null
  remote_status: string
  category?: string | null
}

export interface MappingRecord {
  id: string
  store_id: string
  service_poi_id: string
  state: string
  match_score?: number | null
  match_evidence?: Record<string, unknown>
}

export interface ProductRecord {
  id: string
  name: string
  merchant_product_id?: string
  remote_status?: string
  desired_state?: string
  version?: number
  skus?: Array<{ id: string; name: string; stock: number; desired_stock?: number; version?: number; merchant_sku_id?: string }>
}

export interface OrderRecord {
  id: string
  external_order_id: string
  status: string
  total_amount?: number
  created_at?: string
}

export interface AccountingSummary {
  fund_count: number
  bill_count: number
  difference_count: number
  funds?: Array<Record<string, unknown>>
  bills?: Array<Record<string, unknown>>
  fund_total?: number
  bill_total?: number
  difference?: number
  differences?: unknown[]
  linked_order_count?: number
  unmatched_fund_count?: number
  unmatched_bill_count?: number
}

export interface OperationRecord {
  id: string
  command_type: string
  status: string
  error_code?: string | null
  error_message?: string | null
  attempt_count?: number
  created_at?: string
  completed_at?: string | null
}

export interface RemotePoiRecord {
  poi_id: string
  name: string
  address: string
  latitude?: number | null
  longitude?: number | null
  status: string
}

export interface BatchRetryResponse {
  accepted_count: number
  rejected_count: number
  items: Array<{ operation_id: string; accepted: boolean; reason?: string | null }>
}

export interface VoucherRecord {
  id: string
  external_voucher_id: string
  code_masked: string
  state: string
  consume_store_id?: string | null
  order_id?: string | null
}

export interface AfterSaleRecord {
  id: string
  order_id: string
  external_after_sale_id: string
  type?: string | null
  status: string
  amount?: number
}

export class ApiError extends Error {
  status: number
  code?: string
  correlation_id?: string
  field_errors?: unknown

  constructor(message: string, status: number, code?: string, correlationId?: string, fieldErrors?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.correlation_id = correlationId
    this.field_errors = fieldErrors
  }
}

let csrfToken: string | undefined

export function setCsrfToken(value: string | undefined) {
  csrfToken = value
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/problem+json, application/json')
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  if (csrfToken && init.method && init.method !== 'GET') headers.set('X-CSRF-Token', csrfToken)

  const response = await fetch(path, { ...init, credentials: 'include', headers })
  if (response.status === 204) return undefined as T
  const payload: unknown = await response.json().catch(() => ({}))
  if (!response.ok) {
    const problem = isRecord(payload) ? payload : {}
    const nested = isRecord(problem.detail) ? problem.detail : {}
    const message = stringValue(problem.detail)
      ?? stringValue(nested.message)
      ?? stringValue(problem.message)
      ?? stringValue(problem.title)
      ?? '请求失败，请稍后重试'
    throw new ApiError(
      message,
      response.status,
      stringValue(problem.code) ?? stringValue(nested.code),
      stringValue(problem.correlation_id)
        ?? stringValue(nested.correlation_id)
        ?? response.headers.get('X-Request-ID')
        ?? undefined,
      problem.field_errors ?? nested.field_errors,
    )
  }
  return payload as T
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function stringValue(value: unknown): string | undefined {
  return typeof value === 'string' && value ? value : undefined
}

export const api = {
  me: () => request<MeResponse>('/api/v1/me'),
  csrf: async () => {
    const result = await request<{ csrf_token: string }>('/api/v1/auth/csrf')
    setCsrfToken(result.csrf_token)
    return result.csrf_token
  },
  login: async (email: string, password: string) => {
    const result = await request<LoginResponse>('/api/v1/auth/login', {
      method: 'POST', body: JSON.stringify({ email, password }),
    })
    setCsrfToken(result.csrf_token)
    return result
  },
  logout: () => request<void>('/api/v1/auth/logout', { method: 'POST' }),
  selectTenant: (tenantId: string) => request<MeResponse>('/api/v1/auth/select-tenant', {
    method: 'POST', body: JSON.stringify({ tenant_id: tenantId }),
  }),
  platformTenants: () => request<Tenant[]>('/api/v1/platform/tenants'),
  setTenantStatus: (tenantId: string, status: 'active' | 'suspended') => request<Tenant>('/api/v1/platform/tenants/' + tenantId + '/status', {
    method: 'PATCH', body: JSON.stringify({ status }),
  }),
  dashboard: () => request<DashboardSummary | { summary: DashboardSummary }>('/api/v1/dashboard'),
  stores: () => request<StoreRecord[]>('/api/v1/stores'),
  pois: () => request<PoiRecord[]>('/api/v1/pois'),
  mappings: () => request<MappingRecord[]>('/api/v1/store-poi-mappings'),
  candidates: () => request<unknown[]>('/api/v1/match-candidates'),
  products: () => request<ProductRecord[]>('/api/v1/local-life/products'),
  orders: () => request<OrderRecord[]>('/api/v1/local-life/orders'),
  afterSales: () => request<AfterSaleRecord[]>('/api/v1/local-life/after-sales'),
  accounting: async () => {
    const payload = await request<AccountingSummary | { summary: AccountingSummary }>('/api/v1/local-life/accounting/reconciliation')
    return 'summary' in payload ? payload.summary : payload
  },
  connections: () => request<unknown[]>('/api/v1/connections'),
  operations: () => request<unknown[]>('/api/v1/operations'),
  audit: () => request<unknown[]>('/api/v1/audit-logs'),
  webhooks: () => request<unknown[]>('/api/v1/webhook-events'),
  members: () => request<unknown[]>('/api/v1/members'),
  createStore: (payload: Record<string, unknown>) => request<StoreRecord>('/api/v1/stores', { method: 'POST', body: JSON.stringify(payload) }),
  updateStore: (storeId: string, payload: Record<string, unknown>) => request<StoreRecord>('/api/v1/stores/' + storeId, { method: 'PATCH', body: JSON.stringify(payload) }),
  archiveStore: (storeId: string, version: number) => request<void>('/api/v1/stores/' + storeId + '?version=' + version, { method: 'DELETE', body: '{}' }),
  syncPois: (payload: { connection_id: string; idempotency_key: string }) => request<{ operation_id: string; status: string }>('/api/v1/pois/sync', { method: 'POST', body: JSON.stringify(payload) }),
  searchPois: (connectionId: string, keyword: string) => request<RemotePoiRecord[]>('/api/v1/pois/search?connection_id=' + encodeURIComponent(connectionId) + '&keyword=' + encodeURIComponent(keyword)),
  createPoi: (payload: Record<string, unknown>) => request<{ operation_id: string; status: string }>('/api/v1/pois', { method: 'POST', body: JSON.stringify(payload) }),
  updatePoi: (poiId: string, payload: Record<string, unknown>) => request<{ operation_id: string; status: string }>('/api/v1/pois/' + poiId, { method: 'PATCH', body: JSON.stringify(payload) }),
  deletePoi: (poiId: string, idempotencyKey: string) => request<{ operation_id: string; status: string }>('/api/v1/pois/' + poiId + '/delete', { method: 'POST', body: JSON.stringify({ idempotency_key: idempotencyKey }) }),
  refreshPoiAudit: (poiId: string, idempotencyKey: string) => request<{ operation_id: string; status: string }>('/api/v1/pois/' + poiId + '/audit-refresh', { method: 'POST', body: JSON.stringify({ idempotency_key: idempotencyKey }) }),
  confirmCandidate: (candidateId: string) => request<unknown>('/api/v1/match-candidates/' + candidateId + '/confirm', { method: 'POST', body: '{}' }),
  dismissCandidate: (candidateId: string) => request<unknown>('/api/v1/match-candidates/' + candidateId + '/dismiss', { method: 'POST', body: '{}' }),
  manualMap: (payload: { store_id: string; service_poi_id: string }) => request<unknown>('/api/v1/store-poi-mappings/manual', { method: 'POST', body: JSON.stringify(payload) }),
  unbindMapping: (mappingId: string) => request<unknown>('/api/v1/store-poi-mappings/' + mappingId + '/unbind', { method: 'POST', body: '{}' }),
  createProduct: (payload: Record<string, unknown>) => request<ProductRecord & { operation_id?: string }>('/api/v1/local-life/products', { method: 'POST', body: JSON.stringify(payload) }),
  updateStock: (skuId: string, payload: Record<string, unknown>) => request<unknown>('/api/v1/local-life/skus/' + skuId + '/stock', { method: 'PUT', body: JSON.stringify(payload) }),
  productAction: (productId: string, action: string, idempotencyKey: string) => request<unknown>('/api/v1/local-life/products/' + productId + '/actions/' + action, { method: 'POST', body: JSON.stringify({ idempotency_key: idempotencyKey }) }),
  syncOrder: (payload: { connection_id: string; external_order_id: string; idempotency_key: string }) => request<unknown>('/api/v1/local-life/orders/sync', { method: 'POST', body: JSON.stringify(payload) }),
  syncAfterSale: (payload: { order_id: string; external_after_sale_id: string; idempotency_key: string }) => request<unknown>('/api/v1/local-life/after-sales/sync', { method: 'POST', body: JSON.stringify(payload) }),
  vouchers: () => request<VoucherRecord[]>('/api/v1/local-life/vouchers'),
  consumeVoucher: (voucherId: string, payload: { store_id: string; idempotency_key?: string }) => request<unknown>('/api/v1/local-life/vouchers/' + voucherId + '/consume', { method: 'POST', body: JSON.stringify(payload) }),
  revokeVoucher: (voucherId: string, payload: { store_id?: string; idempotency_key?: string }) => request<unknown>('/api/v1/local-life/vouchers/' + voucherId + '/revoke', { method: 'POST', body: JSON.stringify(payload) }),
  syncAccounting: (payload: { connection_id: string; product_id: string; bill_date: string; idempotency_key: string }) => request<unknown>('/api/v1/local-life/accounting/sync', { method: 'POST', body: JSON.stringify(payload) }),
  retryOperation: (operationId: string) => request<OperationRecord>('/api/v1/operations/' + operationId + '/retry', { method: 'POST', body: '{}' }),
  retryOperationsBatch: (operationIds: string[]) => request<BatchRetryResponse>('/api/v1/operations/retry-batch', { method: 'POST', body: JSON.stringify({ operation_ids: operationIds }) }),
  retryWebhook: (eventId: string) => request<unknown>('/api/v1/webhook-events/' + eventId + '/retry', { method: 'POST', body: '{}' }),
  createConnection: (payload: Record<string, unknown>) => request<unknown>('/api/v1/connections', { method: 'POST', body: JSON.stringify(payload) }),
  inviteMember: (payload: Record<string, unknown>) => request<unknown>('/api/v1/members/invitations', { method: 'POST', body: JSON.stringify(payload) }),
}

export function dashboardValues(payload: DashboardSummary | { summary: DashboardSummary }): DashboardSummary {
  return 'summary' in payload ? payload.summary : payload
}
