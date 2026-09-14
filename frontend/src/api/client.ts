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

export interface QualificationItem {
  code: string
  label: string
  required: boolean
  present: boolean
  verified: boolean
  evidence_reference?: string | null
  note?: string | null
}

export interface OnboardingCaseRecord {
  id: string
  store_id: string
  route: string
  category_code: string
  category_name: string
  subject_type: string
  region_code?: string | null
  stage: string
  status: string
  requirements: QualificationItem[]
  precheck_status: string
  official_status: string
  official_reference?: string | null
  position_status: string
  blocker_message?: string | null
  next_action?: string | null
  version: number
}

export interface MiniProgramRecord {
  id: string
  connection_id?: string | null
  name: string
  app_id?: string | null
  owner_subject: string
  ownership_mode: string
  status: string
  authorization_reference?: string | null
  payment_merchant_id?: string | null
  payment_owner_verified: boolean
  video_channel_id?: string | null
  location_service_status: string
  callback_configured: boolean
  version: number
}

export interface PositionServiceRecord {
  id: string
  onboarding_case_id: string
  store_id: string
  service_poi_id?: string | null
  mini_program_id: string
  service_type: string
  service_name: string
  entry_path: string
  status: string
  official_reference?: string | null
  evidence_reference?: string | null
  last_error?: string | null
  version: number
}

export interface OnboardingReadiness {
  case_id: string
  ready: boolean
  blockers: string[]
  checks: Record<string, boolean>
}

export interface DirectProductRecord {
  id: string
  mini_program_id: string
  store_id: string
  merchant_product_id: string
  name: string
  description: string
  cover_image?: string | null
  sale_price: number
  market_price: number
  stock: number
  sold_count: number
  appointment_required: boolean
  service_minutes: number
  status: string
  version: number
}

export interface DirectOrderRecord {
  id: string
  order_no: string
  product_name: string
  quantity: number
  total_amount: number
  paid_amount: number
  refunded_amount: number
  status: string
  created_at: string
  paid_at?: string | null
}

export interface DirectAppointmentRecord {
  id: string
  order_id: string
  store_id: string
  starts_at: string
  contact_name: string
  contact_phone_masked: string
  note?: string | null
  status: string
  version: number
}

export interface DirectVoucherRecord {
  id: string
  order_id: string
  code_masked: string
  state: string
  valid_until: string
  consume_store_id?: string | null
  consumed_at?: string | null
  version: number
}

export interface PlatformMiniProgramRecord {
  id: string
  name: string
  app_id?: string | null
  owner_subject: string
  connection_id?: string | null
  status: string
  callback_configured: boolean
  version: number
}

export interface StoreBindingRecord {
  id: string
  platform_mini_program_id: string
  tenant_id: string
  store_id: string
  store_code: string
  tencent_poi_id?: string | null
  entry_path?: string | null
  entry_scene?: string | null
  status: string
  official_reference?: string | null
  evidence_reference?: string | null
  version: number
}

export interface PaymentProfileRecord {
  id: string
  tenant_id: string
  store_id: string
  connection_id?: string | null
  mode: string
  mchid?: string | null
  sub_mchid?: string | null
  sp_mchid?: string | null
  verified: boolean
  status: string
  version: number
}

export interface RefundRecord {
  id: string
  tenant_id: string
  order_id: string
  store_id: string
  refund_no: string
  amount: number
  reason?: string | null
  status: string
  transaction_id?: string | null
  wechat_refund_id?: string | null
  version: number
  created_at: string
  updated_at: string
}

export interface BillingPlanRecord {
  id: string
  code: string
  name: string
  description: string
  price: number
  billing_period: string
  period_days: number
  status: string
  version: number
}

export interface SubscriptionRecord {
  id: string
  tenant_id: string
  plan_id: string
  status: string
  current_period_start: string
  current_period_end: string
  grace_until?: string | null
  version: number
}

export interface InvoiceRecord {
  id: string
  tenant_id: string
  subscription_id?: string | null
  invoice_no: string
  period_start?: string | null
  period_end?: string | null
  amount: number
  paid_amount: number
  status: string
  issued_at: string
  due_at?: string | null
  version: number
}

export interface BillingSummaryRecord {
  subscription: SubscriptionRecord | null
  plan: BillingPlanRecord | null
  outstanding_amount: number
  blocked: boolean
  blockers: string[]
}

