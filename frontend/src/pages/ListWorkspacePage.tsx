import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Card, Empty, Skeleton, Table, Tag, Typography } from 'antd'
import { RefreshCw } from 'lucide-react'
import { useAuth } from '../auth/AuthProvider'
import './workspace.css'

type Row = Record<string, unknown> & { id?: string }

const labels: Record<string, string> = {
  pois: '服务 POI', mappings: 'POI 映射', connections: '微信连接', operations: '操作中心', webhooks: '回调事件', audit: '审计日志', members: '成员管理',
}

const fieldLabels: Record<string, string> = {
  capability: '能力', mode: '模式', status: '状态', command_type: '操作类型', error_code: '错误码',
  email: '邮箱', display_name: '姓名', role: '角色', event_type: '事件类型', action: '动作', resource: '资源',
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '-'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

export function ListWorkspacePage({ kind, queryFn }: { kind: keyof typeof labels; queryFn: () => Promise<Row[]> }) {
  const { tenant } = useAuth()
  const query = useQuery({ queryKey: [kind, tenant?.id], queryFn, enabled: Boolean(tenant) })
  const rows = query.data ?? []
  const keys = rows.length ? Object.keys(rows[0]).filter(key => key !== 'id' && !key.endsWith('_at')).slice(0, 5) : []
  return <section className="workspace-page">
    <div className="page-heading"><div><Typography.Text className="page-kicker">运营工作区</Typography.Text><Typography.Title level={2}>{labels[kind]}</Typography.Title><Typography.Paragraph>按当前租户查看可操作记录，敏感字段由服务端脱敏。</Typography.Paragraph></div><Button icon={<RefreshCw size={15} />} onClick={() => void query.refetch()}>刷新</Button></div>
    <Card className="workspace-table-card" variant="borderless">
      {query.isPending && <div className="workspace-state"><Skeleton active paragraph={{ rows: 4 }} /></div>}
      {query.isError && <Alert type="error" showIcon message={query.error instanceof Error ? query.error.message : '数据加载失败'} description="请稍后重试" />}
      {!query.isPending && !query.isError && !rows.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无数据" />}
      {!query.isPending && !query.isError && Boolean(rows.length) && <Table<Row> rowKey="id" dataSource={rows} pagination={{ pageSize: 10 }} scroll={{ x: 720 }} columns={keys.map(key => ({ title: fieldLabels[key] ?? key, dataIndex: key, key, render: (value: unknown) => key === 'status' || key === 'mode' ? <Tag>{displayValue(value)}</Tag> : displayValue(value) }))} />}
    </Card>
  </section>
}
