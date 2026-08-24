import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, Empty, Popconfirm, Skeleton, Space, Table, Tag, Typography, message } from 'antd'
import { RefreshCw } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { api, type Tenant } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import './workspace.css'

export function TenantsPage() {
  const auth = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [messageApi, contextHolder] = message.useMessage()
  const query = useQuery({ queryKey: ['platform-tenants'], queryFn: api.platformTenants, staleTime: 0 })
  const mutation = useMutation({
    mutationFn: ({ tenantId, status }: { tenantId: string; status: 'active' | 'suspended' }) => api.setTenantStatus(tenantId, status),
    onSuccess: async (tenant) => {
      await queryClient.invalidateQueries({ queryKey: ['platform-tenants'] })
      await auth.refresh()
      messageApi.success(tenant.status === 'active' ? '商户已恢复' : '商户已停用')
    },
    onError: (error) => messageApi.error(error instanceof Error ? error.message : '状态更新失败'),
  })

  return <section className="workspace-page">
    {contextHolder}
    <div className="page-heading"><div><Typography.Text className="page-kicker">总部控制台</Typography.Text><Typography.Title level={2}>商户主控</Typography.Title><Typography.Paragraph>统一控制商户访问状态。停用后，该商户的成员、连接与业务接口立即不可访问，数据继续保留。</Typography.Paragraph></div><Space>
      {!auth.tenant && <Button onClick={() => navigate('/dashboard')}>选择商户</Button>}
      {!auth.tenant && <Button onClick={() => void auth.logout()}>退出登录</Button>}
      <Button icon={<RefreshCw size={15} />} onClick={() => void query.refetch()}>刷新</Button>
    </Space></div>
    <Card className="workspace-table-card" variant="borderless">
      {query.isPending && <div className="workspace-state"><Skeleton active paragraph={{ rows: 4 }} /></div>}
      {query.isError && <Alert type="error" showIcon message={query.error instanceof Error ? query.error.message : '商户列表加载失败'} />}
      {!query.isPending && !query.isError && !query.data?.length && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无商户" />}
      {!query.isPending && !query.isError && Boolean(query.data?.length) && <Table<Tenant>
        rowKey="id"
        dataSource={query.data}
        pagination={{ pageSize: 20 }}
        columns={[
          { title: '商户', dataIndex: 'name', key: 'name', render: (name: string, tenant) => <Space direction="vertical" size={0}><strong>{name}</strong><Typography.Text type="secondary">{tenant.slug}</Typography.Text></Space> },
          { title: '状态', dataIndex: 'status', key: 'status', render: (status: string) => <Tag color={status === 'active' ? 'green' : 'red'}>{status === 'active' ? '正常服务' : '已停用'}</Tag> },
          { title: '总部操作', key: 'actions', align: 'right', render: (_, tenant) => tenant.status === 'active'
            ? <Popconfirm title="确认停用这个商户？" description="商户成员将立即无法访问业务接口，数据不会删除。" okText="确认停用" cancelText="取消" onConfirm={() => mutation.mutate({ tenantId: tenant.id, status: 'suspended' })}><Button danger loading={mutation.isPending && mutation.variables?.tenantId === tenant.id}>停用</Button></Popconfirm>
            : <Button type="primary" loading={mutation.isPending && mutation.variables?.tenantId === tenant.id} onClick={() => mutation.mutate({ tenantId: tenant.id, status: 'active' })}>恢复服务</Button> },
        ]}
      />}
    </Card>
  </section>
}
