import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, Form, Input, Modal, Select, Space, Table, Tag, Typography } from 'antd'
import { Plus, RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { WorkspaceState } from './WorkspaceStates'
import './workspace.css'

type Connection = {
  id: string
  capability: string
  mode: string
  status: string
  app_id?: string | null
  merchant_id?: string | null
  mock_scenario: string
}

const capabilityLabel: Record<string, string> = {
  local_life: '微信小店本地生活（兼容）',
  service_poi: '腾讯位置／服务 POI',
  mini_program_commerce: '独立小程序交易与支付',
}

export function ConnectionsPage() {
  const { tenant } = useAuth()
  const client = useQueryClient()
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm()
  const capability = Form.useWatch('capability', form)
  const mode = Form.useWatch('mode', form)
  const query = useQuery({ queryKey: ['connections', tenant?.id], queryFn: api.connections, enabled: Boolean(tenant) })
  const mutation = useMutation({
    mutationFn: api.createConnection,
    onSuccess: async () => {
      setOpen(false)
      form.resetFields()
      await client.invalidateQueries({ queryKey: ['connections', tenant?.id] })
    },
  })
  const rows = (query.data ?? []) as Connection[]

  return <section className="workspace-page">
    <div className="page-heading">
      <div><Typography.Text className="page-kicker">租户微信能力</Typography.Text><Typography.Title level={2}>微信连接</Typography.Title><Typography.Paragraph>真实凭据仅加密保存在服务端，不会返回浏览器。</Typography.Paragraph></div>
      <Space><Button icon={<RefreshCw size={15} />} onClick={() => void query.refetch()}>刷新</Button><Button type="primary" icon={<Plus size={15} />} onClick={() => setOpen(true)}>新建连接</Button></Space>
    </div>
    <Card className="workspace-table-card" variant="borderless"><WorkspaceState loading={query.isPending} error={query.error} empty={!rows.length}>
      <Table<Connection> rowKey="id" dataSource={rows} columns={[
        { title: '能力', dataIndex: 'capability', render: value => capabilityLabel[value] || value },
        { title: '模式', dataIndex: 'mode', render: value => <Tag>{value}</Tag> },
        { title: '状态', dataIndex: 'status' },
        { title: 'AppID', dataIndex: 'app_id', render: value => value || '-' },
        { title: '商户号', dataIndex: 'merchant_id', render: value => value || '-' },
        { title: 'Mock 场景', dataIndex: 'mock_scenario' },
      ]} />
    </WorkspaceState></Card>
    <Modal title="新建微信连接" open={open} onCancel={() => setOpen(false)} footer={null}>
      <Form form={form} layout="vertical" initialValues={{ mode: 'mock', mock_scenario: 'healthy' }} onFinish={values => mutation.mutate({
        capability: values.capability,
        mode: values.mode,
        app_id: values.app_id,
        merchant_id: values.merchant_id,
        mock_scenario: values.mock_scenario,
        secrets: {
          app_secret: values.app_secret,
          access_token: values.access_token,
          callback_token: values.callback_token,
          encoding_aes_key: values.encoding_aes_key,
          merchant_private_key_pem: values.merchant_private_key_pem,
          merchant_serial_no: values.merchant_serial_no,
          api_v3_key: values.api_v3_key,
          wechatpay_public_key_pem: values.wechatpay_public_key_pem,
          wechatpay_public_key_id: values.wechatpay_public_key_id,
          notify_url: values.notify_url,
        },
      })}>
        <Form.Item name="capability" label="能力" rules={[{ required: true }]}><Select options={[
          { value: 'mini_program_commerce', label: '独立小程序交易与支付（推荐）' },
          { value: 'service_poi', label: '腾讯位置／服务 POI' },
          { value: 'local_life', label: '微信团购本地生活' },
        ]} /></Form.Item>
        <Form.Item name="mode" label="模式"><Select options={[{ value: 'mock', label: '模拟验收' }, { value: 'live', label: '真实微信' }]} /></Form.Item>
        {mode === 'live' && <Alert type="warning" showIcon message="真实凭据不要通过聊天发送，请直接粘贴到这里。" style={{ marginBottom: 16 }} />}
        <Form.Item name="app_id" label="AppID" rules={mode === 'live' ? [{ required: true }] : []}><Input /></Form.Item>
        <Form.Item name="merchant_id" label="微信支付商户号"><Input /></Form.Item>
        <Form.Item name="app_secret" label="AppSecret"><Input.Password /></Form.Item>
        {capability === 'mini_program_commerce' && <>
          <Form.Item name="merchant_serial_no" label="商户 API 证书序列号"><Input /></Form.Item>
          <Form.Item name="merchant_private_key_pem" label="商户 API 私钥 PEM"><Input.TextArea rows={4} /></Form.Item>
          <Form.Item name="api_v3_key" label="APIv3 密钥（32 字节）"><Input.Password /></Form.Item>
          <Form.Item name="wechatpay_public_key_id" label="微信支付公钥 ID"><Input /></Form.Item>
          <Form.Item name="wechatpay_public_key_pem" label="微信支付公钥 PEM"><Input.TextArea rows={4} /></Form.Item>
          <Form.Item name="notify_url" label="支付通知地址"><Input placeholder="https://你的域名/api/v1/public/wechatpay/notify/小程序登记ID" /></Form.Item>
        </>}
        {capability !== 'mini_program_commerce' && <>
          <Form.Item name="access_token" label="服务端 Access Token"><Input.Password /></Form.Item>
          <Form.Item name="callback_token" label="回调 Token"><Input.Password /></Form.Item>
          <Form.Item name="encoding_aes_key" label="回调 EncodingAESKey"><Input.Password /></Form.Item>
        </>}
        <Form.Item name="mock_scenario" label="模拟场景"><Select options={['healthy', 'rate_limit', 'timeout', 'server_error', 'invalid', 'permission_denied'].map(value => ({ value, label: value }))} /></Form.Item>
        {mutation.isError && <p className="form-error">{mutation.error.message}</p>}
        <Button block type="primary" htmlType="submit" loading={mutation.isPending}>创建连接</Button>
      </Form>
    </Modal>
  </section>
}
