import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Link, Navigate, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider, useAuth } from './auth/AuthProvider'
import { roleLabels } from './auth/roles'
import { AppShell } from './layout/AppShell'
import { DashboardPage } from './pages/DashboardPage'
import { LoginPage } from './pages/LoginPage'
import { StoresPage } from './pages/StoresPage'
import { ProductsPage } from './pages/ProductsPage'
import { OrdersPage } from './pages/OrdersPage'
import { AccountingPage } from './pages/AccountingPage'
import { PoisPage } from './pages/PoisPage'
import { MappingsPage } from './pages/MappingsPage'
import { ConnectionsPage } from './pages/ConnectionsPage'
import { OperationsPage } from './pages/OperationsPage'
import { WebhooksPage } from './pages/WebhooksPage'
import { AuditPage } from './pages/AuditPage'
import { MembersPage } from './pages/MembersPage'
import { TenantsPage } from './pages/TenantsPage'
import './styles.css'

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 30_000, retry: 1 } } })

function Protected() {
  const auth = useAuth()
  if (auth.status === 'loading') return <div className="app-loading">正在检查登录状态…</div>
  if (auth.status !== 'authenticated') return <Navigate to="/login" replace />
  if (!auth.tenant) {
    if (auth.user?.is_platform_admin) return <Routes>
      <Route path="/platform/tenants" element={<TenantsPage />} />
      <Route path="*" element={<TenantSelection />} />
    </Routes>
    return <TenantSelection />
  }
  return <AppShell><Routes>
    <Route path="/platform/tenants" element={<TenantsPage />} />
    <Route path="/dashboard" element={<DashboardPage />} />
    <Route path="/stores" element={<StoresPage />} />
    <Route path="/products" element={<ProductsPage />} />
    <Route path="/orders" element={<OrdersPage />} />
    <Route path="/accounting" element={<AccountingPage />} />
    <Route path="/pois" element={<PoisPage />} />
    <Route path="/mappings" element={<MappingsPage />} />
    <Route path="/connections" element={<ConnectionsPage />} />
    <Route path="/operations" element={<OperationsPage />} />
    <Route path="/webhooks" element={<WebhooksPage />} />
    <Route path="/audit" element={<AuditPage />} />
    <Route path="/members" element={<MembersPage />} />
    <Route path="*" element={<NotFoundPage />} />
  </Routes></AppShell>
}

function TenantSelection() {
  const auth = useAuth()
  return <main className="tenant-selection">
    <div className="login-brand"><span className="brand-mark">P</span><span>POI Hub</span></div>
    <span className="page-kicker">租户选择</span>
    <h1>选择工作租户</h1>
    <p>{auth.tenants.length ? '请选择本次要进入的运营空间。' : '当前账号还没有可访问的租户。'}</p>
    <div className="tenant-options">
      {auth.tenants.map(item => <button key={item.tenant_id} onClick={() => void auth.selectTenant(item.tenant_id)}><span><strong>{item.tenant_name}</strong><small>{roleLabels[item.role]}</small></span><span aria-hidden="true">→</span></button>)}
    </div>
    {auth.user?.is_platform_admin && <Link className="selection-logout" to="/platform/tenants">进入总部商户主控</Link>}
    <button className="selection-logout" onClick={() => void auth.logout()}>退出登录</button>
  </main>
}

function NotFoundPage() {
  return <section className="not-found-page"><span className="page-kicker">工作区</span><h2>页面不存在</h2><p>当前地址没有对应的运营模块。</p><Link className="not-found-link" to="/dashboard">返回运营总览</Link></section>
}

export function App() {
  return <QueryClientProvider client={queryClient}><AuthProvider><BrowserRouter><Routes><Route path="/login" element={<LoginRoute />} /><Route path="*" element={<Protected />} /></Routes></BrowserRouter></AuthProvider></QueryClientProvider>
}

function LoginRoute() {
  const auth = useAuth()
  if (auth.status === 'loading') return <div className="app-loading">正在检查登录状态…</div>
  if (auth.status === 'authenticated') return <Navigate to="/dashboard" replace />
  return <LoginPage />
}

if (document.getElementById('root')) createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)