export interface ReconciliationBatchRecord {
  id: string
  tenant_id: string
  provider: string
  bill_date: string
  source: string
  statement_total: number
  platform_total: number
  matched_count: number
  difference_count: number
  status: string
  created_at: string
}

export interface ReconciliationItemRecord {
  id: string
  batch_id: string
  order_no?: string | null
  transaction_id?: string | null
  statement_amount?: number | null
  platform_amount?: number | null
  status: string
  note?: string | null
  resolved: boolean
  resolved_note?: string | null
  created_at: string
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
  onboardingCases: () => request<OnboardingCaseRecord[]>('/api/v1/onboarding/cases'),
  createOnboardingCase: (payload: Record<string, unknown>) => request<OnboardingCaseRecord>('/api/v1/onboarding/cases', { method: 'POST', body: JSON.stringify(payload) }),
  runOnboardingPrecheck: (caseId: string, payload: { items: QualificationItem[]; rule_source_reference: string }) => request<OnboardingCaseRecord>(`/api/v1/onboarding/cases/${caseId}/precheck`, { method: 'POST', body: JSON.stringify(payload) }),
  recordOfficialSubmission: (caseId: string, payload: { official_reference: string; evidence_reference: string }) => request<OnboardingCaseRecord>(`/api/v1/onboarding/cases/${caseId}/official-submission`, { method: 'POST', body: JSON.stringify(payload) }),
  recordOfficialDecision: (caseId: string, payload: { decision: string; evidence_reference: string; message?: string }) => request<OnboardingCaseRecord>(`/api/v1/onboarding/cases/${caseId}/official-decision`, { method: 'POST', body: JSON.stringify(payload) }),
  onboardingReadiness: (caseId: string) => request<OnboardingReadiness>(`/api/v1/onboarding/cases/${caseId}/readiness`),
  miniPrograms: () => request<MiniProgramRecord[]>('/api/v1/mini-programs'),
  createMiniProgram: (payload: Record<string, unknown>) => request<MiniProgramRecord>('/api/v1/mini-programs', { method: 'POST', body: JSON.stringify(payload) }),
  updateMiniProgram: (miniProgramId: string, payload: Record<string, unknown>) => request<MiniProgramRecord>(`/api/v1/mini-programs/${miniProgramId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  positionServices: () => request<PositionServiceRecord[]>('/api/v1/position-services'),
  createPositionService: (payload: Record<string, unknown>) => request<PositionServiceRecord>('/api/v1/position-services', { method: 'POST', body: JSON.stringify(payload) }),
  transitionPositionService: (mountId: string, payload: Record<string, unknown>) => request<PositionServiceRecord>(`/api/v1/position-services/${mountId}/transition`, { method: 'POST', body: JSON.stringify(payload) }),
  directProducts: () => request<DirectProductRecord[]>('/api/v1/direct-commerce/products'),
  createDirectProduct: (payload: Record<string, unknown>) => request<DirectProductRecord>('/api/v1/direct-commerce/products', { method: 'POST', body: JSON.stringify(payload) }),
  updateDirectProduct: (productId: string, payload: Record<string, unknown>) => request<DirectProductRecord>(`/api/v1/direct-commerce/products/${productId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  directOrders: () => request<DirectOrderRecord[]>('/api/v1/direct-commerce/orders'),
  directAppointments: () => request<DirectAppointmentRecord[]>('/api/v1/direct-commerce/appointments'),
  directVouchers: () => request<DirectVoucherRecord[]>('/api/v1/direct-commerce/vouchers'),
  consumeDirectVoucher: (payload: { code: string; store_id: string }) => request<DirectVoucherRecord>('/api/v1/direct-commerce/vouchers/consume', { method: 'POST', body: JSON.stringify(payload) }),
  revokeDirectVoucher: (voucherId: string, payload: { version: number; reason: string }) => request<DirectVoucherRecord>(`/api/v1/direct-commerce/vouchers/${voucherId}/revoke`, { method: 'POST', body: JSON.stringify(payload) }),
  platformMiniPrograms: () => request<PlatformMiniProgramRecord[]>('/api/v1/platform/mini-programs'),
  createPlatformMiniProgram: (payload: Record<string, unknown>) => request<PlatformMiniProgramRecord>('/api/v1/platform/mini-programs', { method: 'POST', body: JSON.stringify(payload) }),
  updatePlatformMiniProgram: (programId: string, payload: Record<string, unknown>) => request<PlatformMiniProgramRecord>(`/api/v1/platform/mini-programs/${programId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  storeBindings: () => request<StoreBindingRecord[]>('/api/v1/store-bindings'),
  createStoreBinding: (payload: Record<string, unknown>) => request<StoreBindingRecord>('/api/v1/store-bindings', { method: 'POST', body: JSON.stringify(payload) }),
  updateStoreBinding: (bindingId: string, payload: Record<string, unknown>) => request<StoreBindingRecord>(`/api/v1/store-bindings/${bindingId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  paymentProfiles: () => request<PaymentProfileRecord[]>('/api/v1/direct-commerce/payment-profiles'),
  createPaymentProfile: (payload: Record<string, unknown>) => request<PaymentProfileRecord>('/api/v1/direct-commerce/payment-profiles', { method: 'POST', body: JSON.stringify(payload) }),
  updatePaymentProfile: (profileId: string, payload: Record<string, unknown>) => request<PaymentProfileRecord>(`/api/v1/direct-commerce/payment-profiles/${profileId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  directRefunds: () => request<RefundRecord[]>('/api/v1/direct-commerce/refunds'),
  createDirectRefund: (orderId: string, payload: { amount: number; reason?: string; idempotency_key: string }) => request<RefundRecord>(`/api/v1/direct-commerce/orders/${orderId}/refunds`, { method: 'POST', body: JSON.stringify(payload) }),
  queryDirectOrder: (orderId: string) => request<DirectOrderRecord>(`/api/v1/direct-commerce/orders/${orderId}/query`, { method: 'POST', body: '{}' }),
  billingPlans: () => request<BillingPlanRecord[]>('/api/v1/billing/plans'),
  createBillingPlan: (payload: Record<string, unknown>) => request<BillingPlanRecord>('/api/v1/billing/plans', { method: 'POST', body: JSON.stringify(payload) }),
  updateBillingPlan: (planId: string, payload: Record<string, unknown>) => request<BillingPlanRecord>(`/api/v1/billing/plans/${planId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  billingSubscriptions: () => request<SubscriptionRecord[]>('/api/v1/billing/subscriptions'),
  createBillingSubscription: (payload: Record<string, unknown>) => request<SubscriptionRecord>('/api/v1/billing/subscriptions', { method: 'POST', body: JSON.stringify(payload) }),
  updateBillingSubscription: (subscriptionId: string, payload: Record<string, unknown>) => request<SubscriptionRecord>(`/api/v1/billing/subscriptions/${subscriptionId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  billingInvoices: () => request<InvoiceRecord[]>('/api/v1/billing/invoices'),
  generateBillingInvoice: (payload: Record<string, unknown>) => request<InvoiceRecord>('/api/v1/billing/invoices', { method: 'POST', body: JSON.stringify(payload) }),
  recordBillingUsage: (payload: Record<string, unknown>) => request<unknown>('/api/v1/billing/usage-events', { method: 'POST', body: JSON.stringify(payload) }),
  recordBillingPayment: (invoiceId: string, payload: Record<string, unknown>) => request<unknown>(`/api/v1/billing/invoices/${invoiceId}/payments`, { method: 'POST', body: JSON.stringify(payload) }),
  recordBillingAdjustment: (invoiceId: string, payload: Record<string, unknown>) => request<unknown>(`/api/v1/billing/invoices/${invoiceId}/adjustments`, { method: 'POST', body: JSON.stringify(payload) }),
  billingSummary: () => request<BillingSummaryRecord>('/api/v1/billing/summary'),
  reconciliationBatches: () => request<ReconciliationBatchRecord[]>('/api/v1/direct-commerce/reconciliation/batches'),
  importReconciliation: (payload: { bill_date: string; csv?: string; rows?: Array<Record<string, unknown>> }) => request<ReconciliationBatchRecord>('/api/v1/direct-commerce/reconciliation/import', { method: 'POST', body: JSON.stringify(payload) }),
  reconciliationItems: (batchId: string) => request<ReconciliationItemRecord[]>(`/api/v1/direct-commerce/reconciliation/batches/${batchId}/items`),
  resolveReconciliationItem: (itemId: string, note: string) => request<ReconciliationItemRecord>(`/api/v1/direct-commerce/reconciliation/items/${itemId}/resolve`, { method: 'POST', body: JSON.stringify({ note }) }),
}

export function dashboardValues(payload: DashboardSummary | { summary: DashboardSummary }): DashboardSummary {
  return 'summary' in payload ? payload.summary : payload
}
