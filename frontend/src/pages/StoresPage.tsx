import { useQuery } from '@tanstack/react-query'
import { Button, Card, Space, Table, Tag, Typography } from 'antd'
import { RefreshCw } from 'lucide-react'
import { api, type StoreRecord } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { WorkspaceState } from './WorkspaceStates'
import { StoreEditor } from './StoreEditor'
import './workspace.css'

export function StoresPage() {
  const { tenant } = useAuth()
  const query = useQuery({ queryKey: ['stores', tenant?.id], queryFn: api.stores, enabled: Boolean(tenant) })
  const stores = query.data ?? []
  return <section className="workspace-page">
    <div className="page-heading"><div><Typography.Text className="page-kicker">门店与 POI</Typography.Text><Typography.Title level={2}>门店管理</Typography.Title><Typography.Paragraph>维护可复用的门店主数据与运营状态。</Typography.Paragraph></div><Space><Button icon={<RefreshCw size={15} />} onClick={() => void query.refetch()}>刷新</Button><StoreEditor /></Space></div>
    <Card className="workspace-table-card" variant="borderless">
      <WorkspaceState loading={query.isPending} error={query.error} empty={!stores.length}>
        <Table<StoreRecord> rowKey="id" dataSource={stores} pagination={{ pageSize: 10 }} columns={[
          { title: '门店编码', dataIndex: 'code', key: 'code' },
          { title: '门店名称', dataIndex: 'name', key: 'name' },
          { title: '地址', dataIndex: 'address', key: 'address', ellipsis: true },
          { title: '状态', dataIndex: 'status', key: 'status', render: (value: string) => <Tag color={value === 'active' ? 'green' : 'default'}>{value === 'active' ? '营业中' : '已停用'}</Tag> },
          { title: '操作', key: 'actions', render: () => <Button type="link">查看</Button> },
        ]} />
      </WorkspaceState>
    </Card>
  </section>
}
