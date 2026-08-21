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
}

export class ApiError extends Error {
  status: number
  code?: string

  constructor(message: string, status: number, code?: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

let csrfToken: string | undefined

export function setCsrfToken(value: string | undefined) {
  csrfToken = value
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  if (csrfToken && init.method && init.method !== 'GET') headers.set('X-CSRF-Token', csrfToken)

  const response = await fetch(path, { ...init, credentials: 'include', headers })
  if (response.status === 204) return undefined as T
  const payload = await response.json().catch(() => ({})) as { detail?: string; message?: string; code?: string }
  if (!response.ok) {
    const detail = typeof payload.detail === 'string' ? payload.detail : payload.message
    throw new ApiError(detail || '请求失败，请稍后重试', response.status, payload.code)
  }
  return payload as T
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
  dashboard: () => request<DashboardSummary | { summary: DashboardSummary }>('/api/v1/dashboard'),
}

export function dashboardValues(payload: DashboardSummary | { summary: DashboardSummary }): DashboardSummary {
  return 'summary' in payload ? payload.summary : payload
}
