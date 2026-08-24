import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api, setCsrfToken, type LoginResponse, type Membership, type MeResponse, type Tenant, type User } from '../api/client'

export type AuthStatus = 'loading' | 'unauthenticated' | 'authenticated'

export interface AuthContextValue {
  status: AuthStatus
  user: User | null
  tenant: Tenant | null
  membership: Membership | null
  tenants: Membership[]
  csrfToken?: string
  error?: string
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
  selectTenant: (tenantId: string) => Promise<void>
  refresh: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)

async function resolveTenants(user: User, memberships: Membership[]): Promise<Membership[]> {
  if (!user.is_platform_admin) return memberships
  const tenants = await api.platformTenants()
  return tenants.filter(tenant => tenant.status === 'active').map(tenant => ({
    id: `platform-${tenant.id}`,
    tenant_id: tenant.id,
    tenant_name: tenant.name,
    user_id: user.id,
    email: user.email,
    display_name: user.display_name,
    role: 'platform_admin',
    status: tenant.status,
  }))
}

function stateFromMe(result: MeResponse, tenants: Membership[] = []): Pick<AuthContextValue, 'user' | 'tenant' | 'membership' | 'tenants'> {
  return { user: result.user, tenant: result.tenant, membership: result.membership, tenants }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<Pick<AuthContextValue, 'user' | 'tenant' | 'membership' | 'tenants'>>({ user: null, tenant: null, membership: null, tenants: [] })
  const [status, setStatus] = useState<AuthStatus>('loading')
  const [csrfToken, setToken] = useState<string>()
  const [error, setError] = useState<string>()

  const refresh = useCallback(async () => {
    setError(undefined)
    try {
      const result = await api.me()
      const token = await api.csrf()
      const tenants = await resolveTenants(result.user, result.tenants)
      setToken(token)
      setState(stateFromMe(result, tenants))
      setStatus('authenticated')
    } catch (err) {
      if (err instanceof Error && 'status' in err && (err as { status: number }).status === 401) {
        setState({ user: null, tenant: null, membership: null, tenants: [] })
        setStatus('unauthenticated')
      } else {
        setError(err instanceof Error ? err.message : '无法读取登录状态')
        setStatus('unauthenticated')
      }
    }
  }, [])

  useEffect(() => { void refresh() }, [refresh])

  const login = useCallback(async (email: string, password: string) => {
    setError(undefined)
    const result: LoginResponse = await api.login(email, password)
    const tenants = await resolveTenants(result.user, result.tenants)
    setToken(result.csrf_token)
    setState(current => ({ ...current, user: result.user, tenants }))
    if (tenants.length === 1) {
      const selected = await api.selectTenant(tenants[0].tenant_id)
      setState(stateFromMe(selected, tenants))
    } else {
      setStatus('authenticated')
    }
    setStatus('authenticated')
  }, [])

  const selectTenant = useCallback(async (tenantId: string) => {
    const result = await api.selectTenant(tenantId)
    setState(current => stateFromMe(result, current.tenants))
    setStatus('authenticated')
  }, [])

  const logout = useCallback(async () => {
    try { await api.logout() } finally {
      setCsrfToken(undefined)
      setToken(undefined)
      setState({ user: null, tenant: null, membership: null, tenants: [] })
      setStatus('unauthenticated')
    }
  }, [])

  const value = useMemo<AuthContextValue>(() => ({ ...state, status, csrfToken, error, login, logout, selectTenant, refresh }), [state, status, csrfToken, error, login, logout, selectTenant, refresh])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth 必须在 AuthProvider 内使用')
  return value
}
