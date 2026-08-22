import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Card, Space, Table, Tag, Typography } from 'antd'
import { Check, RefreshCw, X } from 'lucide-react'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { WorkspaceState } from './WorkspaceStates'
import './workspace.css'

type Candidate = { id: string; store_id: string; service_poi_id: string; total_score: number; name_score: number; address_score: number; distance_meters?: number | null }

export function MappingsPage() {
  const { tenant, membership, user } = useAuth()
  const client = useQueryClient()
  const editable = Boolean(user?.is_platform_admin || ['tenant_admin', 'operator'].includes(membership?.role ?? ''))
  const query = useQuery({ queryKey: ['candidates', tenant?.id], queryFn: api.candidates, enabled: Boolean(tenant) })
  const mutation = useMutation({
    mutationFn: ({ id, action }: { id: string; action: 'confirm' | 'dismiss' }) => action === 'confirm' ? api.confirmCandidate(id) : api.dismissCandidate(id),
    onSuccess: async () => {
      await Promise.all([client.invalidateQueries({ queryKey: ['candidates', tenant?.id] }), client.invalidateQueries({ queryKey: ['mappings', tenant?.id] })])
    },
  })
  const candidates = (query.data ?? []) as Candidate[]
  return <section className="workspace-page">
    <div className="page-heading"><div><Typography.Text className="page-kicker">门店与 POI</Typography.Text><Typography.Title level={2}>POI 映射</Typography.Title><Typography.Paragraph>候选关系只有经过人工确认后才会用于券码核销。</Typography.Paragraph></div><Button icon={<RefreshCw size={15} />} onClick={() => void query.refetch()}>刷新</Button></div>
    <Card className="workspace-table-card" variant="borderless"><WorkspaceState loading={query.isPending} error={query.error ?? mutation.error} empty={!candidates.length}>
      <Table<Candidate> rowKey="id" dataSource={candidates} columns={[
        { title: '门店 ID', dataIndex: 'store_id', ellipsis: true },
        { title: 'POI ID', dataIndex: 'service_poi_id', ellipsis: true },
        { title: '综合匹配度', dataIndex: 'total_score', render: (value: number) => <Tag color={value >= .8 ? 'green' : 'gold'}>{Math.round(value * 100)}%</Tag> },
        { title: '名称 / 地址', render: (_, row) => String(Math.round(row.name_score * 100)) + '% / ' + String(Math.round(row.address_score * 100)) + '%' },
        { title: '距离', dataIndex: 'distance_meters', render: (value?: number) => value == null ? '-' : String(Math.round(value)) + ' m' },
        { title: '操作', render: (_, row) => editable && <Space><Button type="primary" size="small" icon={<Check size={14} />} loading={mutation.isPending} onClick={() => mutation.mutate({ id: row.id, action: 'confirm' })}>确认</Button><Button size="small" icon={<X size={14} />} onClick={() => mutation.mutate({ id: row.id, action: 'dismiss' })}>忽略</Button></Space> },
      ]} />
    </WorkspaceState></Card>
  </section>
}
