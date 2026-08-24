import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Card, Modal, Space, Table, Tag, Typography } from 'antd'
import { RefreshCw } from 'lucide-react'
import { api, type StoreRecord } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { WorkspaceState } from './WorkspaceStates'
import { StoreEditor } from './StoreEditor'
import './workspace.css'

export function StoresPage() {
  const { tenant } = useAuth()
  const client = useQueryClient()
  const query = useQuery({ queryKey: ['stores', tenant?.id], queryFn: api.stores, enabled: Boolean(tenant) })
  const stores = query.data ?? []
  const archive = useMutation({ mutationFn: ({ id, version }: { id: string; version: number }) => api.archiveStore(id, version), onSuccess: async () => client.invalidateQueries({ queryKey: ['stores', tenant?.id] }) })
  return <section className="workspace-page">
    <div className="page-heading"><div><Typography.Text className="page-kicker">门店与 POI</Typography.Text><Typography.Title level={2}>门店管理</Typography.Title><Typography.Paragraph>维护可复用的门店主数据与运营状态。</Typography.Paragraph></div><Space><Button icon={<RefreshCw size={15} />} onClick={() => void query.refetch()}>刷新</Button><StoreEditor /></Space></div>
    <Card className="workspace-table-card" variant="borderless">
      <WorkspaceState loading={query.isPending} error={query.error} empty={!stores.length}>
        <Table<StoreRecord> rowKey="id" dataSource={stores} pagination={{ pageSize: 10 }} columns={[
          { title: '门店编码', dataIndex: 'code', key: 'code' },
          { title: '门店名称', dataIndex: 'name', key: 'name' },
          { title: '地址', dataIndex: 'address', key: 'address', ellipsis: true },
          { title: '状态', dataIndex: 'status', key: 'status', render: (value: string) => <Tag color={value === 'active' ? 'green' : 'default'}>{value === 'active' ? '营业中' : '已停用'}</Tag> },
          { title: '操作', key: 'actions', render: (_, row) => <Space><StoreEditor store={row} /><Button type="link" danger disabled={row.status !== 'active'} loading={archive.isPending} onClick={() => Modal.confirm({ title: '归档门店？', content: '归档会解除当前活动 POI 映射。', okText: '确认归档', okButtonProps: { danger: true }, cancelText: '取消', onOk: () => archive.mutate({ id: row.id, version: row.version ?? 1 }) })}>归档</Button></Space> },
        ]} />
      </WorkspaceState>
    </Card>
  </section>
}
