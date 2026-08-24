import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Card, Form, Input, Modal, Select, Space, Table, Tag, Typography } from 'antd'
import { RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { api, type AfterSaleRecord, type OrderRecord } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { WorkspaceState } from './WorkspaceStates'
import './workspace.css'

export function OrdersPage() {
  const { tenant } = useAuth()
  const client = useQueryClient()
  const [voucher, setVoucher] = useState<{ id: string; state: string } | null>(null)
  const [syncOpen, setSyncOpen] = useState(false)
  const [afterSaleOpen, setAfterSaleOpen] = useState(false)
  const [form] = Form.useForm()
  const [afterSaleForm] = Form.useForm()
  const query = useQuery({ queryKey: ['orders', tenant?.id], queryFn: api.orders, enabled: Boolean(tenant) })
  const vouchers = useQuery({ queryKey: ['vouchers', tenant?.id], queryFn: api.vouchers, enabled: Boolean(tenant) })
  const afterSales = useQuery({ queryKey: ['after-sales', tenant?.id], queryFn: api.afterSales, enabled: Boolean(tenant) })
  const stores = useQuery({ queryKey: ['stores', tenant?.id], queryFn: api.stores, enabled: Boolean(tenant) })
  const connections = useQuery({ queryKey: ['connections', tenant?.id], queryFn: api.connections, enabled: Boolean(tenant) })
  const storeRows = Array.isArray(stores.data) ? stores.data : []
  const connectionRows = Array.isArray(connections.data) ? connections.data : []
  const mutateVoucher = useMutation({ mutationFn: ({ voucherId, state, storeId }: { voucherId: string; state: string; storeId?: string }) => state === 'available' ? api.consumeVoucher(voucherId, { store_id: storeId!, idempotency_key: 'consume:' + voucherId + ':' + Date.now() }) : api.revokeVoucher(voucherId, { store_id: storeId, idempotency_key: 'revoke:' + voucherId + ':' + Date.now() }), onSuccess: async () => { setVoucher(null); await client.invalidateQueries({ queryKey: ['vouchers', tenant?.id] }) } })
  const sync = useMutation({ mutationFn: api.syncOrder, onSuccess: async () => { setSyncOpen(false); form.resetFields(); await client.invalidateQueries({ queryKey: ['orders', tenant?.id] }) } })
  const syncAfterSale = useMutation({ mutationFn: api.syncAfterSale, onSuccess: async () => { setAfterSaleOpen(false); afterSaleForm.resetFields(); await client.invalidateQueries({ queryKey: ['after-sales', tenant?.id] }) } })
  const orders = query.data ?? []
  return <section className="workspace-page">
    <div className="page-heading"><div><Typography.Text className="page-kicker">本地生活交易</Typography.Text><Typography.Title level={2}>订单与券码</Typography.Title><Typography.Paragraph>查询订单、核销凭证和售后进度。</Typography.Paragraph></div><Space><Button onClick={() => setSyncOpen(true)}>同步订单</Button><Button onClick={() => setAfterSaleOpen(true)}>同步售后</Button><Button icon={<RefreshCw size={15} />} onClick={() => void query.refetch()}>刷新</Button></Space></div>
    <Card className="workspace-table-card" variant="borderless"><WorkspaceState loading={query.isPending} error={query.error} empty={!orders.length}>
      <Table<OrderRecord> rowKey="id" dataSource={orders} pagination={{ pageSize: 10 }} columns={[
        { title: '订单号', dataIndex: 'external_order_id', key: 'external_order_id' },
        { title: '状态', dataIndex: 'status', key: 'status', render: (value: string) => <Tag color={value === 'paid' ? 'green' : 'blue'}>{value}</Tag> },
        { title: '订单金额', dataIndex: 'total_amount', key: 'total_amount', render: (value?: number) => typeof value === 'number' ? '¥' + (value / 100).toFixed(2) : '-' },
        { title: '操作', key: 'actions', render: () => <Button type="link">查看券码</Button> },
      ]} />
    </WorkspaceState></Card>
    <Typography.Title level={3} className="workspace-subtitle">券码</Typography.Title>
    <Card className="workspace-table-card" variant="borderless"><WorkspaceState loading={vouchers.isPending} error={vouchers.error} empty={!vouchers.data?.length}><Table rowKey="id" dataSource={vouchers.data ?? []} columns={[{ title: '券码', dataIndex: 'code_masked' }, { title: '状态', dataIndex: 'state', render: value => <Tag>{value}</Tag> }, { title: '核销门店', dataIndex: 'consume_store_id', render: value => value || '-' }, { title: '操作', render: (_, row) => <Button type={row.state === 'available' ? 'primary' : 'default'} onClick={() => setVoucher(row)} disabled={!['available', 'consumed'].includes(row.state)}>{row.state === 'available' ? '核销' : '撤销核销'}</Button> }]} /></WorkspaceState></Card>
    <Modal title={voucher?.state === 'available' ? '确认核销券码' : '确认撤销核销'} open={Boolean(voucher)} onCancel={() => setVoucher(null)} footer={null}>
      <Form layout="vertical" onFinish={values => voucher && mutateVoucher.mutate({ voucherId: voucher.id, state: voucher.state, storeId: values.store_id })}>
        <Form.Item name="store_id" label="核销门店" rules={voucher?.state === 'available' ? [{ required: true }] : []}><Select allowClear options={storeRows.map(item => ({ value: item.id, label: item.name }))} /></Form.Item>
        <Button block type="primary" danger={voucher?.state === 'consumed'} htmlType="submit" loading={mutateVoucher.isPending}>{voucher?.state === 'available' ? '确认核销' : '确认撤销'}</Button>
      </Form>
    </Modal>
    <Modal title="同步订单" open={syncOpen} onCancel={() => setSyncOpen(false)} footer={null}><Form form={form} layout="vertical" onFinish={values => sync.mutate({ ...values, idempotency_key: 'order-sync:' + values.external_order_id + ':' + Date.now() })}><Form.Item name="connection_id" label="本地生活连接" rules={[{ required: true }]}><Select options={connectionRows.filter(item => (item as { capability?: string }).capability === 'local_life').map(item => ({ value: (item as { id: string }).id, label: (item as { id: string }).id }))} /></Form.Item><Form.Item name="external_order_id" label="微信订单号" rules={[{ required: true }]}><Input /></Form.Item><Button block type="primary" htmlType="submit" loading={sync.isPending}>提交同步</Button></Form></Modal>
    <Typography.Title level={3} className="workspace-subtitle">售后</Typography.Title>
    <Card className="workspace-table-card" variant="borderless"><WorkspaceState loading={afterSales.isPending} error={afterSales.error ?? syncAfterSale.error} empty={!afterSales.data?.length}><Table<AfterSaleRecord> rowKey="id" dataSource={afterSales.data ?? []} columns={[{ title: '售后单号', dataIndex: 'external_after_sale_id' }, { title: '订单 ID', dataIndex: 'order_id' }, { title: '类型', dataIndex: 'type', render: value => value || '-' }, { title: '状态', dataIndex: 'status', render: value => <Tag>{value}</Tag> }, { title: '金额', dataIndex: 'amount', render: value => typeof value === 'number' ? '¥' + (value / 100).toFixed(2) : '-' }]} /></WorkspaceState></Card>
    <Modal title="同步售后" open={afterSaleOpen} onCancel={() => setAfterSaleOpen(false)} footer={null}><Form form={afterSaleForm} layout="vertical" onFinish={values => syncAfterSale.mutate({ ...values, idempotency_key: 'after-sale:' + values.external_after_sale_id + ':' + Date.now() })}><Form.Item name="order_id" label="本地订单 ID" rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="external_after_sale_id" label="微信售后单号" rules={[{ required: true }]}><Input /></Form.Item>{syncAfterSale.isError && <p className="form-error">{syncAfterSale.error.message}</p>}<Button block type="primary" htmlType="submit" loading={syncAfterSale.isPending}>提交同步</Button></Form></Modal>
  </section>
}
