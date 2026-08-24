import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, Table, Tag, Typography } from 'antd'
import { RefreshCw, RotateCcw } from 'lucide-react'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { WorkspaceState } from './WorkspaceStates'
import './workspace.css'

type WebhookRow = { id: string; event_type: string; status: string; attempt_count: number; received_at?: string; error_message?: string | null }

export function WebhooksPage() {
  const { tenant, membership, user } = useAuth()
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['webhooks', tenant?.id], queryFn: api.webhooks, enabled: Boolean(tenant) })
  const retry = useMutation({ mutationFn: api.retryWebhook, onSuccess: async () => client.invalidateQueries({ queryKey: ['webhooks', tenant?.id] }) })
  const editable = Boolean(user?.is_platform_admin || ['tenant_admin', 'operator'].includes(membership?.role ?? ''))
  const rows = (query.data ?? []) as WebhookRow[]
  return <section className="workspace-page">
    <div className="page-heading"><div><Typography.Text className="page-kicker">微信事件</Typography.Text><Typography.Title level={2}>回调收件箱</Typography.Title><Typography.Paragraph>查看签名校验后的事件、处理结果和可重试错误。</Typography.Paragraph></div><Button icon={<RefreshCw size={15} />} onClick={() => void query.refetch()}>刷新</Button></div>
    {retry.isSuccess && <Alert className="workspace-alert" type="success" showIcon message="回调已重新排队" />}
    <Card className="workspace-table-card" variant="borderless"><WorkspaceState loading={query.isPending} error={query.error ?? retry.error} empty={!rows.length}>
      <Table<WebhookRow> rowKey="id" dataSource={rows} pagination={{ pageSize: 10 }} columns={[{ title: '事件类型', dataIndex: 'event_type' }, { title: '状态', dataIndex: 'status', render: value => <Tag color={value === 'processed' ? 'green' : value === 'dead_letter' ? 'red' : value === 'retry_wait' ? 'orange' : 'blue'}>{value}</Tag> }, { title: '尝试次数', dataIndex: 'attempt_count' }, { title: '接收时间', dataIndex: 'received_at' }, { title: '错误', dataIndex: 'error_message', ellipsis: true, render: value => value || '-' }, { title: '操作', render: (_, row) => editable && ['failed', 'retry_wait', 'dead_letter'].includes(row.status) && <Button type="link" icon={<RotateCcw size={14} />} loading={retry.isPending} onClick={() => retry.mutate(row.id)}>重新处理</Button> }]} />
    </WorkspaceState></Card>
  </section>
}
