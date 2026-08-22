import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, Col, Row, Select, Space, Statistic, Typography } from 'antd'
import { RefreshCw } from 'lucide-react'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { WorkspaceState } from './WorkspaceStates'
import './workspace.css'

export function AccountingPage() {
  const { tenant } = useAuth()
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['accounting', tenant?.id], queryFn: api.accounting, enabled: Boolean(tenant) })
  const connections = useQuery({ queryKey: ['connections', tenant?.id], queryFn: api.connections, enabled: Boolean(tenant) })
  const connectionRows = Array.isArray(connections.data) ? connections.data : []
  const sync = useMutation({ mutationFn: (connection_id: string) => api.syncAccounting({ connection_id, idempotency_key: 'accounting-sync:' + Date.now() }), onSuccess: async () => { await client.invalidateQueries({ queryKey: ['accounting', tenant?.id] }); await client.invalidateQueries({ queryKey: ['operations', tenant?.id] }) } })
  const summary = query.data
  return <section className="workspace-page">
    <div className="page-heading"><div><Typography.Text className="page-kicker">结算与财务</Typography.Text><Typography.Title level={2}>资金与对账</Typography.Title><Typography.Paragraph>核对微信资金流水、券账单和差异。</Typography.Paragraph></div><Space><Select className="workspace-select" placeholder="选择连接并同步" options={connectionRows.filter(item => (item as { capability?: string }).capability === 'local_life').map(item => ({ value: (item as { id: string }).id, label: (item as { id: string }).id }))} onChange={value => sync.mutate(value)} /><Button icon={<RefreshCw size={15} />} onClick={() => void query.refetch()}>刷新</Button></Space></div>
    <Card className="workspace-table-card" variant="borderless"><WorkspaceState loading={query.isPending} error={query.error} empty={!summary}>
      {summary && <><Row gutter={[16, 16]}><Col xs={24} sm={8}><Card size="small"><Statistic title="资金流水" value={summary.fund_count} /></Card></Col><Col xs={24} sm={8}><Card size="small"><Statistic title="券账单" value={summary.bill_count} /></Card></Col><Col xs={24} sm={8}><Card size="small"><Statistic title="待处理差异" value={summary.difference_count} /></Card></Col></Row>{summary.difference_count > 0 && <Alert className="workspace-alert" type="warning" showIcon message="发现对账差异" description={'净差额 ' + String((summary.difference ?? 0) / 100) + ' 元'} />}</>}
    </WorkspaceState></Card>
  </section>
}
