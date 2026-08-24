import { useQuery } from '@tanstack/react-query'
import { Alert, Card, Col, Row, Skeleton, Typography } from 'antd'
import { AlertTriangle, ArrowUpRight, ClipboardCheck, Link2Off, MapPin, PackageSearch, Scale } from 'lucide-react'
import { api, dashboardValues, type DashboardSummary } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import './dashboard.css'

type Metric = { key: keyof DashboardSummary; label: string; description: string; icon: typeof MapPin; tone: string }
const metrics: Metric[] = [
  { key: 'failed_operations', label: '失败操作', description: '等待重试或人工处理', icon: AlertTriangle, tone: 'red' },
  { key: 'unmapped_stores', label: '待映射门店', description: '尚未确认 POI 的门店', icon: MapPin, tone: 'green' },
  { key: 'pending_audits', label: '待处理审核', description: '等待微信商品审核结果', icon: ClipboardCheck, tone: 'amber' },
  { key: 'low_stock', label: '低库存商品', description: '库存低于运营目标的 SKU', icon: PackageSearch, tone: 'blue' },
  { key: 'reconciliation_differences', label: '对账差异', description: '资金流水与券账单的差异', icon: Scale, tone: 'amber' },
  { key: 'unhealthy_connections', label: '异常连接', description: '需要重新授权或检查的微信连接', icon: Link2Off, tone: 'red' },
]

export function DashboardPage() {
  const { tenant } = useAuth()
  const summaryQuery = useQuery({
    queryKey: ['dashboard', tenant?.id],
    queryFn: async () => dashboardValues(await api.dashboard()),
    enabled: Boolean(tenant),
    staleTime: 0,
  })
  const visibleMetrics = summaryQuery.isPending
    ? metrics
    : metrics.filter(metric => typeof summaryQuery.data?.[metric.key] === 'number')

  return <div className="dashboard-page">
    <div className="page-heading"><div><Typography.Text className="page-kicker">今日运营</Typography.Text><Typography.Title level={2}>运营总览</Typography.Title><Typography.Paragraph>快速了解门店、商品和订单的当前状态。</Typography.Paragraph></div></div>
    {summaryQuery.isError ? <Alert type="error" showIcon message={summaryQuery.error instanceof Error ? summaryQuery.error.message : '仪表盘暂时无法加载'} description="请稍后重试，或前往操作中心查看详细信息。" /> :
      <Row gutter={[16, 16]} className="metric-grid" aria-label="运营指标" aria-busy={summaryQuery.isPending}>
        {visibleMetrics.map(metric => {
          const Icon = metric.icon
          return <Col xs={24} sm={12} key={metric.key}><Card className={`metric-card ${metric.tone}`} variant="borderless">
            {summaryQuery.isPending ? <Skeleton active paragraph={{ rows: 1 }} /> : <>
              <div className="metric-top"><span className="metric-icon"><Icon size={18} /></span><ArrowUpRight size={16} className="metric-arrow" /></div>
              <div className="metric-value">{summaryQuery.data?.[metric.key]}</div>
              <div className="metric-label">{metric.label}</div>
              <div className="metric-description">{metric.description}</div>
            </>}
          </Card></Col>
        })}
      </Row>}
  </div>
}
