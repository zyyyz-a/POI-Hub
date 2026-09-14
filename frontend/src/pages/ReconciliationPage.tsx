import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, Input, Modal, Space, Table, Tag, Typography } from 'antd'
import { FileSearch, RefreshCw, Upload } from 'lucide-react'
import { useState } from 'react'
import { api, type ReconciliationBatchRecord, type ReconciliationItemRecord } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { WorkspaceState } from './WorkspaceStates'
import './workspace.css'

const money = (value?: number | null) => (value == null ? '-' : `¥${(value / 100).toFixed(2)}`)

const statusLabel: Record<string, string> = {
  matched: '一致', amount_mismatch: '金额不符', status_mismatch: '状态不符',
  missing_platform: '平台无单', missing_statement: '账单缺失'
}
const statusColor: Record<string, string> = {
  matched: 'green', amount_mismatch: 'orange', status_mismatch: 'orange',
  missing_platform: 'red', missing_statement: 'red'
}

export function ReconciliationPage() {
  const { tenant } = useAuth()
  const client = useQueryClient()
  const [billDate, setBillDate] = useState('')
  const [csv, setCsv] = useState('')
  const [selected, setSelected] = useState<ReconciliationBatchRecord | null>(null)
  const [resolveItem, setResolveItem] = useState<ReconciliationItemRecord | null>(null)
  const [note, setNote] = useState('')

  const batches = useQuery({ queryKey: ['recon-batches', tenant?.id], queryFn: api.reconciliationBatches, enabled: Boolean(tenant) })
  const items = useQuery({
    queryKey: ['recon-items', tenant?.id, selected?.id],
    queryFn: () => api.reconciliationItems(selected!.id),
    enabled: Boolean(tenant && selected)
  })

  const refresh = async () => {
    await client.invalidateQueries({ queryKey: ['recon-batches', tenant?.id] })
    if (selected) await client.invalidateQueries({ queryKey: ['recon-items', tenant?.id, selected.id] })
  }
  const importBill = useMutation({
    mutationFn: () => api.importReconciliation({ bill_date: billDate, csv }),
    onSuccess: async batch => { setCsv(''); setSelected(batch); await refresh() },
  })
  const resolve = useMutation({
    mutationFn: () => api.resolveReconciliationItem(resolveItem!.id, note),
    onSuccess: async () => { setResolveItem(null); setNote(''); await refresh() },
  })

  const batchColumns = [
    { title: '账单日期', dataIndex: 'bill_date' },
    { title: '账单合计', dataIndex: 'statement_total', render: (value: number) => money(value) },
    { title: '平台合计', dataIndex: 'platform_total', render: (value: number) => money(value) },
    { title: '一致', dataIndex: 'matched_count', render: (value: number) => <Tag color="green">{value}</Tag> },
    { title: '差异', dataIndex: 'difference_count', render: (value: number) => value ? <Tag color="red">{value}</Tag> : <Tag>0</Tag> },
    { title: '来源', dataIndex: 'source' },
    { title: '操作', render: (_: unknown, row: ReconciliationBatchRecord) => <Button size="small" type={selected?.id === row.id ? 'primary' : 'default'} onClick={() => setSelected(row)}>查看差异</Button> },
  ]

  const itemColumns = [
    { title: '商户订单号', dataIndex: 'order_no', render: (value?: string) => value || '-' },
    { title: '微信订单号', dataIndex: 'transaction_id', render: (value?: string) => value || '-' },
    { title: '账单金额', dataIndex: 'statement_amount', render: money },
    { title: '平台金额', dataIndex: 'platform_amount', render: money },
    { title: '差异类型', dataIndex: 'status', render: (value: string) => <Tag color={statusColor[value] || 'default'}>{statusLabel[value] || value}</Tag> },
    { title: '说明', dataIndex: 'note', render: (value?: string) => value || '-' },
    { title: '处理', render: (_: unknown, row: ReconciliationItemRecord) => row.status === 'matched' ? '-' : row.resolved ? <Tag color="green">已处理</Tag> : <Button size="small" onClick={() => { setResolveItem(row); setNote('') }}>登记处理</Button> },
  ]

  return <section className="workspace-page">
    <div className="page-heading"><div><Typography.Text className="page-kicker">交易对账</Typography.Text><Typography.Title level={2}>微信支付账单对账</Typography.Title><Typography.Paragraph>导入微信支付交易账单，逐单比对平台订单金额与状态，差异生成工单。</Typography.Paragraph></div><Button icon={<RefreshCw size={15} />} onClick={() => void refresh()}>刷新</Button></div>
    <Alert type="info" showIcon message="对账边界" description="只比对消费者货款订单；平台 SaaS 服务费在“平台服务费”单独对账，不与顾客货款混同。" />

    <Card className="workspace-table-card" variant="borderless" title="导入交易账单" extra={<Upload size={15} />}>
      <Space direction="vertical" style={{ width: '100%' }}>
        <Space wrap>
          <Input style={{ width: 200 }} placeholder="账单日期 YYYY-MM-DD" value={billDate} onChange={event => setBillDate(event.target.value)} />
          <Button type="primary" loading={importBill.isPending} onClick={() => importBill.mutate()} disabled={!billDate || !csv}>导入账单</Button>
        </Space>
        <Input.TextArea rows={6} placeholder="粘贴微信支付交易账单 CSV（含表头）" value={csv} onChange={event => setCsv(event.target.value)} />
        {importBill.isError && <p className="form-error">{importBill.error.message}</p>}
      </Space>
    </Card>

    <Card className="workspace-table-card" variant="borderless" title="对账批次">
      <WorkspaceState loading={batches.isPending} error={batches.error} empty={!batches.data?.length}>
        <Table rowKey="id" dataSource={batches.data || []} columns={batchColumns} pagination={false} />
      </WorkspaceState>
    </Card>

    <Card className="workspace-table-card" variant="borderless" title={selected ? `差异明细 · ${selected.bill_date}` : '差异明细'} extra={<FileSearch size={15} />}>
      <WorkspaceState loading={items.isPending} error={items.error} empty={!selected || !items.data?.length}>
        <Table rowKey="id" dataSource={items.data || []} columns={itemColumns} scroll={{ x: 900 }} />
      </WorkspaceState>
    </Card>

    <Modal title="登记差异处理" open={Boolean(resolveItem)} onCancel={() => setResolveItem(null)} onOk={() => resolve.mutate()} confirmLoading={resolve.isPending} okButtonProps={{ disabled: !note }}>
      <p className="muted">订单 {resolveItem?.order_no || '-'} · {resolveItem ? statusLabel[resolveItem.status] || resolveItem.status : ''}</p>
      <Input.TextArea rows={3} value={note} onChange={event => setNote(event.target.value)} placeholder="填写核对结论与处理方式" />
      {resolve.isError && <p className="form-error">{resolve.error.message}</p>}
    </Modal>
  </section>
}
