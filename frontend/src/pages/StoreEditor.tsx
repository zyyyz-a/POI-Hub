import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Button, Form, Input, Modal, Select, Space } from 'antd'
import { useState } from 'react'
import { Plus } from 'lucide-react'
import { api, type StoreRecord } from '../api/client'
import { useAuth } from '../auth/AuthProvider'

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
  return <>
    <Button type={store ? 'link' : 'primary'} icon={!store ? <Plus size={15} /> : undefined} onClick={() => { if (store) form.setFieldsValue(store); setOpen(true) }}>{store ? '编辑' : '新建门店'}</Button>
    <Modal title={store ? '编辑门店' : '新建门店'} open={open} onCancel={() => setOpen(false)} footer={null} destroyOnHidden>
      <Form form={form} layout="vertical" initialValues={{ status: 'active' }} onFinish={values => mutation.mutate(store ? { ...values, version: store.version } : values)}>
        <Form.Item name="code" label="门店编码" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="name" label="门店名称" rules={[{ required: true }]}><Input /></Form.Item>
        <Form.Item name="address" label="详细地址" rules={[{ required: true }]}><Input /></Form.Item>
        <Space.Compact block>
          <Form.Item name="city" label="城市" style={{ width: '50%' }}><Input /></Form.Item>
          <Form.Item name="district" label="区县" style={{ width: '50%' }}><Input /></Form.Item>
        </Space.Compact>
        <Form.Item name="status" label="状态"><Select options={[{ value: 'active', label: '营业中' }, { value: 'inactive', label: '停用' }]} /></Form.Item>
        {mutation.isError && <p className="form-error">{mutation.error.message}</p>}
        <Button block type="primary" htmlType="submit" loading={mutation.isPending}>{store ? '保存门店' : '创建门店'}</Button>
      </Form>
    </Modal>
  </>
}
