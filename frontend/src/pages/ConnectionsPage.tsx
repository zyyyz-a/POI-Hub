import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Card, Form, Input, Modal, Select, Space, Table, Tag, Typography } from 'antd'
import { Plus, RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { WorkspaceState } from './WorkspaceStates'
import './workspace.css'

type Connection = { id: string; capability: string; mode: string; status: string; app_id?: string | null; mock_scenario: string }
export function ConnectionsPage() {
  const { tenant } = useAuth()
  const client = useQueryClient()
  const [open, setOpen] = useState(false)
  const query = useQuery({ queryKey: ['connections', tenant?.id], queryFn: api.connections, enabled: Boolean(tenant) })
  const [form] = Form.useForm()
  const mutation = useMutation({ mutationFn: api.createConnection, onSuccess: async () => { setOpen(false); await client.invalidateQueries({ queryKey: ['connections', tenant?.id] }) } })
  const rows = (query.data ?? []) as Connection[]
  return <section className="workspace-page"><div className="page-heading"><div><Typography.Text className="page-kicker">租户微信能力</Typography.Text><Typography.Title level={2}>微信连接</Typography.Title><Typography.Paragraph>Mock 用于本地演示，Live 凭据只会加密保存在服务端。</Typography.Paragraph></div><Space><Button icon={<RefreshCw size={15} />} onClick={() => void query.refetch()}>刷新</Button><Button type="primary" icon={<Plus size={15} />} onClick={() => setOpen(true)}>新建连接</Button></Space></div><Card className="workspace-table-card" variant="borderless"><WorkspaceState loading={query.isPending} error={query.error} empty={!rows.length}><Table<Connection> rowKey="id" dataSource={rows} columns={[{ title: '能力', dataIndex: 'capability' }, { title: '模式', dataIndex: 'mode', render: value => <Tag>{value}</Tag> }, { title: '状态', dataIndex: 'status' }, { title: 'AppID', dataIndex: 'app_id', render: value => value || '-' }, { title: 'Mock 场景', dataIndex: 'mock_scenario' }]} /></WorkspaceState></Card><Modal title="新建微信连接" open={open} onCancel={() => setOpen(false)} footer={null}><Form form={form} layout="vertical" initialValues={{ mode: 'mock', mock_scenario: 'healthy' }} onFinish={values => mutation.mutate({ ...values, secrets: { app_secret: values.app_secret, access_token: values.access_token, callback_token: values.callback_token, encoding_aes_key: values.encoding_aes_key } })}><Form.Item name="capability" label="能力" rules={[{ required: true }]}><Select options={[{ value: 'local_life', label: '微信团购本地生活' }, { value: 'service_poi', label: '服务 POI' }]} /></Form.Item><Form.Item name="mode" label="模式"><Select options={[{ value: 'mock', label: 'Mock' }, { value: 'live', label: 'Live' }]} /></Form.Item><Form.Item name="app_id" label="AppID"><Input /></Form.Item><Form.Item name="merchant_id" label="商户号"><Input /></Form.Item><Form.Item name="app_secret" label="AppSecret"><Input.Password /></Form.Item><Form.Item name="access_token" label="服务端 Access Token"><Input.Password /></Form.Item><Form.Item name="callback_token" label="回调 Token"><Input.Password /></Form.Item><Form.Item name="encoding_aes_key" label="回调 EncodingAESKey"><Input.Password /></Form.Item><Form.Item name="mock_scenario" label="Mock 场景"><Select options={['healthy', 'rate_limit', 'timeout', 'server_error', 'invalid', 'permission_denied'].map(value => ({ value, label: value }))} /></Form.Item>{mutation.isError && <p className="form-error">{mutation.error.message}</p>}<Button block type="primary" htmlType="submit" loading={mutation.isPending}>创建连接</Button></Form></Modal></section>
}
