import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Card, Table, Tag, Typography } from 'antd'
import { RefreshCw, RotateCcw } from 'lucide-react'
import { api, type OperationRecord } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { WorkspaceState } from './WorkspaceStates'
import './workspace.css'

export function OperationsPage() {
  const { tenant } = useAuth()
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['operations', tenant?.id], queryFn: api.operations, enabled: Boolean(tenant), refetchInterval: 5000 })
  const retry = useMutation({ mutationFn: api.retryOperation, onSuccess: async () => client.invalidateQueries({ queryKey: ['operations', tenant?.id] }) })
  const rows = (query.data ?? []) as OperationRecord[]
  return <section className="workspace-page"><div className="page-heading"><div><Typography.Text className="page-kicker">外部操作队列</Typography.Text><Typography.Title level={2}>操作中心</Typography.Title><Typography.Paragraph>查看微信命令的排队、执行、重试和终态错误。</Typography.Paragraph></div><Button icon={<RefreshCw size={15} />} onClick={() => void query.refetch()}>刷新</Button></div><Card className="workspace-table-card" variant="borderless"><WorkspaceState loading={query.isPending} error={query.error ?? retry.error} empty={!rows.length}><Table<OperationRecord> rowKey="id" dataSource={rows} columns={[{ title: '操作类型', dataIndex: 'command_type' }, { title: '状态', dataIndex: 'status', render: value => <Tag color={value === 'succeeded' ? 'green' : value === 'failed' ? 'red' : 'blue'}>{value}</Tag> }, { title: '尝试次数', dataIndex: 'attempt_count' }, { title: '错误', dataIndex: 'error_message', ellipsis: true, render: value => value || '-' }, { title: '操作', render: (_, row) => <Button icon={<RotateCcw size={14} />} disabled={!['failed', 'retry_wait'].includes(row.status)} loading={retry.isPending} onClick={() => retry.mutate(row.id)}>重试</Button> }]} /></WorkspaceState></Card></section>
}
