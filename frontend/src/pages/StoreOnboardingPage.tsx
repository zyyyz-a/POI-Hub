import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, Checkbox, Form, Image, Input, Modal, Select, Space, Tag, Typography } from 'antd'
import { Copy, CreditCard, Plus, QrCode, Store as StoreIcon } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import {
  api,
  type PaymentProfileRecord,
  type PlatformMiniProgramRecord,
  type StoreBindingRecord,
  type StoreRecord,
} from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { WorkspaceState } from './WorkspaceStates'
import './workspace.css'

const money = (value: number) => `¥${(value / 100).toFixed(2)}`

type ConnectionLike = { id: string; capability: string; app_id?: string | null }

export function StoreOnboardingPage() {
  const { tenant } = useAuth()
  const client = useQueryClient()
  const [storeId, setStoreId] = useState<string>('')
  const [profileModal, setProfileModal] = useState(false)
  const [bindingModal, setBindingModal] = useState(false)
  const [activateModal, setActivateModal] = useState(false)
  const [code, setCode] = useState<{ available?: boolean; reason?: string | null; image_base64?: string | null; scene: string; page: string } | null>(null)
  const [profileForm] = Form.useForm()
  const [bindingForm] = Form.useForm()
  const [activateForm] = Form.useForm()

  const stores = useQuery({ queryKey: ['stores', tenant?.id], queryFn: api.stores, enabled: Boolean(tenant) })
  const programs = useQuery({ queryKey: ['platform-mini-programs'], queryFn: api.platformMiniPrograms, enabled: Boolean(tenant) })
  const connections = useQuery({ queryKey: ['connections', tenant?.id], queryFn: api.connections, enabled: Boolean(tenant) })
  const profiles = useQuery({ queryKey: ['payment-profiles', tenant?.id], queryFn: api.paymentProfiles, enabled: Boolean(tenant) })
  const products = useQuery({ queryKey: ['direct-products', tenant?.id], queryFn: api.directProducts, enabled: Boolean(tenant) })
  const bindings = useQuery({ queryKey: ['store-bindings', tenant?.id], queryFn: api.storeBindings, enabled: Boolean(tenant) })

  const refresh = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: ['stores', tenant?.id] }),
      client.invalidateQueries({ queryKey: ['payment-profiles', tenant?.id] }),
      client.invalidateQueries({ queryKey: ['direct-products', tenant?.id] }),
      client.invalidateQueries({ queryKey: ['store-bindings', tenant?.id] }),
    ])
  }

  const store = useMemo(() => (stores.data || []).find(item => item.id === storeId) || null, [stores.data, storeId])
  const selectedProfile = useMemo<PaymentProfileRecord | undefined>(() => (profiles.data || []).find(item => item.store_id === storeId), [profiles.data, storeId])
  const selectedBinding = useMemo<StoreBindingRecord | undefined>(() => (bindings.data || []).find(item => item.store_id === storeId), [bindings.data, storeId])
  const storeProducts = useMemo(() => (products.data || []).filter(item => item.store_id === storeId), [products.data, storeId])
  const program = (programs.data || [])[0]
  const commerceConnections = ((connections.data || []) as ConnectionLike[]).filter(item => item.capability === 'mini_program_commerce')

  useEffect(() => { setCode(null) }, [storeId])

  const saveProfile = useMutation({
    mutationFn: (values: Record<string, unknown>) => selectedProfile
      ? api.updatePaymentProfile(selectedProfile.id, { ...values, version: selectedProfile.version })
      : api.createPaymentProfile({ ...values, store_id: storeId }),
    onSuccess: async () => { setProfileModal(false); profileForm.resetFields(); await refresh() },
  })
  const createBinding = useMutation({
    mutationFn: (values: Record<string, unknown>) => api.createStoreBinding({ ...values, store_id: storeId }),
    onSuccess: async () => { setBindingModal(false); bindingForm.resetFields(); await refresh() },
  })
  const activateBinding = useMutation({
    mutationFn: (values: Record<string, unknown>) => api.updateStoreBinding(selectedBinding!.id, { ...values, status: 'active', version: selectedBinding!.version }),
    onSuccess: async () => { setActivateModal(false); activateForm.resetFields(); await refresh() },
  })
  const toggleDiscoverable = useMutation({
    mutationFn: (row: StoreBindingRecord) => api.updateStoreBinding(row.id, { version: row.version, discoverable: !row.discoverable }),
    onSuccess: refresh,
  })
  const generateCode = useMutation({
    mutationFn: () => api.generateStoreEntryCode(selectedBinding!.id, 'release'),
    onSuccess: data => setCode(data),
  })

  const stepDone = (key: string): boolean => {
    if (!store) return false
    switch (key) {
      case 'profile': return Boolean(store.name && store.address && store.city)
      case 'photos': return Boolean(store.cover_image) || (store.environment_images || []).length > 0
      case 'poi': return Boolean(selectedBinding?.tencent_poi_id)
      case 'payment': return Boolean(selectedProfile && selectedProfile.status === 'active' && selectedProfile.verified)
      case 'products': return storeProducts.length > 0
      case 'entry': return Boolean(selectedBinding)
      case 'audit': return Boolean(selectedBinding?.official_reference && selectedBinding?.evidence_reference)
      case 'activate': return selectedBinding?.status === 'active'
      case 'discoverable': return Boolean(selectedBinding?.discoverable)
      default: return false
    }
  }

  const stepItems = [
    { key: 'profile', title: '基础信息', desc: '门店名称、地址、城市、经纬度、营业时间', action: <Button size="small" onClick={() => window.location.assign('/stores')}>去填写</Button> },
    { key: 'photos', title: '门店照片', desc: '头图、Logo、店内环境图（最多 6 张）', action: <Button size="small" onClick={() => window.location.assign('/stores')}>去填写</Button> },
    { key: 'poi', title: '腾讯地图 POI', desc: '填写腾讯地图 POI 标识', action: <Button size="small" disabled={!selectedBinding} onClick={() => setActivateModal(true)}>填写</Button> },
    { key: 'payment', title: '支付商户号', desc: '普通商户号或服务商子商户号，核验归属', action: <Button size="small" type="primary" icon={<CreditCard size={14} />} onClick={() => { if (selectedProfile) profileForm.setFieldsValue(selectedProfile); setProfileModal(true) }}>{selectedProfile ? '编辑支付档案' : '新建支付档案'}</Button> },
    { key: 'products', title: '服务项目', desc: '至少一个已上架套餐', action: <Button size="small" onClick={() => window.location.assign('/direct-commerce')}>去管理套餐</Button> },
    { key: 'entry', title: '入口编码', desc: '门店专属 store_code，供腾讯地图与小程序码使用', action: <Button size="small" type="primary" icon={<Plus size={14} />} disabled={Boolean(selectedBinding)} onClick={() => setBindingModal(true)}>绑定入口</Button> },
    { key: 'audit', title: '审核材料', desc: '官方审核编号与凭证', action: <Button size="small" disabled={!selectedBinding} onClick={() => setActivateModal(true)}>填写</Button> },
    { key: 'activate', title: '启用门店入口', desc: '依据官方凭证启用', action: <Button size="small" type="primary" disabled={!selectedBinding || selectedBinding.status === 'active'} onClick={() => setActivateModal(true)}>启用</Button> },
    { key: 'discoverable', title: '顾客可见', desc: '在顾客门店列表中展示', action: <Button size="small" disabled={!selectedBinding} onClick={() => selectedBinding && toggleDiscoverable.mutate(selectedBinding)}>{selectedBinding?.discoverable ? '隐藏' : '上架'}</Button> },
  ]

  const completed = stepItems.filter(item => stepDone(item.key)).length

  return <section className="workspace-page">
    <div className="page-heading"><div><Typography.Text className="page-kicker">门店接入向导</Typography.Text><Typography.Title level={2}>按步骤接入一家门店</Typography.Title><Typography.Paragraph>顾客端不能新增门店；门店由商家在后台按向导接入，逐项检查后启用。</Typography.Paragraph></div></div>
    <Alert type="info" showIcon message="只允许平台管理员或对应商户管理员操作；顾客端只能识别已审核接入的门店。" />

    <Card className="workspace-table-card" variant="borderless" title="选择门店">
      <Select style={{ width: 320 }} placeholder="选择要接入的门店" value={storeId || undefined} onChange={setStoreId} options={(stores.data || []).map(item => ({ value: item.id, label: item.name }))} />
      {program && <Space style={{ marginLeft: 16 }}><Tag color={program.status === 'active' ? 'green' : 'default'}>平台小程序 {program.status === 'active' ? '已启用' : '未启用'}</Tag></Space>}
    </Card>

    <WorkspaceState loading={stores.isPending} error={stores.error} empty={!stores.data?.length}>
      {store && <>
        <Card className="workspace-table-card" variant="borderless" title={`${store.name} · 完成 ${completed}/${stepItems.length}`}>
          <Space direction="vertical" size="middle" style={{ width: '100%' }}>
            {stepItems.map(item => <div key={item.key} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, borderBottom: '1px solid #f0f0f0', paddingBottom: 12 }}>
              <div>
                <Space>
                  <Tag color={stepDone(item.key) ? 'green' : 'default'}>{stepDone(item.key) ? '已完成' : '待完成'}</Tag>
                  <strong>{item.title}</strong>
                </Space>
                <div className="muted">{item.desc}</div>
              </div>
              {item.action}
            </div>)}
          </Space>
        </Card>

        <Card className="workspace-table-card" variant="borderless" title="门店码与入口参数">
          {!selectedBinding && <div className="muted">请先绑定入口编码。</div>}
          {selectedBinding && <>
            <Space wrap>
              <Tag>store_code: {selectedBinding.store_code}</Tag>
              {selectedBinding.tencent_poi_id && <Tag>POI: {selectedBinding.tencent_poi_id}</Tag>}
              <Button icon={<QrCode size={14} />} loading={generateCode.isPending} onClick={() => generateCode.mutate()}>生成门店小程序码</Button>
            </Space>
            <div className="muted" style={{ marginTop: 8 }}>
              入口路径：<code>{selectedBinding.entry_path || 'pages/store/index'}?store_code={selectedBinding.store_code}</code>
              <Button type="link" size="small" icon={<Copy size={13} />} onClick={() => void navigator.clipboard?.writeText(`pages/store/index?store_code=${selectedBinding.store_code}`)}>复制</Button>
            </div>
            {code && <>
              {code.available && code.image_base64
                ? <Image width={220} src={`data:image/png;base64,${code.image_base64}`} alt="门店小程序码" />
                : <Alert style={{ marginTop: 12 }} type="warning" showIcon message="暂不能生成真实门店码" description={code.reason || '需要真实的平台小程序连接与凭据。'} />}
              <div className="muted" style={{ marginTop: 8 }}>scene：<code>{code.scene}</code> · 页面：<code>{code.page}</code></div>
            </>}
          </>}
        </Card>
      </>}
    </WorkspaceState>

    <Modal title={selectedProfile ? '编辑支付档案' : '新建支付档案'} open={profileModal} onCancel={() => setProfileModal(false)} footer={null}><Form form={profileForm} layout="vertical" initialValues={{ mode: 'ordinary', verified: false, status: 'draft' }} onFinish={values => saveProfile.mutate(values)}>
      <Form.Item label="门店"><Input value={store?.name} disabled /></Form.Item>
      <Form.Item name="connection_id" label="支付连接" rules={[{ required: true }]}><Select options={commerceConnections.map(item => ({ value: item.id, label: `${item.app_id || '待填 AppID'} · ${item.id}` }))} /></Form.Item>
      <Form.Item name="mode" label="收款模式"><Select options={[{ value: 'ordinary', label: '普通商户直连' }, { value: 'partner', label: '服务商子商户' }]} /></Form.Item>
      <Form.Item name="mchid" label="普通商户号"><Input /></Form.Item>
      <Form.Item name="sp_mchid" label="服务商商户号"><Input /></Form.Item>
      <Form.Item name="sub_mchid" label="子商户号"><Input /></Form.Item>
      <Space><Form.Item name="verified" valuePropName="checked"><Checkbox>商户号归属已核验</Checkbox></Form.Item><Form.Item name="status" label="状态"><Select style={{ width: 160 }} options={[{ value: 'draft', label: '草稿' }, { value: 'active', label: '启用' }, { value: 'disabled', label: '停用' }]} /></Form.Item></Space>
      {saveProfile.isError && <p className="form-error">{saveProfile.error.message}</p>}<Button block type="primary" htmlType="submit" loading={saveProfile.isPending}>保存</Button>
    </Form></Modal>

    <Modal title="绑定门店入口" open={bindingModal} onCancel={() => setBindingModal(false)} footer={null}><Form form={bindingForm} layout="vertical" initialValues={{ entry_path: 'pages/store/index', discoverable: true }} onFinish={values => createBinding.mutate(values)}>
      <Form.Item name="platform_mini_program_id" label="平台小程序" rules={[{ required: true }]}><Select options={(programs.data || []).map((item: PlatformMiniProgramRecord) => ({ value: item.id, label: `${item.name} · ${item.app_id || '待注册'}` }))} /></Form.Item>
      <Form.Item name="store_code" label="公开入口编码 store_code" rules={[{ required: true }]}><Input placeholder="例如 disifengshang" /></Form.Item>
      <Form.Item name="tencent_poi_id" label="腾讯地图 POI 标识"><Input /></Form.Item>
      <Form.Item name="entry_path" label="小程序入口路径"><Input /></Form.Item>
      <Form.Item name="discoverable" valuePropName="checked"><Checkbox>在顾客门店列表中展示</Checkbox></Form.Item>
      {createBinding.isError && <p className="form-error">{createBinding.error.message}</p>}<Button block type="primary" htmlType="submit" loading={createBinding.isPending}>创建草稿</Button>
    </Form></Modal>

    <Modal title="官方凭证与启用" open={activateModal} onCancel={() => setActivateModal(false)} footer={null}>
      <Form form={activateForm} layout="vertical" initialValues={{ tencent_poi_id: selectedBinding?.tencent_poi_id, official_reference: selectedBinding?.official_reference, evidence_reference: selectedBinding?.evidence_reference }} onFinish={values => activateBinding.mutate(values)}>
        <Form.Item name="tencent_poi_id" label="腾讯地图 POI 标识"><Input /></Form.Item>
        <Form.Item name="official_reference" label="官方审核编号"><Input /></Form.Item>
        <Form.Item name="evidence_reference" label="官方审核凭证"><Input /></Form.Item>
        {activateBinding.isError && <p className="form-error">{activateBinding.error.message}</p>}
        <Button block type="primary" htmlType="submit" loading={activateBinding.isPending}>保存并启用</Button>
      </Form>
    </Modal>

    <Card className="workspace-table-card" variant="borderless" title="门店清单">
      <Space wrap>
        {(stores.data || []).map((item: StoreRecord) => <Tag key={item.id} icon={<StoreIcon size={12} />} onClick={() => setStoreId(item.id)} style={{ cursor: 'pointer' }}>{item.name}{item.public_phone ? ` · ${item.public_phone}` : ''}</Tag>)}
      </Space>
      <div className="muted" style={{ marginTop: 8 }}>当前门店套餐数：{storeProducts.length}，示例价格：{storeProducts[0] ? money(storeProducts[0].sale_price) : '-'}</div>
    </Card>
  </section>
}
