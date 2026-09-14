import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Button, Form, Input, InputNumber, Modal, Select, Space } from 'antd'
import { useState } from 'react'
import { Plus } from 'lucide-react'
import { api, type StoreRecord } from '../api/client'
import { useAuth } from '../auth/AuthProvider'

function normalizeImages(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(String)
  return String(value || '')
    .split('\n')
    .map(item => item.trim())
    .filter(Boolean)
    .slice(0, 6)
}

export function StoreEditor({ store, onDone }: { store?: StoreRecord; onDone?: () => void }) {
  const { tenant } = useAuth()
  const client = useQueryClient()
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm()
  const mutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) => store
      ? api.updateStore(store.id, payload)
      : api.createStore(payload),
    onSuccess: async () => {
      setOpen(false)
      form.resetFields()
      await client.invalidateQueries({ queryKey: ['stores', tenant?.id] })
      onDone?.()
    },
  })
  const openEditor = () => {
    if (store) {
      form.setFieldsValue({ ...store, environment_images: (store.environment_images || []).join('\n') })
    }
    setOpen(true)
  }
  return <>
    <Button type={store ? 'link' : 'primary'} icon={!store ? <Plus size={15} /> : undefined} onClick={openEditor}>{store ? '编辑' : '新建门店'}</Button>
    <Modal title={store ? '编辑门店' : '新建门店'} open={open} onCancel={() => setOpen(false)} footer={null} destroyOnHidden width={640}>
      <Form form={form} layout="vertical" initialValues={{ status: 'active' }} onFinish={values => {
        const payload: Record<string, unknown> = { ...values, environment_images: normalizeImages(values.environment_images) }
        mutation.mutate(store ? { ...payload, version: store.version } : payload)
      }}>
        <Space.Compact block>
          <Form.Item name="code" label="门店编码" rules={[{ required: true }]} style={{ width: '40%' }}><Input /></Form.Item>
          <Form.Item name="name" label="门店名称" rules={[{ required: true }]} style={{ width: '60%' }}><Input /></Form.Item>
        </Space.Compact>
        <Form.Item name="address" label="详细地址" rules={[{ required: true }]}><Input /></Form.Item>
        <Space.Compact block>
          <Form.Item name="city" label="城市" style={{ width: '50%' }}><Input /></Form.Item>
          <Form.Item name="district" label="区县" style={{ width: '50%' }}><Input /></Form.Item>
        </Space.Compact>
        <Space.Compact block>
          <Form.Item name="business_hours" label="营业时间" style={{ width: '50%' }}><Input placeholder="09:00-21:00" /></Form.Item>
          <Form.Item name="public_phone" label="对外电话" style={{ width: '50%' }}><Input placeholder="展示给顾客的电话" /></Form.Item>
        </Space.Compact>
        <Space.Compact block>
          <Form.Item name="cover_image" label="门店头图 URL" style={{ width: '50%' }}><Input /></Form.Item>
          <Form.Item name="logo" label="Logo URL" style={{ width: '50%' }}><Input /></Form.Item>
        </Space.Compact>
        <Space.Compact block>
          <Form.Item name="latitude" label="纬度" style={{ width: '50%' }}><InputNumber style={{ width: '100%' }} precision={6} /></Form.Item>
          <Form.Item name="longitude" label="经度" style={{ width: '50%' }}><InputNumber style={{ width: '100%' }} precision={6} /></Form.Item>
        </Space.Compact>
        <Form.Item name="intro" label="门店简介"><Input.TextArea rows={2} maxLength={2000} showCount /></Form.Item>
        <Form.Item name="environment_images" label="门店环境图（每行一个 URL，最多 6 张）"><Input.TextArea rows={3} placeholder="https://.../1.jpg" /></Form.Item>
        <Form.Item name="service_guarantees" label="服务保障"><Input.TextArea rows={2} placeholder="真实门店 · 到店核销 · 未使用可申请退款" /></Form.Item>
        <Form.Item name="appointment_notes" label="预约与退款说明"><Input.TextArea rows={2} /></Form.Item>
        <Form.Item name="status" label="状态"><Select options={[{ value: 'active', label: '营业中' }, { value: 'inactive', label: '停用' }]} /></Form.Item>
        {mutation.isError && <p className="form-error">{mutation.error.message}</p>}
        <Button block type="primary" htmlType="submit" loading={mutation.isPending}>{store ? '保存门店' : '创建门店'}</Button>
      </Form>
    </Modal>
  </>
}
