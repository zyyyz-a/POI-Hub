import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, Form, Input, InputNumber, Modal, Select, Space, Table, Tabs, Tag, Typography } from 'antd'
import { Plus, RefreshCw, ScanLine } from 'lucide-react'
import { useMemo, useState } from 'react'
import {
  api,
  type DirectAppointmentRecord,
  type DirectOrderRecord,
  type DirectProductRecord,
  type DirectVoucherRecord,
} from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { WorkspaceState } from './WorkspaceStates'
import './workspace.css'

const money = (value: number) => `¥${(value / 100).toFixed(2)}`
const time = (value?: string | null) => value ? new Date(value).toLocaleString('zh-CN') : '-'

export function DirectCommercePage() {
  const { tenant } = useAuth()
  const client = useQueryClient()
  const [productModal, setProductModal] = useState(false)
  const [consumeModal, setConsumeModal] = useState(false)
  const [form] = Form.useForm()
  const [consumeForm] = Form.useForm()
  const products = useQuery({ queryKey: ['direct-products', tenant?.id], queryFn: api.directProducts, enabled: Boolean(tenant) })
  const orders = useQuery({ queryKey: ['direct-orders', tenant?.id], queryFn: api.directOrders, enabled: Boolean(tenant) })
  const appointments = useQuery({ queryKey: ['direct-appointments', tenant?.id], queryFn: api.directAppointments, enabled: Boolean(tenant) })
  const vouchers = useQuery({ queryKey: ['direct-vouchers', tenant?.id], queryFn: api.directVouchers, enabled: Boolean(tenant) })
  const stores = useQuery({ queryKey: ['stores', tenant?.id], queryFn: api.stores, enabled: Boolean(tenant) })
  const apps = useQuery({ queryKey: ['mini-programs', tenant?.id], queryFn: api.miniPrograms, enabled: Boolean(tenant) })

  const refresh = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: ['direct-products', tenant?.id] }),
      client.invalidateQueries({ queryKey: ['direct-orders', tenant?.id] }),
      client.invalidateQueries({ queryKey: ['direct-appointments', tenant?.id] }),
      client.invalidateQueries({ queryKey: ['direct-vouchers', tenant?.id] }),
    ])
  }
  const createProduct = useMutation({
    mutationFn: (values: Record<string, unknown>) => api.createDirectProduct({ ...values, sale_price: Number(values.sale_price_yuan) * 100, market_price: Number(values.market_price_yuan) * 100 }),
    onSuccess: async () => { setProductModal(false); form.resetFields(); await refresh() },
  })
  const productAction = useMutation({
    mutationFn: ({ row, status }: { row: DirectProductRecord; status: string }) => api.updateDirectProduct(row.id, { version: row.version, status }),
    onSuccess: refresh,
  })
  const consume = useMutation({
    mutationFn: (values: { code: string; store_id: string }) => api.consumeDirectVoucher(values),
    onSuccess: async () => { setConsumeModal(false); consumeForm.resetFields(); await refresh() },
  })
  const revoke = useMutation({
    mutationFn: (row: DirectVoucherRecord) => api.revokeDirectVoucher(row.id, { version: row.version, reason: '后台确认撤销误核销' }),
    onSuccess: refresh,
  })
  const storeNames = useMemo(() => new Map((stores.data || []).map(item => [item.id, item.name])), [stores.data])

  const productColumns = [
    { title: '商品', render: (_: unknown, row: DirectProductRecord) => <div><strong>{row.name}</strong><br /><Typography.Text type="secondary">{row.merchant_product_id}</Typography.Text></div> },
    { title: '门店', dataIndex: 'store_id', render: (value: string) => storeNames.get(value) || value },
    { title: '价格', render: (_: unknown, row: DirectProductRecord) => <span>{money(row.sale_price)} <Typography.Text delete type="secondary">{money(row.market_price)}</Typography.Text></span> },
    { title: '库存/已售', render: (_: unknown, row: DirectProductRecord) => `${row.stock} / ${row.sold_count}` },
    { title: '状态', dataIndex: 'status', render: (value: string) => <Tag color={value === 'listed' ? 'green' : 'default'}>{value === 'listed' ? '已上架' : value === 'delisted' ? '已下架' : '草稿'}</Tag> },
    { title: '操作', render: (_: unknown, row: DirectProductRecord) => <Button size="small" onClick={() => productAction.mutate({ row, status: row.status === 'listed' ? 'delisted' : 'listed' })}>{row.status === 'listed' ? '下架' : '上架'}</Button> },
  ]
  const orderColumns = [
    { title: '订单号', dataIndex: 'order_no' },
    { title: '商品', dataIndex: 'product_name' },
    { title: '数量', dataIndex: 'quantity' },
    { title: '实付', dataIndex: 'paid_amount', render: (value: number) => money(value) },
    { title: '状态', dataIndex: 'status', render: (value: string) => <Tag color={value === 'paid' ? 'green' : 'orange'}>{value}</Tag> },
    { title: '下单时间', dataIndex: 'created_at', render: time },
  ]
  const appointmentColumns = [
    { title: '预约时间', dataIndex: 'starts_at', render: time },
    { title: '顾客', render: (_: unknown, row: DirectAppointmentRecord) => `${row.contact_name} ${row.contact_phone_masked}` },
    { title: '门店', dataIndex: 'store_id', render: (value: string) => storeNames.get(value) || value },
    { title: '备注', dataIndex: 'note', render: (value?: string) => value || '-' },
    { title: '状态', dataIndex: 'status' },
  ]
  const voucherColumns = [
    { title: '券码', dataIndex: 'code_masked' },
    { title: '状态', dataIndex: 'state', render: (value: string) => <Tag color={value === 'available' ? 'green' : 'blue'}>{value === 'available' ? '可使用' : '已核销'}</Tag> },
    { title: '核销门店', dataIndex: 'consume_store_id', render: (value?: string) => value ? storeNames.get(value) || value : '-' },
    { title: '有效期', dataIndex: 'valid_until', render: time },
    { title: '操作', render: (_: unknown, row: DirectVoucherRecord) => row.state === 'consumed' ? <Button size="small" danger onClick={() => Modal.confirm({ title: '确认撤销本次核销？', onOk: () => revoke.mutateAsync(row) })}>撤销误核销</Button> : '-' },
  ]

  return <section className="workspace-page">
    <div className="page-heading"><div><Typography.Text className="page-kicker">商家独立小程序</Typography.Text><Typography.Title level={2}>商品、订单、预约与核销</Typography.Title><Typography.Paragraph>顾客付款直接进入已绑定的商家微信支付商户号。</Typography.Paragraph></div><Space><Button icon={<RefreshCw size={15} />} onClick={() => void refresh()}>刷新</Button><Button icon={<ScanLine size={15} />} onClick={() => setConsumeModal(true)}>核销券码</Button><Button type="primary" icon={<Plus size={15} />} onClick={() => setProductModal(true)}>新增商品</Button></Space></div>
    <Alert type="info" showIcon message="只有准入、官方报备、位置挂载、小程序和商户支付门禁全部通过，商品才允许上架。" />
    <Tabs items={[
      { key: 'products', label: '小程序商品', children: <Card className="workspace-table-card" variant="borderless"><WorkspaceState loading={products.isPending} error={products.error} empty={!products.data?.length}><Table<DirectProductRecord> rowKey="id" dataSource={products.data || []} columns={productColumns} /></WorkspaceState></Card> },
      { key: 'orders', label: '顾客订单', children: <Card className="workspace-table-card" variant="borderless"><WorkspaceState loading={orders.isPending} error={orders.error} empty={!orders.data?.length}><Table<DirectOrderRecord> rowKey="id" dataSource={orders.data || []} columns={orderColumns} /></WorkspaceState></Card> },
      { key: 'appointments', label: '预约排期', children: <Card className="workspace-table-card" variant="borderless"><WorkspaceState loading={appointments.isPending} error={appointments.error} empty={!appointments.data?.length}><Table<DirectAppointmentRecord> rowKey="id" dataSource={appointments.data || []} columns={appointmentColumns} /></WorkspaceState></Card> },
      { key: 'vouchers', label: '券码核销', children: <Card className="workspace-table-card" variant="borderless"><WorkspaceState loading={vouchers.isPending} error={vouchers.error} empty={!vouchers.data?.length}><Table<DirectVoucherRecord> rowKey="id" dataSource={vouchers.data || []} columns={voucherColumns} /></WorkspaceState></Card> },
    ]} />
    <Modal title="新增小程序商品" open={productModal} onCancel={() => setProductModal(false)} footer={null}><Form form={form} layout="vertical" initialValues={{ sale_price_yuan: 99, market_price_yuan: 129, stock: 10, appointment_required: true, service_minutes: 60 }} onFinish={values => createProduct.mutate(values)}>
      <Form.Item name="mini_program_id" label="商家小程序" rules={[{ required: true }]}><Select options={(apps.data || []).map(item => ({ value: item.id, label: `${item.name} · ${item.app_id || '待注册'}` }))} /></Form.Item>
      <Form.Item name="store_id" label="服务门店" rules={[{ required: true }]}><Select options={(stores.data || []).map(item => ({ value: item.id, label: item.name }))} /></Form.Item>
      <Form.Item name="merchant_product_id" label="商家商品编号" rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="name" label="商品名称" rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="description" label="使用说明"><Input.TextArea /></Form.Item><Form.Item name="cover_image" label="封面图片 HTTPS 地址"><Input /></Form.Item>
      <Space align="start"><Form.Item name="sale_price_yuan" label="销售价（元）" rules={[{ required: true }]}><InputNumber min={0.01} precision={2} /></Form.Item><Form.Item name="market_price_yuan" label="划线价（元）" rules={[{ required: true }]}><InputNumber min={0.01} precision={2} /></Form.Item><Form.Item name="stock" label="库存" rules={[{ required: true }]}><InputNumber min={0} precision={0} /></Form.Item></Space>
      <Form.Item name="service_minutes" label="预计服务时长（分钟）"><InputNumber min={5} /></Form.Item>
      {createProduct.isError && <p className="form-error">{createProduct.error.message}</p>}<Button block type="primary" htmlType="submit" loading={createProduct.isPending}>保存草稿</Button>
    </Form></Modal>
    <Modal title="核销顾客券码" open={consumeModal} onCancel={() => setConsumeModal(false)} footer={null}><Form form={consumeForm} layout="vertical" onFinish={values => consume.mutate(values)}><Form.Item name="store_id" label="实际核销门店" rules={[{ required: true }]}><Select options={(stores.data || []).map(item => ({ value: item.id, label: item.name }))} /></Form.Item><Form.Item name="code" label="顾客完整券码" rules={[{ required: true }]}><Input autoComplete="off" /></Form.Item>{consume.isError && <p className="form-error">{consume.error.message}</p>}<Button block type="primary" htmlType="submit" loading={consume.isPending}>确认核销</Button></Form></Modal>
  </section>
}
