import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, Checkbox, Form, Input, Modal, Select, Space, Table, Tabs, Tag, Typography } from 'antd'
import { CreditCard, Plus, RefreshCw, RotateCcw, Smartphone, Store as StoreIcon } from 'lucide-react'
import { useMemo, useState } from 'react'
import {
  api,
  type PaymentProfileRecord,
  type PlatformMiniProgramRecord,
  type RefundRecord,
  type StoreBindingRecord,
} from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { WorkspaceState } from './WorkspaceStates'
import './workspace.css'

const money = (value: number) => `¥${(value / 100).toFixed(2)}`
const time = (value?: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '-'

const statusColor: Record<string, string> = {
  active: 'green', success: 'green', draft: 'default', suspended: 'red', disabled: 'red',
  failed: 'red', closed: 'default', pending: 'orange', processing: 'blue', partial: 'blue',
}
const statusLabel: Record<string, string> = {
  active: '已启用', draft: '草稿', suspended: '已停用', disabled: '已停用',
  pending: '待处理', processing: '退款处理中', success: '退款成功', failed: '退款失败', closed: '已关闭',
}
const StatusTag = ({ value }: { value: string }) => <Tag color={statusColor[value] || 'default'}>{statusLabel[value] || value}</Tag>

type ConnectionLike = { id: string; capability: string; app_id?: string | null }

export function PlatformMiniappPage() {
  const { tenant, user } = useAuth()
  const client = useQueryClient()
  const [programModal, setProgramModal] = useState<{ row?: PlatformMiniProgramRecord } | null>(null)
  const [bindingModal, setBindingModal] = useState(false)
  const [activateBinding, setActivateBinding] = useState<StoreBindingRecord | null>(null)
  const [profileModal, setProfileModal] = useState<{ row?: PaymentProfileRecord } | null>(null)
  const [programForm] = Form.useForm()
  const [bindingForm] = Form.useForm()
  const [activateForm] = Form.useForm()
  const [profileForm] = Form.useForm()

  const isPlatformAdmin = Boolean(user?.is_platform_admin)
  const programs = useQuery({ queryKey: ['platform-mini-programs'], queryFn: api.platformMiniPrograms, enabled: isPlatformAdmin })
  const bindings = useQuery({ queryKey: ['store-bindings', tenant?.id], queryFn: api.storeBindings, enabled: Boolean(tenant) })
  const profiles = useQuery({ queryKey: ['payment-profiles', tenant?.id], queryFn: api.paymentProfiles, enabled: Boolean(tenant) })
  const refunds = useQuery({ queryKey: ['direct-refunds', tenant?.id], queryFn: api.directRefunds, enabled: Boolean(tenant) })
  const stores = useQuery({ queryKey: ['stores', tenant?.id], queryFn: api.stores, enabled: Boolean(tenant) })
  const connections = useQuery({ queryKey: ['connections', tenant?.id], queryFn: api.connections, enabled: Boolean(tenant) })

  const refresh = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: ['platform-mini-programs'] }),
      client.invalidateQueries({ queryKey: ['store-bindings', tenant?.id] }),
      client.invalidateQueries({ queryKey: ['payment-profiles', tenant?.id] }),
      client.invalidateQueries({ queryKey: ['direct-refunds', tenant?.id] }),
    ])
  }

  const saveProgram = useMutation({
    mutationFn: (values: Record<string, unknown>) => programModal?.row
      ? api.updatePlatformMiniProgram(programModal.row.id, { ...values, version: programModal.row.version })
      : api.createPlatformMiniProgram(values),
    onSuccess: async () => { setProgramModal(null); programForm.resetFields(); await refresh() },
  })
  const activateProgram = useMutation({
    mutationFn: (row: PlatformMiniProgramRecord) => api.updatePlatformMiniProgram(row.id, { version: row.version, status: 'active' }),
    onSuccess: refresh,
  })
  const createBinding = useMutation({
    mutationFn: (values: Record<string, unknown>) => api.createStoreBinding(values),
    onSuccess: async () => { setBindingModal(false); bindingForm.resetFields(); await refresh() },
  })
  const saveBindingActivation = useMutation({
    mutationFn: (values: Record<string, unknown>) => api.updateStoreBinding(activateBinding!.id, { ...values, status: 'active', version: activateBinding!.version }),
    onSuccess: async () => { setActivateBinding(null); activateForm.resetFields(); await refresh() },
  })
  const saveProfile = useMutation({
    mutationFn: (values: Record<string, unknown>) => profileModal?.row
      ? api.updatePaymentProfile(profileModal.row.id, { ...values, version: profileModal.row.version })
      : api.createPaymentProfile(values),
    onSuccess: async () => { setProfileModal(null); profileForm.resetFields(); await refresh() },
  })

  const storeNames = useMemo(() => new Map((stores.data || []).map(item => [item.id, item.name])), [stores.data])
  const programNames = useMemo(() => new Map((programs.data || []).map(item => [item.id, item.name])), [programs.data])
  const commerceConnections = ((connections.data || []) as ConnectionLike[]).filter(item => item.capability === 'mini_program_commerce')

  const programColumns = [
    { title: '名称/AppID', render: (_: unknown, row: PlatformMiniProgramRecord) => <div><strong>{row.name}</strong><br /><Typography.Text type="secondary">{row.app_id || '待注册'}</Typography.Text></div> },
    { title: '主体', dataIndex: 'owner_subject' },
    { title: '状态', dataIndex: 'status', render: (value: string) => <StatusTag value={value} /> },
    { title: '回调', dataIndex: 'callback_configured', render: (value: boolean) => value ? <Tag color="green">已配置</Tag> : <Tag>未配置</Tag> },
    { title: '操作', render: (_: unknown, row: PlatformMiniProgramRecord) => <Space>
      <Button size="small" onClick={() => { setProgramModal({ row }); programForm.setFieldsValue(row) }}>配置</Button>
      {row.status !== 'active' && <Button size="small" type="primary" onClick={() => activateProgram.mutate(row)}>启用</Button>}
    </Space> },
  ]

  const bindingColumns = [
    { title: '入口编码', dataIndex: 'store_code' },
    { title: '门店', dataIndex: 'store_id', render: (value: string) => storeNames.get(value) || value },
    { title: '平台小程序', dataIndex: 'platform_mini_program_id', render: (value: string) => programNames.get(value) || value },
    { title: '腾讯 POI', dataIndex: 'tencent_poi_id', render: (value?: string) => value || '-' },
    { title: '状态', dataIndex: 'status', render: (value: string) => <StatusTag value={value} /> },
    { title: '命中路径', render: (_: unknown, row: StoreBindingRecord) => row.entry_path || `pages/store/index?store_code=${row.store_code}` },
    { title: '操作', render: (_: unknown, row: StoreBindingRecord) => row.status === 'active' ? <Tag color="green">已启用</Tag> : <Button size="small" type="primary" onClick={() => { setActivateBinding(row); activateForm.setFieldsValue({ tencent_poi_id: row.tencent_poi_id }) }}>依据官方凭证启用</Button> },
  ]

  const profileColumns = [
    { title: '门店', dataIndex: 'store_id', render: (value: string) => storeNames.get(value) || value },
    { title: '模式', dataIndex: 'mode', render: (value: string) => value === 'partner' ? '服务商子商户' : '普通商户直连' },
    { title: '商户号', render: (_: unknown, row: PaymentProfileRecord) => <div>{row.mchid || '-'}<br /><Typography.Text type="secondary">{row.sub_mchid ? `子商户 ${row.sub_mchid}` : ''}</Typography.Text></div> },
    { title: '归属核验', dataIndex: 'verified', render: (value: boolean) => value ? <Tag color="green">已核验</Tag> : <Tag color="red">未核验</Tag> },
    { title: '状态', dataIndex: 'status', render: (value: string) => <StatusTag value={value} /> },
    { title: '操作', render: (_: unknown, row: PaymentProfileRecord) => <Button size="small" onClick={() => { setProfileModal({ row }); profileForm.setFieldsValue(row) }}>配置</Button> },
  ]

  const refundColumns = [
    { title: '退款单号', dataIndex: 'refund_no' },
    { title: '订单', dataIndex: 'order_id', render: (value: string) => value.slice(0, 8) },
    { title: '门店', dataIndex: 'store_id', render: (value: string) => storeNames.get(value) || value },
    { title: '金额', dataIndex: 'amount', render: (value: number) => money(value) },
    { title: '原因', dataIndex: 'reason', render: (value?: string) => value || '-' },
    { title: '状态', dataIndex: 'status', render: (value: string) => <StatusTag value={value} /> },
    { title: '时间', dataIndex: 'created_at', render: time },
  ]

  return <section className="workspace-page">
    <div className="page-heading"><div><Typography.Text className="page-kicker">统一平台小程序</Typography.Text><Typography.Title level={2}>平台小程序门店接入</Typography.Title><Typography.Paragraph>一个平台 AppID 服务多家门店；入口编码由服务端解析，收款方由门店支付档案决定。</Typography.Paragraph></div><Button icon={<RefreshCw size={15} />} onClick={() => void refresh()}>刷新</Button></div>
    <Alert type="info" showIcon message="资金边界" description="消费者货款按门店支付档案进入对应商户账户；平台前端不能选择或传递商户号。" />
    <Tabs items={[
      ...(isPlatformAdmin ? [{
        key: 'programs', label: <span><Smartphone size={15} /> 平台小程序</span>,
        children: <Card className="workspace-table-card" variant="borderless" title="唯一平台 AppID" extra={<Button type="primary" icon={<Plus size={15} />} onClick={() => setProgramModal({})}>登记平台小程序</Button>}>
          <WorkspaceState loading={programs.isPending} error={programs.error} empty={!programs.data?.length}><Table rowKey="id" dataSource={programs.data || []} columns={programColumns} /></WorkspaceState>
        </Card>,
      }] : []),
      {
        key: 'bindings', label: <span><StoreIcon size={15} /> 门店入口</span>,
        children: <Card className="workspace-table-card" variant="borderless" title="store_code 与腾讯地图入口" extra={<Button type="primary" icon={<Plus size={15} />} onClick={() => setBindingModal(true)}>绑定门店入口</Button>}>
          <WorkspaceState loading={bindings.isPending} error={bindings.error} empty={!bindings.data?.length}><Table rowKey="id" dataSource={bindings.data || []} columns={bindingColumns} scroll={{ x: 1000 }} /></WorkspaceState>
        </Card>,
      },
      {
        key: 'profiles', label: <span><CreditCard size={15} /> 支付档案</span>,
        children: <Card className="workspace-table-card" variant="borderless" title="逐门店收款账户" extra={<Button type="primary" icon={<Plus size={15} />} onClick={() => setProfileModal({})}>新增支付档案</Button>}>
          <WorkspaceState loading={profiles.isPending} error={profiles.error} empty={!profiles.data?.length}><Table rowKey="id" dataSource={profiles.data || []} columns={profileColumns} /></WorkspaceState>
        </Card>,
      },
      {
        key: 'refunds', label: <span><RotateCcw size={15} /> 退款记录</span>,
        children: <Card className="workspace-table-card" variant="borderless" title="门店退款单">
          <WorkspaceState loading={refunds.isPending} error={refunds.error} empty={!refunds.data?.length}><Table<RefundRecord> rowKey="id" dataSource={refunds.data || []} columns={refundColumns} /></WorkspaceState>
        </Card>,
      },
    ]} />

    <Modal title={programModal?.row ? '配置平台小程序' : '登记平台小程序'} open={Boolean(programModal)} onCancel={() => { setProgramModal(null); programForm.resetFields() }} footer={null}><Form form={programForm} layout="vertical" initialValues={{ callback_configured: false }} onFinish={values => saveProgram.mutate(values)}>
      <Form.Item name="name" label="平台小程序名称" rules={[{ required: true }]}><Input /></Form.Item>
      <Form.Item name="app_id" label="平台 AppID" rules={[{ required: true }]}><Input /></Form.Item>
      <Form.Item name="owner_subject" label="所有主体" rules={[{ required: true }]}><Input disabled={Boolean(programModal?.row)} /></Form.Item>
      <Form.Item name="connection_id" label="平台交易连接" rules={[{ required: true }]}><Select options={commerceConnections.map(item => ({ value: item.id, label: `${item.app_id || '待填 AppID'} · ${item.id}` }))} /></Form.Item>
      <Form.Item name="callback_configured" valuePropName="checked"><Checkbox>支付回调已配置</Checkbox></Form.Item>
      {programModal?.row && <Form.Item name="status" label="状态"><Select options={['draft', 'active', 'suspended'].map(value => ({ value, label: statusLabel[value] || value }))} /></Form.Item>}
      {saveProgram.isError && <p className="form-error">{saveProgram.error.message}</p>}<Button block type="primary" htmlType="submit" loading={saveProgram.isPending}>保存</Button>
    </Form></Modal>

    <Modal title="绑定门店入口" open={bindingModal} onCancel={() => setBindingModal(false)} footer={null}><Form form={bindingForm} layout="vertical" initialValues={{ entry_path: 'pages/store/index' }} onFinish={values => createBinding.mutate(values)}>
      <Form.Item name="platform_mini_program_id" label="平台小程序" rules={[{ required: true }]}><Select options={(programs.data || []).map(item => ({ value: item.id, label: `${item.name} · ${item.app_id || '待注册'}` }))} /></Form.Item>
      <Form.Item name="store_id" label="门店" rules={[{ required: true }]}><Select options={(stores.data || []).map(item => ({ value: item.id, label: item.name }))} /></Form.Item>
      <Form.Item name="store_code" label="公开入口编码 store_code" rules={[{ required: true }]}><Input placeholder="字母、数字、下划线或短横线" /></Form.Item>
      <Form.Item name="tencent_poi_id" label="腾讯地图 POI 标识"><Input /></Form.Item>
      <Form.Item name="entry_path" label="小程序入口路径"><Input /></Form.Item>
      <Form.Item name="entry_scene" label="入口 scene"><Input /></Form.Item>
      {createBinding.isError && <p className="form-error">{createBinding.error.message}</p>}<Button block type="primary" htmlType="submit" loading={createBinding.isPending}>创建草稿</Button>
    </Form></Modal>

    <Modal title="依据官方凭证启用门店入口" open={Boolean(activateBinding)} onCancel={() => { setActivateBinding(null); activateForm.resetFields() }} footer={null}><Form form={activateForm} layout="vertical" onFinish={values => saveBindingActivation.mutate(values)}>
      <Form.Item name="tencent_poi_id" label="腾讯地图 POI 标识" rules={[{ required: true }]}><Input /></Form.Item>
      <Form.Item name="official_reference" label="官方审核编号" rules={[{ required: true }]}><Input /></Form.Item>
      <Form.Item name="evidence_reference" label="官方审核凭证" rules={[{ required: true }]}><Input /></Form.Item>
      {saveBindingActivation.isError && <p className="form-error">{saveBindingActivation.error.message}</p>}<Button block type="primary" htmlType="submit" loading={saveBindingActivation.isPending}>确认启用</Button>
    </Form></Modal>

    <Modal title={profileModal?.row ? '配置支付档案' : '新增支付档案'} open={Boolean(profileModal)} onCancel={() => { setProfileModal(null); profileForm.resetFields() }} footer={null}><Form form={profileForm} layout="vertical" initialValues={{ mode: 'ordinary', verified: false, status: 'draft' }} onFinish={values => saveProfile.mutate(values)}>
      <Form.Item name="store_id" label="门店" rules={[{ required: true }]}><Select disabled={Boolean(profileModal?.row)} options={(stores.data || []).map(item => ({ value: item.id, label: item.name }))} /></Form.Item>
      <Form.Item name="connection_id" label="支付连接" rules={[{ required: true }]}><Select options={commerceConnections.map(item => ({ value: item.id, label: `${item.app_id || '待填 AppID'} · ${item.id}` }))} /></Form.Item>
      <Form.Item name="mode" label="收款模式"><Select options={[{ value: 'ordinary', label: '普通商户直连' }, { value: 'partner', label: '服务商子商户' }]} /></Form.Item>
      <Form.Item name="mchid" label="普通商户号"><Input /></Form.Item>
      <Form.Item name="sp_mchid" label="服务商商户号"><Input /></Form.Item>
      <Form.Item name="sub_mchid" label="子商户号"><Input /></Form.Item>
      <Space><Form.Item name="verified" valuePropName="checked"><Checkbox>商户号归属已核验</Checkbox></Form.Item><Form.Item name="status" label="状态"><Select style={{ width: 160 }} options={['draft', 'active', 'disabled'].map(value => ({ value, label: statusLabel[value] || value }))} /></Form.Item></Space>
      {saveProfile.isError && <p className="form-error">{saveProfile.error.message}</p>}<Button block type="primary" htmlType="submit" loading={saveProfile.isPending}>保存</Button>
    </Form></Modal>
  </section>
}
