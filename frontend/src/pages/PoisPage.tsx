import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Card, Select, Space, Table, Tag, Typography } from 'antd'
import { RefreshCw } from 'lucide-react'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { WorkspaceState } from './WorkspaceStates'
import './workspace.css'

type Poi = { id: string; external_poi_id: string; name: string; address: string; remote_status: string }
type Connection = { id: string; capability: string }

export function PoisPage() {
  const { tenant } = useAuth()
  const client = useQueryClient()
  const pois = useQuery({ queryKey: ['pois', tenant?.id], queryFn: api.pois, enabled: Boolean(tenant) })
  const connections = useQuery({ queryKey: ['connections', tenant?.id], queryFn: api.connections, enabled: Boolean(tenant) })
  const connectionRows = Array.isArray(connections.data) ? connections.data : []
  const poiConnections = connectionRows.filter(item => (item as Connection).capability === 'service_poi') as Connection[]
  const sync = useMutation({ mutationFn: (connection_id: string) => api.syncPois({ connection_id, idempotency_key: 'poi-sync:' + Date.now() }), onSuccess: async () => client.invalidateQueries({ queryKey: ['operations', tenant?.id] }) })
  const rows = (pois.data ?? []) as Poi[]
  return <section className="workspace-page">
    <div className="page-heading"><div><Typography.Text className="page-kicker">腾讯地图镜像</Typography.Text><Typography.Title level={2}>服务 POI</Typography.Title><Typography.Paragraph>同步微信服务 POI 后生成可解释的门店匹配候选。</Typography.Paragraph></div><Space><Select className="workspace-select" placeholder="选择 POI 连接并同步" options={poiConnections.map(item => ({ value: item.id, label: item.id }))} onChange={value => sync.mutate(value)} /><Button icon={<RefreshCw size={15} />} onClick={() => void pois.refetch()}>刷新</Button></Space></div>
    {sync.isSuccess && <p className="operation-note">同步操作已进入队列。</p>}
    <Card className="workspace-table-card" variant="borderless"><WorkspaceState loading={pois.isPending} error={pois.error ?? sync.error} empty={!rows.length}><Table<Poi> rowKey="id" dataSource={rows} columns={[{ title: 'POI ID', dataIndex: 'external_poi_id' }, { title: '名称', dataIndex: 'name' }, { title: '地址', dataIndex: 'address', ellipsis: true }, { title: '状态', dataIndex: 'remote_status', render: value => <Tag>{value}</Tag> }]} /></WorkspaceState></Card>
  </section>
}
