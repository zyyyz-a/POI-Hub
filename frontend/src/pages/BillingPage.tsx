import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, DatePicker, Form, Input, InputNumber, Modal, Select, Space, Table, Tabs, Tag, Typography } from 'antd'
import { BadgeDollarSign, FileText, Plus, RefreshCw, CreditCard } from 'lucide-react'
import { useState } from 'react'
import { api, type BillingPlanRecord, type InvoiceRecord, type SubscriptionRecord } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { WorkspaceState } from './WorkspaceStates'
import './workspace.css'

const money = (value: number) => `¥${(value / 100).toFixed(2)}`
const day = (value?: string | null) => value ? new Date(value).toLocaleDateString('zh-CN') : '-'

const statusLabel: Record<string, string> = {
  active: '服务中', past_due: '已逾期', suspended: '已停用', cancelled: '已取消',
  issued: '待收款', overdue: '已逾期', paid: '已结清', partially_paid: '部分收款', void: '已作废',
  monthly: '按月', yearly: '按年',
}
const statusColor: Record<string, string> = {
  active: 'green', paid: 'green', issued: 'blue', partially_paid: 'orange',
  past_due: 'orange', overdue: 'red', suspended: 'red', cancelled: 'default', void: 'default',
}
const StatusTag = ({ value }: { value: string }) => <Tag color={statusColor[value] || 'default'}>{statusLabel[value] || value}</Tag>

