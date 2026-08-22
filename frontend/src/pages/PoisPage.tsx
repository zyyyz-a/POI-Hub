import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Card, Form, Input, Modal, Select, Space, Table, Tag, Typography } from 'antd'
import { RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { api, type PoiRecord } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { WorkspaceState } from './WorkspaceStates'
import './workspace.css'

type Connection = { id: string; capability: string }

export function PoisPage() {
  const { tenant } = useAuth()
  const client = useQueryClient()
  const pois = useQuery({ queryKey: ['pois', tenant?.id], queryFn: api.pois, enabled: Boolean(tenant) })
  const connections = useQuery({ queryKey: ['connections', tenant?.id], queryFn: api.connections, enabled: Boolean(tenant) })
  const connectionRows = Array.isArray(connections.data) ? connections.data : []
  const poiConnections = connectionRows.filter(item => (item as Connection).capability === 'service_poi') as Connection[]
  const [createOpen, setCreateOpen] = useState(false)
  const [form] = Form.useForm()
  const sync = useMutation({ mutationFn: (connection_id: string) => api.syncPois({ connection_id, idempotency_key: 'poi-sync:' + Date.now() }), onSuccess: async () => { await client.invalidateQueries({ queryKey: ['operations', tenant?.id] }); await client.invalidateQueries({ queryKey: ['pois', tenant?.id] }) } })
  const create = useMutation({ mutationFn: api.createPoi, onSuccess: async () => { setCreateOpen(false); form.resetFields(); await client.invalidateQueries({ queryKey: ['pois', tenant?.id] }) } })
  const action = useMutation({ mutationFn: ({ id, kind }: { id: string; kind: 'delete' | 'audit' }) => kind === 'delete' ? api.deletePoi(id, 'poi-delete:' + id + ':' + Date.now()) : api.refreshPoiAudit(id, 'poi-audit:' + id + ':' + Date.now()), onSuccess: async () => client.invalidateQueries({ queryKey: ['pois', tenant?.id] }) })
  const rows = (pois.data ?? []) as PoiRecord[]
  return <section className="workspace-page">
    <div className="page-heading"><div><Typography.Text className="page-kicker">腾讯地图镜像</Typography.Text><Typography.Title level={2}>服务 POI</Typography.Title><Typography.Paragraph>同步微信服务 POI 后生成可解释的门店匹配候选。</Typography.Paragraph></div><Space><Select className="workspace-select" placeholder="选择 POI 连接并同步" options={poiConnections.map(item => ({ value: item.id, label: item.id }))} onChange={value => sync.mutate(value)} /><Button type="primary" onClick={() => setCreateOpen(true)}>新建 POI</Button><Button icon={<RefreshCw size={15} />} onClick={() => void pois.refetch()}>刷新</Button></Space></div>
    {sync.isSuccess && <p className="operation-note">同步操作已进入队列。</p>}
    <Card className="workspace-table-card" variant="borderless"><WorkspaceState loading={pois.isPending} error={pois.error ?? sync.error ?? action.error} empty={!rows.length}><Table<PoiRecord> rowKey="id" dataSource={rows} columns={[{ title: 'POI ID', dataIndex: 'external_poi_id' }, { title: '名称', dataIndex: 'name' }, { title: '地址', dataIndex: 'address', ellipsis: true }, { title: '状态', dataIndex: 'remote_status', render: value => <Tag>{value}</Tag> }, { title: '操作', render: (_, row) => <Space><Button type="link" onClick={() => action.mutate({ id: row.id, kind: 'audit' })}>刷新审核</Button><Button type="link" danger disabled={row.remote_status === 'deleted'} onClick={() => Modal.confirm({ title: '删除远端 POI？', content: '删除操作会进入队列，完成前仍会保留本地镜像。', okText: '确认删除', okButtonProps: { danger: true }, cancelText: '取消', onOk: () => action.mutate({ id: row.id, kind: 'delete' }) })}>删除</Button></Space> }]} /></WorkspaceState></Card>
    <Modal title="新建服务 POI" open={createOpen} onCancel={() => setCreateOpen(false)} footer={null} destroyOnHidden>
      <Form form={form} layout="vertical" onFinish={values => create.mutate({ ...values, connection_id: values.connection_id, idempotency_key: 'poi-create:' + Date.now() })}>
        <Form.Item name="connection_id" label="服务 POI 连接" rules={[{ required: true }]}><Select options={poiConnections.map(item => ({ value: item.id, label: item.id }))} /></Form.Item>
        <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="address" label="地址" rules={[{ required: true }]}><Input /></Form.Item>
        <Space.Compact block><Form.Item name="latitude" label="纬度" style={{ width: '50%' }}><Input /></Form.Item><Form.Item name="longitude" label="经度" style={{ width: '50%' }}><Input /></Form.Item></Space.Compact>
        {create.isError && <p className="form-error">{create.error.message}</p>}
        <Button block type="primary" htmlType="submit" loading={create.isPending}>提交 POI 创建</Button>
      </Form>
    </Modal>
  </section>
}
