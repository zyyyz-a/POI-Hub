import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Card, Dropdown, Form, Input, InputNumber, Modal, Select, Space, Table, Tag, Typography } from 'antd'
import { Plus, RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { api, type ProductRecord } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { WorkspaceState } from './WorkspaceStates'
import './workspace.css'

export function ProductsPage() {
  const { tenant } = useAuth()
  const client = useQueryClient()
  const [open, setOpen] = useState(false)
  const [stockSku, setStockSku] = useState<{ id: string; name: string; stock: number; version?: number } | null>(null)
  const [stockForm] = Form.useForm()
  const [form] = Form.useForm()
  const query = useQuery({ queryKey: ['products', tenant?.id], queryFn: api.products, enabled: Boolean(tenant) })
  const connections = useQuery({ queryKey: ['connections', tenant?.id], queryFn: api.connections, enabled: Boolean(tenant) })
  const connectionRows = Array.isArray(connections.data) ? connections.data : []
  const productConnections = connectionRows.filter(item => (item as { capability?: string }).capability === 'local_life') as Array<{ id: string }>
  const create = useMutation({ mutationFn: api.createProduct, onSuccess: async () => { setOpen(false); form.resetFields(); await client.invalidateQueries({ queryKey: ['products', tenant?.id] }) } })
  const action = useMutation({ mutationFn: ({ id, action }: { id: string; action: string }) => api.productAction(id, action, 'product-action:' + id + ':' + action + ':' + Date.now()), onSuccess: async () => client.invalidateQueries({ queryKey: ['products', tenant?.id] }) })
  const stock = useMutation({ mutationFn: ({ skuId, payload }: { skuId: string; payload: Record<string, unknown> }) => api.updateStock(skuId, payload), onSuccess: async () => { setStockSku(null); stockForm.resetFields(); await client.invalidateQueries({ queryKey: ['products', tenant?.id] }) } })
  const products = query.data ?? []
  return <section className="workspace-page">
    <div className="page-heading"><div><Typography.Text className="page-kicker">微信本地生活</Typography.Text><Typography.Title level={2}>团购商品</Typography.Title><Typography.Paragraph>查看商品审核、上架状态和 SKU 库存。</Typography.Paragraph></div><Space><Button icon={<RefreshCw size={15} />} onClick={() => void query.refetch()}>刷新</Button><Button type="primary" icon={<Plus size={15} />} onClick={() => setOpen(true)}>新建商品</Button></Space></div>
    <Card className="workspace-table-card" variant="borderless"><WorkspaceState loading={query.isPending} error={query.error} empty={!products.length}>
      <Table<ProductRecord> rowKey="id" dataSource={products} pagination={{ pageSize: 10 }} columns={[
        { title: '商品名称', dataIndex: 'name', key: 'name' },
        { title: '商户商品 ID', dataIndex: 'merchant_product_id', key: 'merchant_product_id' },
        { title: '状态', dataIndex: 'remote_status', key: 'remote_status', render: (value: string) => <Tag color={value === 'listed' ? 'green' : 'gold'}>{value || '未同步'}</Tag> },
        { title: 'SKU 数', key: 'sku_count', render: (_: unknown, record) => record.skus?.length ?? 0 },
        { title: '库存', key: 'stock', render: (_: unknown, record) => <Space direction="vertical" size={0}>{record.skus?.map(sku => <Button key={sku.id} type="link" onClick={() => { setStockSku(sku); stockForm.setFieldsValue({ stock: sku.desired_stock ?? sku.stock }) }}>{sku.name}: {sku.stock}</Button>)}</Space> },
        { title: '操作', key: 'actions', render: (_, row) => <Dropdown menu={{ items: [{ key: 'list', label: '上架' }, { key: 'delist', label: '下架' }, { key: 'delete', label: '删除', danger: true }], onClick: item => item.key === 'delete' ? Modal.confirm({ title: '删除商品？', content: '删除会同步到微信，且不能恢复。', okText: '确认删除', okButtonProps: { danger: true }, cancelText: '取消', onOk: () => action.mutate({ id: row.id, action: item.key }) }) : action.mutate({ id: row.id, action: item.key }) }}><Button type="link">生命周期</Button></Dropdown> },
      ]} />
    </WorkspaceState></Card>
    <Modal title="新建团购商品" open={open} onCancel={() => setOpen(false)} footer={null} destroyOnHidden>
      <Form form={form} layout="vertical" initialValues={{ product_type: 'cash_voucher', code_source: 'wechat', sale_price: 9900, market_price: 12900, stock: 10 }} onFinish={values => create.mutate({ connection_id: values.connection_id, idempotency_key: 'product-create:' + Date.now(), merchant_product_id: values.merchant_product_id, name: values.name, product_type: values.product_type, category: values.category, brand: values.brand, code_source: values.code_source, head_images: [values.head_image], available_store_desc: values.available_store_desc, rules: JSON.parse(values.rules_json), skus: [{ merchant_sku_id: values.merchant_sku_id, name: values.sku_name, sale_price: values.sale_price, market_price: values.market_price, stock: values.stock }] })}>
        <Form.Item name="connection_id" label="本地生活连接" rules={[{ required: true }]}><Select options={productConnections.map(item => ({ value: item.id, label: item.id }))} /></Form.Item>
        <Form.Item name="merchant_product_id" label="商家商品 ID" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="name" label="商品名称" rules={[{ required: true, min: 3, max: 60 }]}><Input /></Form.Item>
        <Form.Item name="product_type" label="券类型" rules={[{ required: true }]}><Select options={[{ value: 'cash_voucher', label: '代金券' }, { value: 'exchange_voucher', label: '兑换券' }, { value: 'multi_use_card', label: '次卡' }]} /></Form.Item>
        <Form.Item name="category" label="微信三级类目 ID" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="brand" label="微信品牌 ID" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="code_source" label="券码来源" rules={[{ required: true }]}><Select options={[{ value: 'wechat', label: '微信平台生成' }, { value: 'merchant', label: '商家预存' }]} /></Form.Item>
        <Form.Item name="head_image" label="头图 URL" rules={[{ required: true, type: 'url' }]}><Input /></Form.Item>
        <Form.Item name="available_store_desc" label="可用门店说明"><Input /></Form.Item>
        <Form.Item name="rules_json" label="微信商品属性 JSON" extra="字段值须符合微信小店本地生活对应券类型的属性结构" rules={[{ required: true }, { validator: async (_, value) => { try { const parsed = JSON.parse(value); if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object' || Object.keys(parsed).length === 0) throw new Error(); } catch { throw new Error('请输入有效且非空的 JSON 对象'); } } }]}><Input.TextArea autoSize={{ minRows: 5, maxRows: 12 }} /></Form.Item>
        <Form.Item name="merchant_sku_id" label="商家 SKU ID" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="sku_name" label="SKU 名称" rules={[{ required: true }]}><Input /></Form.Item>
        <Space.Compact block><Form.Item name="sale_price" label="售价（分）" style={{ width: '33%' }}><InputNumber min={1} /></Form.Item><Form.Item name="market_price" label="市场价（分）" style={{ width: '33%' }}><InputNumber min={1} /></Form.Item><Form.Item name="stock" label="库存" style={{ width: '33%' }}><InputNumber min={0} /></Form.Item></Space.Compact>
        {create.isError && <p className="form-error">{create.error.message}</p>}
        <Button block type="primary" htmlType="submit" loading={create.isPending}>提交并等待微信处理</Button>
      </Form>
    </Modal>
    <Modal title={'调整库存：' + (stockSku?.name ?? '')} open={Boolean(stockSku)} onCancel={() => setStockSku(null)} footer={null} destroyOnHidden>
      <Form form={stockForm} layout="vertical" onFinish={values => stockSku && stock.mutate({ skuId: stockSku.id, payload: { stock: values.stock, version: stockSku.version ?? 1, idempotency_key: 'stock:' + stockSku.id + ':' + Date.now() } })}>
        <Form.Item name="stock" label="目标库存" rules={[{ required: true }]}><InputNumber min={0} style={{ width: '100%' }} /></Form.Item>
        {stock.isError && <p className="form-error">{stock.error.message}</p>}
        <Button block type="primary" htmlType="submit" loading={stock.isPending}>提交库存更新</Button>
      </Form>
    </Modal>
  </section>
}