export function BillingPage() {
  const { tenant, user } = useAuth()
  const client = useQueryClient()
  const [planModal, setPlanModal] = useState(false)
  const [subModal, setSubModal] = useState(false)
  const [invoiceModal, setInvoiceModal] = useState(false)
  const [paymentFor, setPaymentFor] = useState<InvoiceRecord | null>(null)
  const [adjustFor, setAdjustFor] = useState<InvoiceRecord | null>(null)
  const [planForm] = Form.useForm()
  const [subForm] = Form.useForm()
  const [invoiceForm] = Form.useForm()
  const [paymentForm] = Form.useForm()
  const [adjustForm] = Form.useForm()

  const isPlatformAdmin = Boolean(user?.is_platform_admin)
  const plans = useQuery({ queryKey: ['billing-plans'], queryFn: api.billingPlans, enabled: isPlatformAdmin })
  const subscriptions = useQuery({ queryKey: ['billing-subscriptions'], queryFn: api.billingSubscriptions, enabled: isPlatformAdmin })
  const invoices = useQuery({ queryKey: ['billing-invoices', tenant?.id], queryFn: api.billingInvoices, enabled: Boolean(tenant) })
  const summary = useQuery({ queryKey: ['billing-summary', tenant?.id], queryFn: api.billingSummary, enabled: Boolean(tenant) })
  const tenants = useQuery({ queryKey: ['platform-tenants'], queryFn: api.platformTenants, enabled: isPlatformAdmin })

  const refresh = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: ['billing-plans'] }),
      client.invalidateQueries({ queryKey: ['billing-subscriptions'] }),
      client.invalidateQueries({ queryKey: ['billing-invoices', tenant?.id] }),
      client.invalidateQueries({ queryKey: ['billing-summary', tenant?.id] }),
    ])
  }

  const createPlan = useMutation({
    mutationFn: (values: Record<string, unknown>) => api.createBillingPlan({ ...values, price: Math.round(Number(values.price_yuan) * 100) }),
    onSuccess: async () => { setPlanModal(false); planForm.resetFields(); await refresh() },
  })
  const createSubscription = useMutation({
    mutationFn: (values: Record<string, unknown>) => api.createBillingSubscription(values),
    onSuccess: async () => { setSubModal(false); subForm.resetFields(); await refresh() },
  })
  const generateInvoice = useMutation({
    mutationFn: (values: Record<string, unknown>) => api.generateBillingInvoice({
      tenant_id: tenant?.id,
      period_start: (values.period as [unknown, unknown])[0],
      period_end: (values.period as [unknown, unknown])[1],
      amount: values.amount_yuan != null ? Math.round(Number(values.amount_yuan) * 100) : undefined,
      description: values.description ? String(values.description) : undefined,
    }),
    onSuccess: async () => { setInvoiceModal(false); invoiceForm.resetFields(); await refresh() },
  })
  const recordPayment = useMutation({
    mutationFn: (values: Record<string, unknown>) => api.recordBillingPayment(paymentFor!.id, { ...values, amount: Math.round(Number(values.amount_yuan) * 100) }),
    onSuccess: async () => { setPaymentFor(null); paymentForm.resetFields(); await refresh() },
  })
  const recordAdjustment = useMutation({
    mutationFn: (values: Record<string, unknown>) => api.recordBillingAdjustment(adjustFor!.id, { ...values, amount: Math.round(Number(values.amount_yuan) * 100) }),
    onSuccess: async () => { setAdjustFor(null); adjustForm.resetFields(); await refresh() },
  })

  const planName = (planId: string) => (plans.data || []).find(item => item.id === planId)?.name || planId

  const planColumns = [
    { title: '套餐', render: (_: unknown, row: BillingPlanRecord) => <div><strong>{row.name}</strong><br /><Typography.Text type="secondary">{row.code}</Typography.Text></div> },
    { title: '价格', dataIndex: 'price', render: (value: number) => money(value) },
    { title: '周期', dataIndex: 'billing_period', render: (value: string, row: BillingPlanRecord) => `${statusLabel[value] || value} · ${row.period_days} 天` },
    { title: '状态', dataIndex: 'status', render: (value: string) => <Tag color={value === 'active' ? 'green' : 'default'}>{value === 'active' ? '启用' : '停用'}</Tag> },
  ]
  const subColumns = [
    { title: '商户', dataIndex: 'tenant_id', render: (value: string) => (tenants.data || []).find(item => item.id === value)?.name || value },
    { title: '套餐', dataIndex: 'plan_id', render: (value: string) => planName(value) },
    { title: '状态', dataIndex: 'status', render: (value: string) => <StatusTag value={value} /> },
    { title: '本周期', render: (_: unknown, row: SubscriptionRecord) => `${day(row.current_period_start)} ~ ${day(row.current_period_end)}` },
    { title: '宽限至', dataIndex: 'grace_until', render: day },
  ]
  const invoiceColumns = [
    { title: '账单号', dataIndex: 'invoice_no' },
    { title: '账期', render: (_: unknown, row: InvoiceRecord) => `${day(row.period_start)} ~ ${day(row.period_end)}` },
    { title: '应收', dataIndex: 'amount', render: (value: number) => money(value) },
    { title: '已收', dataIndex: 'paid_amount', render: (value: number) => money(value) },
    { title: '状态', dataIndex: 'status', render: (value: string) => <StatusTag value={value} /> },
    { title: '到期', dataIndex: 'due_at', render: day },
    { title: '操作', render: (_: unknown, row: InvoiceRecord) => isPlatformAdmin && !['paid', 'void'].includes(row.status) ? <Space>
      <Button size="small" onClick={() => { setPaymentFor(row); paymentForm.setFieldsValue({ amount_yuan: (row.amount - row.paid_amount) / 100, method: 'bank_transfer' }) }}>录入收款</Button>
      <Button size="small" onClick={() => setAdjustFor(row)}>减免/冲正</Button>
    </Space> : '-' },
  ]

  const summaryData = summary.data

  return <section className="workspace-page">
    <div className="page-heading"><div><Typography.Text className="page-kicker">平台服务费</Typography.Text><Typography.Title level={2}>订阅、账单与收款</Typography.Title><Typography.Paragraph>平台服务费独立开账，不进入顾客货款；欠费只停新交易，不删除历史账单。</Typography.Paragraph></div><Button icon={<RefreshCw size={15} />} onClick={() => void refresh()}>刷新</Button></div>
    {summaryData?.blocked && <Alert type="error" showIcon message="商户交易已被暂停" description={summaryData.blockers.join('、')} />}
    <Tabs items={[
      {
        key: 'summary', label: <span><BadgeDollarSign size={15} /> 我的服务费</span>,
        children: <Card className="workspace-table-card" variant="borderless" title="当前订阅">
          <WorkspaceState loading={summary.isPending} error={summary.error} empty={!summaryData?.subscription}>
            {summaryData?.subscription && <Space direction="vertical" size="middle">
              <div><Typography.Text type="secondary">套餐</Typography.Text><div><strong>{summaryData.plan?.name || summaryData.subscription.plan_id}</strong> · {summaryData.plan ? money(summaryData.plan.price) : ''}</div></div>
              <div><Typography.Text type="secondary">状态</Typography.Text><div><StatusTag value={summaryData.subscription.status} /></div></div>
              <div><Typography.Text type="secondary">本周期</Typography.Text><div>{day(summaryData.subscription.current_period_start)} ~ {day(summaryData.subscription.current_period_end)}</div></div>
              <div><Typography.Text type="secondary">未结金额</Typography.Text><div><strong>{money(summaryData.outstanding_amount)}</strong></div></div>
            </Space>}
          </WorkspaceState>
        </Card>,
      },
      ...(isPlatformAdmin ? [
        {
          key: 'plans', label: <span><CreditCard size={15} /> 套餐</span>,
          children: <Card className="workspace-table-card" variant="borderless" title="服务套餐" extra={<Button type="primary" icon={<Plus size={15} />} onClick={() => setPlanModal(true)}>新增套餐</Button>}>
            <WorkspaceState loading={plans.isPending} error={plans.error} empty={!plans.data?.length}><Table rowKey="id" dataSource={plans.data || []} columns={planColumns} /></WorkspaceState>
          </Card>,
        },
        {
          key: 'subscriptions', label: <span><BadgeDollarSign size={15} /> 订阅</span>,
          children: <Card className="workspace-table-card" variant="borderless" title="商户订阅" extra={<Button type="primary" icon={<Plus size={15} />} onClick={() => setSubModal(true)}>新建订阅</Button>}>
            <WorkspaceState loading={subscriptions.isPending} error={subscriptions.error} empty={!subscriptions.data?.length}><Table rowKey="id" dataSource={subscriptions.data || []} columns={subColumns} /></WorkspaceState>
          </Card>,
        },
      ] : []),
      {
        key: 'invoices', label: <span><FileText size={15} /> 账单</span>,
        children: <Card className="workspace-table-card" variant="borderless" title="服务费账单" extra={isPlatformAdmin && <Button type="primary" icon={<Plus size={15} />} onClick={() => setInvoiceModal(true)}>生成账单</Button>}>
          <WorkspaceState loading={invoices.isPending} error={invoices.error} empty={!invoices.data?.length}><Table rowKey="id" dataSource={invoices.data || []} columns={invoiceColumns} /></WorkspaceState>
        </Card>,
      },
    ]} />

    <Modal title="新增套餐" open={planModal} onCancel={() => setPlanModal(false)} footer={null}><Form form={planForm} layout="vertical" initialValues={{ billing_period: 'monthly', period_days: 30, price_yuan: 199 }} onFinish={values => createPlan.mutate(values)}>
      <Form.Item name="code" label="套餐编码" rules={[{ required: true }]}><Input /></Form.Item>
      <Form.Item name="name" label="套餐名称" rules={[{ required: true }]}><Input /></Form.Item>
      <Form.Item name="description" label="说明"><Input.TextArea /></Form.Item>
      <Space><Form.Item name="price_yuan" label="价格（元）" rules={[{ required: true }]}><InputNumber min={0} precision={2} /></Form.Item><Form.Item name="period_days" label="周期天数"><InputNumber min={1} precision={0} /></Form.Item></Space>
      <Form.Item name="billing_period" label="计费周期"><Select options={[{ value: 'monthly', label: '按月' }, { value: 'yearly', label: '按年' }]} /></Form.Item>
      {createPlan.isError && <p className="form-error">{createPlan.error.message}</p>}<Button block type="primary" htmlType="submit" loading={createPlan.isPending}>保存</Button>
    </Form></Modal>

    <Modal title="新建订阅" open={subModal} onCancel={() => setSubModal(false)} footer={null}><Form form={subForm} layout="vertical" initialValues={{ grace_days: 7 }} onFinish={values => createSubscription.mutate(values)}>
      <Form.Item name="tenant_id" label="商户" rules={[{ required: true }]}><Select options={(tenants.data || []).map(item => ({ value: item.id, label: item.name }))} /></Form.Item>
      <Form.Item name="plan_id" label="套餐" rules={[{ required: true }]}><Select options={(plans.data || []).map(item => ({ value: item.id, label: `${item.name} · ${money(item.price)}` }))} /></Form.Item>
      <Form.Item name="grace_days" label="宽限天数"><InputNumber min={0} /></Form.Item>
      {createSubscription.isError && <p className="form-error">{createSubscription.error.message}</p>}<Button block type="primary" htmlType="submit" loading={createSubscription.isPending}>保存</Button>
    </Form></Modal>

    <Modal title="生成服务费账单" open={invoiceModal} onCancel={() => setInvoiceModal(false)} footer={null}><Form form={invoiceForm} layout="vertical" initialValues={{ description: 'SaaS 服务费' }} onFinish={values => generateInvoice.mutate(values)}>
      <Form.Item name="period" label="账期" rules={[{ required: true }]}><DatePicker.RangePicker style={{ width: '100%' }} /></Form.Item>
      <Form.Item name="amount_yuan" label="固定金额（元，留空则按用量计费）"><InputNumber min={0} precision={2} style={{ width: '100%' }} /></Form.Item>
      <Form.Item name="description" label="账单说明"><Input /></Form.Item>
      {generateInvoice.isError && <p className="form-error">{generateInvoice.error.message}</p>}<Button block type="primary" htmlType="submit" loading={generateInvoice.isPending}>生成</Button>
    </Form></Modal>

    <Modal title="录入收款" open={Boolean(paymentFor)} onCancel={() => { setPaymentFor(null); paymentForm.resetFields() }} footer={null}><Form form={paymentForm} layout="vertical" onFinish={values => recordPayment.mutate(values)}>
      <Form.Item name="amount_yuan" label="收款金额（元）" rules={[{ required: true }]}><InputNumber min={0.01} precision={2} style={{ width: '100%' }} /></Form.Item>
      <Form.Item name="method" label="收款方式"><Select options={[{ value: 'bank_transfer', label: '对公转账' }, { value: 'payment_code', label: '收款码' }, { value: 'cash', label: '现金' }, { value: 'other', label: '其他' }]} /></Form.Item>
      <Form.Item name="reference" label="凭证号"><Input /></Form.Item>
      {recordPayment.isError && <p className="form-error">{recordPayment.error.message}</p>}<Button block type="primary" htmlType="submit" loading={recordPayment.isPending}>确认收款</Button>
    </Form></Modal>

    <Modal title="减免 / 冲正" open={Boolean(adjustFor)} onCancel={() => { setAdjustFor(null); adjustForm.resetFields() }} footer={null}><Form form={adjustForm} layout="vertical" initialValues={{ kind: 'discount' }} onFinish={values => recordAdjustment.mutate(values)}>
      <Form.Item name="kind" label="类型"><Select options={[{ value: 'discount', label: '减免' }, { value: 'refund', label: '退款' }, { value: 'writeoff', label: '坏账核销' }, { value: 'surcharge', label: '补收' }]} /></Form.Item>
      <Form.Item name="amount_yuan" label="金额（元，负数为冲减）" rules={[{ required: true }]}><InputNumber precision={2} style={{ width: '100%' }} /></Form.Item>
      <Form.Item name="reason" label="原因" rules={[{ required: true }]}><Input.TextArea /></Form.Item>
      {recordAdjustment.isError && <p className="form-error">{recordAdjustment.error.message}</p>}<Button block type="primary" htmlType="submit" loading={recordAdjustment.isPending}>保存</Button>
    </Form></Modal>
  </section>
}
