import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Card, Form, Modal, Select, Space, Table, Tag, Typography } from 'antd'
import { Check, RefreshCw, X } from 'lucide-react'
import { useState } from 'react'
import { api, type MappingRecord, type PoiRecord, type StoreRecord } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { WorkspaceState } from './WorkspaceStates'
import './workspace.css'

type Candidate = { id: string; store_id: string; service_poi_id: string; total_score: number; name_score: number; address_score: number; distance_meters?: number | null }

export function MappingsPage() {
  const { tenant, membership, user } = useAuth()
  const client = useQueryClient()
  const editable = Boolean(user?.is_platform_admin || ['tenant_admin', 'operator'].includes(membership?.role ?? ''))
  const query = useQuery({ queryKey: ['candidates', tenant?.id], queryFn: api.candidates, enabled: Boolean(tenant) })
  const stores = useQuery({ queryKey: ['stores', tenant?.id], queryFn: api.stores, enabled: Boolean(tenant) })
  const pois = useQuery({ queryKey: ['pois', tenant?.id], queryFn: api.pois, enabled: Boolean(tenant) })
  const mappings = useQuery({ queryKey: ['mappings', tenant?.id], queryFn: api.mappings, enabled: Boolean(tenant) })
  const [manualOpen, setManualOpen] = useState(false)
  const [form] = Form.useForm()
  const mutation = useMutation({
    mutationFn: ({ id, action }: { id: string; action: 'confirm' | 'dismiss' }) => action === 'confirm' ? api.confirmCandidate(id) : api.dismissCandidate(id),
    onSuccess: async () => {
      await Promise.all([client.invalidateQueries({ queryKey: ['candidates', tenant?.id] }), client.invalidateQueries({ queryKey: ['mappings', tenant?.id] })])
    },
  })
  const manual = useMutation({ mutationFn: api.manualMap, onSuccess: async () => { setManualOpen(false); form.resetFields(); await Promise.all([client.invalidateQueries({ queryKey: ['candidates', tenant?.id] }), client.invalidateQueries({ queryKey: ['mappings', tenant?.id] })]) } })
  const unbind = useMutation({ mutationFn: api.unbindMapping, onSuccess: async () => client.invalidateQueries({ queryKey: ['mappings', tenant?.id] }) })
  const candidates = (query.data ?? []) as Candidate[]
  const storeById = new Map((stores.data ?? []).map((item: StoreRecord) => [item.id, item]))
  const poiById = new Map((pois.data ?? []).map((item: PoiRecord) => [item.id, item]))
  return <section className="workspace-page">
    <div className="page-heading"><div><Typography.Text className="page-kicker">门店与 POI</Typography.Text><Typography.Title level={2}>POI 映射</Typography.Title><Typography.Paragraph>候选关系只有经过人工确认后才会用于券码核销。</Typography.Paragraph></div><Space><Button icon={<RefreshCw size={15} />} onClick={() => void query.refetch()}>刷新</Button>{editable && <Button type="primary" onClick={() => setManualOpen(true)}>手动绑定</Button>}</Space></div>
    <Card className="workspace-table-card" variant="borderless"><WorkspaceState loading={query.isPending} error={query.error ?? mutation.error} empty={!candidates.length}>
      <Table<Candidate> rowKey="id" dataSource={candidates} columns={[
        { title: '门店', render: (_, row) => storeById.get(row.store_id)?.name ?? row.store_id, ellipsis: true },
        { title: 'POI', render: (_, row) => poiById.get(row.service_poi_id)?.name ?? row.service_poi_id, ellipsis: true },
        { title: '综合匹配度', dataIndex: 'total_score', render: (value: number) => <Tag color={value >= .8 ? 'green' : 'gold'}>{Math.round(value * 100)}%</Tag> },
        { title: '名称 / 地址', render: (_, row) => String(Math.round(row.name_score * 100)) + '% / ' + String(Math.round(row.address_score * 100)) + '%' },
        { title: '距离', dataIndex: 'distance_meters', render: (value?: number) => value == null ? '-' : String(Math.round(value)) + ' m' },
        { title: '操作', render: (_, row) => editable && <Space><Button type="primary" size="small" icon={<Check size={14} />} loading={mutation.isPending} onClick={() => mutation.mutate({ id: row.id, action: 'confirm' })}>确认</Button><Button size="small" icon={<X size={14} />} onClick={() => mutation.mutate({ id: row.id, action: 'dismiss' })}>忽略</Button></Space> },
      ]} />
    </WorkspaceState></Card>
    <Typography.Title level={3} className="workspace-subtitle">当前活动映射</Typography.Title>
    <Card className="workspace-table-card" variant="borderless"><WorkspaceState loading={mappings.isPending} error={mappings.error ?? unbind.error} empty={!mappings.data?.length}>
      <Table<MappingRecord> rowKey="id" dataSource={mappings.data ?? []} columns={[{ title: '门店 ID', dataIndex: 'store_id', ellipsis: true }, { title: 'POI ID', dataIndex: 'service_poi_id', ellipsis: true }, { title: '来源', render: (_, row) => row.match_score == null ? '人工绑定' : '候选确认' }, { title: '操作', render: (_, row) => editable && <Button danger type="link" loading={unbind.isPending} onClick={() => Modal.confirm({ title: '解除映射？', content: '解除后该门店不能用于当前券码核销。', okText: '确认解除', okButtonProps: { danger: true }, cancelText: '取消', onOk: () => unbind.mutate(row.id) })}>解除</Button> }]} />
    </WorkspaceState></Card>
    <Modal title="手动绑定 POI" open={manualOpen} onCancel={() => setManualOpen(false)} footer={null} destroyOnHidden>
      <Form form={form} layout="vertical" onFinish={values => manual.mutate(values)}>
        <Form.Item name="store_id" label="门店" rules={[{ required: true }]}><Select options={(stores.data ?? []).map((item: StoreRecord) => ({ value: item.id, label: item.name + '（' + item.code + '）' }))} /></Form.Item>
        <Form.Item name="service_poi_id" label="服务 POI" rules={[{ required: true }]}><Select options={(pois.data ?? []).filter((item: PoiRecord) => item.remote_status !== 'deleted').map(item => ({ value: item.id, label: item.name + '（' + item.external_poi_id + '）' }))} /></Form.Item>
        {manual.isError && <p className="form-error">{manual.error.message}</p>}
        <Button block type="primary" htmlType="submit" loading={manual.isPending}>确认绑定</Button>
      </Form>
    </Modal>
  </section>
}
