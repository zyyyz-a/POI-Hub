import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider, useAuth } from './auth/AuthProvider'
import { AppShell } from './layout/AppShell'
import { DashboardPage } from './pages/DashboardPage'
import { LoginPage } from './pages/LoginPage'
import './styles.css'

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 30_000, retry: 1 } } })

function Protected() {
  const auth = useAuth()
  if (auth.status === 'loading') return <div className="app-loading">正在检查登录状态…</div>
  if (auth.status !== 'authenticated') return <Navigate to="/login" replace />
  if (!auth.tenant) return <TenantSelection />
  return <AppShell><Routes><Route path="/dashboard" element={<DashboardPage />} /><Route path="*" element={<PlaceholderPage />} /></Routes></AppShell>
}

function TenantSelection() {
  const auth = useAuth()
  return <main className="tenant-selection">
    <div className="login-brand"><span className="brand-mark">P</span><span>POI Hub</span></div>
    <span className="page-kicker">SELECT TENANT</span>
    <h1>选择工作租户</h1>
    <p>{auth.tenants.length ? '请选择本次要进入的运营空间。' : '当前账号还没有可访问的租户。'}</p>
    <div className="tenant-options">
      {auth.tenants.map(item => <button key={item.tenant_id} onClick={() => void auth.selectTenant(item.tenant_id)}><span><strong>{item.tenant_name}</strong><small>{item.role === 'platform_admin' ? '平台管理员' : item.role}</small></span><span aria-hidden="true">→</span></button>)}
    </div>
    <button className="selection-logout" onClick={() => void auth.logout()}>退出登录</button>
  </main>
}

function PlaceholderPage() {
  return <section className="placeholder-page"><span className="page-kicker">WORKSPACE</span><h2>页面正在准备中</h2><p>该模块的后端接口正在接入，运营总览可继续使用。</p></section>
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
