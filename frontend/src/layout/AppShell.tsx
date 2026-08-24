import { App as AntApp, Avatar, Button, Layout, Space, Tag, Tooltip } from 'antd'
import { LogoutOutlined, ShopOutlined, TeamOutlined, ApartmentOutlined, DashboardOutlined, LinkOutlined, GiftOutlined, ShoppingCartOutlined, SafetyCertificateOutlined, SwapOutlined, SyncOutlined, NotificationOutlined, ControlOutlined } from '@ant-design/icons'
import { Link, useLocation } from 'react-router-dom'
import { useState, type ReactNode } from 'react'
import { useAuth } from '../auth/AuthProvider'
import { roleLabels } from '../auth/roles'
import type { Role } from '../api/client'
import './shell.css'

const { Header, Sider, Content } = Layout

type NavItem = { key: string; label: string; icon: ReactNode; roles?: Role[] }
const navigation: NavItem[] = [
  { key: '/platform/tenants', label: '商户主控', icon: <ControlOutlined />, roles: ['platform_admin'] },
  { key: '/dashboard', label: '运营总览', icon: <DashboardOutlined /> },
  { key: '/stores', label: '门店管理', icon: <ShopOutlined />, roles: ['platform_admin', 'tenant_admin', 'operator', 'auditor'] },
  { key: '/pois', label: '服务 POI', icon: <ApartmentOutlined />, roles: ['platform_admin', 'tenant_admin', 'operator', 'auditor'] },
  { key: '/mappings', label: 'POI 映射', icon: <ApartmentOutlined />, roles: ['platform_admin', 'tenant_admin', 'operator', 'auditor'] },
  { key: '/products', label: '团购商品', icon: <GiftOutlined />, roles: ['platform_admin', 'tenant_admin', 'operator', 'auditor'] },
  { key: '/orders', label: '订单与券码', icon: <ShoppingCartOutlined />, roles: ['platform_admin', 'tenant_admin', 'operator', 'verifier', 'auditor'] },
  { key: '/accounting', label: '资金与对账', icon: <SwapOutlined />, roles: ['platform_admin', 'tenant_admin', 'operator', 'auditor'] },
  { key: '/operations', label: '操作中心', icon: <SyncOutlined />, roles: ['platform_admin', 'tenant_admin', 'operator', 'verifier', 'auditor'] },
  { key: '/webhooks', label: '回调收件箱', icon: <NotificationOutlined />, roles: ['platform_admin', 'tenant_admin', 'auditor'] },
  { key: '/connections', label: '微信连接', icon: <LinkOutlined />, roles: ['platform_admin', 'tenant_admin'] },
  { key: '/members', label: '成员管理', icon: <TeamOutlined />, roles: ['platform_admin', 'tenant_admin'] },
  { key: '/audit', label: '审计日志', icon: <SafetyCertificateOutlined />, roles: ['platform_admin', 'tenant_admin', 'auditor'] },
]

export function AppShell({ children }: { children: ReactNode }) {
  const auth = useAuth()
  const location = useLocation()
  const role = auth.user?.is_platform_admin ? 'platform_admin' : auth.membership?.role
  const items = navigation.filter(item => !item.roles || (role && item.roles.includes(role)))
  const active = items.find(item => location.pathname === item.key || location.pathname.startsWith(`${item.key}/`))?.key || '/dashboard'

  return <AntApp>
    <Layout className="poi-layout">
      <Sider breakpoint="lg" collapsedWidth="0" className="poi-sider">
        <div className="brand"><span className="brand-mark">P</span><span>POI Hub</span></div>
        <nav className="side-nav" aria-label="主导航">
          {items.map(item => <Link key={item.key} to={item.key} className={`nav-link ${active === item.key ? 'active' : ''}`}>{item.icon}<span>{item.label}</span></Link>)}
        </nav>
        <div className="sider-foot"><span className="status-dot" /> 中央 SaaS 服务</div>
      </Sider>
      <Layout>
        <Header className="poi-header">
          <div className="header-context">
            <span className="eyebrow">运营工作台</span>
            {auth.tenant && <TenantSwitcher />}
          </div>
          <Space size="middle">
            <Tag color="blue">{role ? roleLabels[role] : '未选择角色'}</Tag>
            <Avatar size="small" className="user-avatar">{auth.user?.display_name.slice(0, 1) || '?'}</Avatar>
            <span className="user-name">{auth.user?.display_name}</span>
            <Tooltip title="退出登录"><Button type="text" aria-label="退出登录" icon={<LogoutOutlined />} onClick={() => void auth.logout()} /></Tooltip>
          </Space>
        </Header>
        <Content className="poi-content">{children}</Content>
      </Layout>
    </Layout>
  </AntApp>
}

function TenantSwitcher() {
  const auth = useAuth()
  const [open, setOpen] = useState(false)
  return <div className="tenant-switcher">
    <button className="tenant-trigger" aria-label={`切换租户，当前为 ${auth.tenant?.name}`} onClick={() => setOpen(value => !value)}>
      <span className="tenant-label">当前租户</span><strong>{auth.tenant?.name}</strong><SwapOutlined />
    </button>
    {open && <div className="tenant-menu" role="menu">
      {auth.tenants.map(item => <button key={item.tenant_id} role="menuitem" disabled={item.tenant_id === auth.tenant?.id} onClick={() => { setOpen(false); void auth.selectTenant(item.tenant_id) }}>{item.tenant_name}<small>{roleLabels[item.role]}</small></button>)}
    </div>}
  </div>
}
