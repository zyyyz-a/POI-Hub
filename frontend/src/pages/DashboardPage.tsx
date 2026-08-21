import { Alert, Card, Col, Empty, Row, Skeleton, Tag, Typography } from 'antd'
import { ArrowUpRight, AlertTriangle, Box, MapPin, ClipboardCheck, Activity } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, dashboardValues, type DashboardSummary } from '../api/client'
import './dashboard.css'

type Metric = { key: keyof DashboardSummary; label: string; description: string; icon: typeof Box; tone: string }
const metrics: Metric[] = [
  { key: 'pending_audits', label: '待处理审计', description: '需要关注的运营记录', icon: ClipboardCheck, tone: 'amber' },
  { key: 'failed_operations', label: '失败操作', description: '等待重试或人工处理', icon: AlertTriangle, tone: 'red' },
  { key: 'low_stock', label: '低库存商品', description: '库存低于安全阈值', icon: Box, tone: 'blue' },
  { key: 'unmapped_stores', label: '待映射门店', description: '尚未确认 POI 的门店', icon: MapPin, tone: 'green' },
]

export function DashboardPage() {
  const [summary, setSummary] = useState<DashboardSummary>()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string>()

  useEffect(() => {
    let active = true
    api.dashboard().then(payload => { if (active) setSummary(dashboardValues(payload)) }).catch(err => { if (active) setError(err instanceof Error ? err.message : '仪表盘暂时无法加载') }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [])

  return <div className="dashboard-page">
    <div className="page-heading"><div><Typography.Text className="page-kicker">TODAY / OPERATIONS</Typography.Text><Typography.Title level={2}>运营总览</Typography.Title><Typography.Paragraph>快速了解门店、商品和订单的当前状态。</Typography.Paragraph></div><Tag icon={<Activity size={13} />} color="green">连接正常</Tag></div>
    {error && <Alert type="error" showIcon message={error} description="请稍后重试，或前往操作中心查看详细信息。" />}
    <Row gutter={[16, 16]} className="metric-grid" aria-label="运营指标" aria-busy={loading}>
      {metrics.map(metric => { const Icon = metric.icon; const value = Number(summary?.[metric.key] ?? 0); return <Col xs={24} sm={12} xl={6} key={metric.key}><Card className={`metric-card ${metric.tone}`} variant="borderless">{loading ? <Skeleton active paragraph={{ rows: 1 }} /> : <><div className="metric-top"><span className="metric-icon"><Icon size={18} /></span><ArrowUpRight size={16} className="metric-arrow" /></div><div className="metric-value">{value}</div><div className="metric-label">{metric.label}</div><div className="metric-description">{metric.description}</div></>}</Card></Col> })}
    </Row>
    <Row gutter={[16, 16]} className="dashboard-lower">
      <Col xs={24} lg={15}><Card title="运营动态" extra={<a href="/operations">查看全部</a>} variant="borderless" className="workspace-card">{loading ? <Skeleton active /> : error ? <Empty description="动态加载失败" /> : <div className="activity-empty"><span className="empty-icon"><Activity size={20} /></span><strong>暂无需要处理的动态</strong><span>新的订单、核销和同步事件会显示在这里</span></div>}</Card></Col>
      <Col xs={24} lg={9}><Card title="连接状态" variant="borderless" className="workspace-card connection-card"><div className="connection-row"><span><i className="status-dot" />微信本地生活</span><Tag color="green">Mock 正常</Tag></div><div className="connection-row"><span><i className="status-dot" />服务号 POI</span><Tag color="green">Mock 正常</Tag></div><div className="connection-foot">最后检查：刚刚</div></Card></Col>
    </Row>
  </div>
}
