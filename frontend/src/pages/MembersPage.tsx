import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, Form, Input, Modal, Select, Space, Table, Tag, Typography } from 'antd'
import { Plus, RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { WorkspaceState } from './WorkspaceStates'
import './workspace.css'

type Member = { id: string; email: string; display_name: string; role: string; status: string }
export function MembersPage() {
  const { tenant } = useAuth()
  const client = useQueryClient()
  const [open, setOpen] = useState(false)
  const [inviteToken, setInviteToken] = useState<string>()
  const query = useQuery({ queryKey: ['members', tenant?.id], queryFn: api.members, enabled: Boolean(tenant) })
  const invite = useMutation({ mutationFn: api.inviteMember, onSuccess: async (result) => { setInviteToken(typeof result === 'object' && result !== null && 'invite_token' in result ? String(result.invite_token) : undefined); await client.invalidateQueries({ queryKey: ['members', tenant?.id] }) } })
  const rows = (query.data ?? []) as Member[]
  return <section className="workspace-page"><div className="page-heading"><div><Typography.Text className="page-kicker">租户权限</Typography.Text><Typography.Title level={2}>成员管理</Typography.Title><Typography.Paragraph>通过邀请分配固定角色，不开放公共注册。</Typography.Paragraph></div><Space><Button icon={<RefreshCw size={15} />} onClick={() => void query.refetch()}>刷新</Button><Button type="primary" icon={<Plus size={15} />} onClick={() => { setInviteToken(undefined); setOpen(true) }}>邀请成员</Button></Space></div><Card className="workspace-table-card" variant="borderless"><WorkspaceState loading={query.isPending} error={query.error} empty={!rows.length}><Table<Member> rowKey="id" dataSource={rows} columns={[{ title: '姓名', dataIndex: 'display_name' }, { title: '邮箱', dataIndex: 'email' }, { title: '角色', dataIndex: 'role', render: value => <Tag>{value}</Tag> }, { title: '状态', dataIndex: 'status' }]} /></WorkspaceState></Card><Modal title="邀请成员" open={open} onCancel={() => setOpen(false)} footer={null}><Form layout="vertical" initialValues={{ role: 'operator', expires_in_days: 7 }} onFinish={values => invite.mutate(values)}><Form.Item name="email" label="邮箱" rules={[{ required: true, type: 'email' }]}><Input /></Form.Item><Form.Item name="role" label="角色"><Select options={['tenant_admin', 'operator', 'verifier', 'auditor'].map(value => ({ value, label: value }))} /></Form.Item>{inviteToken && <Alert type="success" showIcon message="邀请已创建" description={<Input readOnly value={inviteToken} aria-label="邀请令牌" />} />}{invite.isError && <p className="form-error">{invite.error.message}</p>}<Button block type="primary" htmlType="submit" loading={invite.isPending}>创建邀请</Button></Form></Modal></section>
}
