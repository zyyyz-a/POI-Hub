import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, Form, Input, InputNumber, Modal, Select, Space, Table, Tag, Typography } from 'antd'
import { RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { api, type PoiRecord, type RemotePoiRecord } from '../api/client'
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
  const [searchKeyword, setSearchKeyword] = useState('')
  const [form] = Form.useForm()
  const submissionStage = Form.useWatch('submission_stage', form) as 'bind_store' | 'create_map' | undefined
  const sync = useMutation({ mutationFn: (connection_id: string) => api.syncPois({ connection_id, idempotency_key: 'poi-sync:' + Date.now() }), onSuccess: async () => { await client.invalidateQueries({ queryKey: ['operations', tenant?.id] }); await client.invalidateQueries({ queryKey: ['pois', tenant?.id] }) } })
  const search = useMutation({ mutationFn: ({ connectionId, keyword }: { connectionId: string; keyword: string }) => api.searchPois(connectionId, keyword) })
  const create = useMutation({ mutationFn: api.createPoi, onSuccess: async () => { setCreateOpen(false); form.resetFields(); await client.invalidateQueries({ queryKey: ['pois', tenant?.id] }) } })
  const action = useMutation({ mutationFn: ({ id, kind }: { id: string; kind: 'delete' | 'audit' }) => kind === 'delete' ? api.deletePoi(id, 'poi-delete:' + id + ':' + Date.now()) : api.refreshPoiAudit(id, 'poi-audit:' + id + ':' + Date.now()), onSuccess: async () => client.invalidateQueries({ queryKey: ['pois', tenant?.id] }) })
  const rows = (pois.data ?? []) as PoiRecord[]
  return <section className="workspace-page">
    <div className="page-heading"><div><Typography.Text className="page-kicker">腾讯地图镜像</Typography.Text><Typography.Title level={2}>服务 POI</Typography.Title><Typography.Paragraph>同步微信服务 POI 后生成可解释的门店匹配候选。</Typography.Paragraph></div><Space><Select className="workspace-select" placeholder="选择 POI 连接并同步" options={poiConnections.map(item => ({ value: item.id, label: item.id }))} onChange={value => sync.mutate(value)} /><Button type="primary" onClick={() => setCreateOpen(true)}>新建 POI</Button><Button icon={<RefreshCw size={15} />} onClick={() => void pois.refetch()}>刷新</Button></Space></div>
    {sync.isSuccess && <p className="operation-note">同步操作已进入队列。</p>}
    <Card className="workspace-table-card" variant="borderless"><WorkspaceState loading={pois.isPending} error={pois.error ?? sync.error ?? action.error} empty={!rows.length}><Table<PoiRecord> rowKey="id" dataSource={rows} columns={[{ title: 'POI ID', dataIndex: 'external_poi_id' }, { title: '名称', dataIndex: 'name' }, { title: '地址', dataIndex: 'address', ellipsis: true }, { title: '状态', dataIndex: 'remote_status', render: value => <Tag>{value}</Tag> }, { title: '操作', render: (_, row) => <Space><Button type="link" onClick={() => action.mutate({ id: row.id, kind: 'audit' })}>刷新审核</Button><Button type="link" danger disabled={row.remote_status === 'deleted'} onClick={() => Modal.confirm({ title: '删除远端 POI？', content: '删除操作会进入队列，完成前仍会保留本地镜像。', okText: '确认删除', okButtonProps: { danger: true }, cancelText: '取消', onOk: () => action.mutate({ id: row.id, kind: 'delete' }) })}>删除</Button></Space> }]} /></WorkspaceState></Card>
    <Modal title="接入微信服务门店" open={createOpen} onCancel={() => setCreateOpen(false)} footer={null} width={720} destroyOnHidden>
      <Form form={form} layout="vertical" initialValues={{ submission_stage: 'bind_store' }} onFinish={values => {
        const payload = { ...values, idempotency_key: 'poi-create:' + Date.now() }
        delete payload.submission_stage
        delete payload.search_keyword
        if (payload.photo) payload.pic_list = [payload.photo]
        create.mutate(payload)
      }}>
        <Form.Item name="connection_id" label="服务 POI 连接" rules={[{ required: true }]}><Select options={poiConnections.map(item => ({ value: item.id, label: item.id }))} /></Form.Item>
        <Form.Item name="submission_stage" label="当前步骤" rules={[{ required: true }]}><Select options={[{ value: 'bind_store', label: '已有腾讯地图点位，提交微信门店审核' }, { value: 'create_map', label: '地图上没有门店，先创建腾讯地图点位' }]} /></Form.Item>
        {submissionStage === 'bind_store' && <>
          <Alert type="info" showIcon message="先搜索腾讯地图点位" description="选中搜索结果后会自动填入腾讯地图 POI ID。微信门店审核通过后，再点页面上方“同步”取得最终微信 POI ID。" />
          <Space.Compact block style={{ marginTop: 16 }}><Form.Item name="search_keyword" noStyle><Input placeholder="输入门店名称或地址" value={searchKeyword} onChange={event => setSearchKeyword(event.target.value)} /></Form.Item><Button loading={search.isPending} onClick={() => { const connectionId = form.getFieldValue('connection_id') as string | undefined; if (connectionId && searchKeyword.trim()) search.mutate({ connectionId, keyword: searchKeyword.trim() }) }}>搜索腾讯地图</Button></Space.Compact>
          {search.isError && <p className="form-error">{search.error.message}</p>}
          {search.data?.length ? <Table<RemotePoiRecord> size="small" rowKey="poi_id" pagination={false} dataSource={search.data} columns={[{ title: '门店', dataIndex: 'name' }, { title: '地址', dataIndex: 'address', ellipsis: true }, { title: '', render: (_, row) => <Button type="link" onClick={() => form.setFieldsValue({ map_poi_id: row.poi_id, name: row.name, address: row.address, latitude: row.latitude, longitude: row.longitude })}>选择</Button> }]} /> : null}
          <Form.Item name="map_poi_id" label="腾讯地图 POI ID" rules={[{ required: true }]}><Input /></Form.Item>
        </>}
        {submissionStage === 'create_map' && <Alert type="warning" showIcon message="这是第一阶段" description="提交后需等待腾讯地图审核。审核完成并可搜索到点位后，回到这里选择“已有腾讯地图点位”，再提交微信门店审核。" />}
        <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="address" label="地址" rules={[{ required: true }]}><Input /></Form.Item>
        <Space.Compact block><Form.Item name="latitude" label="纬度" style={{ width: '50%' }} rules={submissionStage === 'create_map' ? [{ required: true }] : []}><InputNumber min={-90} max={90} precision={6} style={{ width: '100%' }} /></Form.Item><Form.Item name="longitude" label="经度" style={{ width: '50%' }} rules={submissionStage === 'create_map' ? [{ required: true }] : []}><InputNumber min={-180} max={180} precision={6} style={{ width: '100%' }} /></Form.Item></Space.Compact>
        {submissionStage === 'create_map' && <>
          <Space.Compact block><Form.Item name="province" label="省" style={{ width: '33%' }} rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="city" label="市" style={{ width: '33%' }} rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="district" label="区/县" style={{ width: '34%' }} rules={[{ required: true }]}><Input /></Form.Item></Space.Compact>
          <Form.Item name="districtid" label="腾讯地图行政区划 ID" rules={[{ required: true }]}><InputNumber min={1} style={{ width: '100%' }} /></Form.Item>
          <Form.Item name="category" label="腾讯地图类目" rules={[{ required: true }]}><Input placeholder="例如：美食:中餐厅" /></Form.Item>
          <Form.Item name="telephone" label="门店电话" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="license" label="营业执照图片 URL" rules={[{ required: true, type: 'url' }]}><Input /></Form.Item>
          <Form.Item name="description" label="门店简介" rules={[{ required: true }]}><Input.TextArea /></Form.Item>
        </>}
        <Form.Item name="photo" label="门店图片 URL" rules={[{ required: true, type: 'url' }]}><Input /></Form.Item>
        {submissionStage === 'bind_store' && <>
          <Form.Item name="contract_phone" label="审核联系电话" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="hour" label="营业时间" rules={[{ required: true }]}><Input placeholder="例如：09:00-21:00" /></Form.Item>
          <Form.Item name="credential" label="资质材料标识" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="company_name" label="主体名称"><Input /></Form.Item>
          <Form.Item name="card_id" label="证件编号"><Input /></Form.Item>
        </>}
        {create.isError && <p className="form-error">{create.error.message}</p>}
        <Button block type="primary" htmlType="submit" loading={create.isPending}>{submissionStage === 'create_map' ? '提交腾讯地图点位审核' : '提交微信门店审核'}</Button>
      </Form>
    </Modal>
  </section>
}
