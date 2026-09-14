import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from 'antd'
import { ClipboardCheck, Link2, Plus, RefreshCw, Smartphone } from 'lucide-react'
import { useMemo, useState } from 'react'
import {
  api,
  type MiniProgramRecord,
  type OnboardingCaseRecord,
  type PositionServiceRecord,
  type QualificationItem,
} from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { WorkspaceState } from './WorkspaceStates'
import './workspace.css'

const requirementLabels: Record<string, string> = {
  official_category_open: '官方当前开放该类目和地区',
  region_supported: '经营地区在当前开放范围内',
  business_license: '营业执照真实有效',
  merchant_admin_confirmed: '商家超级管理员本人确认',
  storefront_photo: '真实清晰门头照片',
  interior_photo: '真实店内环境照片',
  public_phone: '可公开且能接审核电话的门店号码',
  map_location: '腾讯地图点位真实且落点正确',
  settlement_account: '结算账户与商户主体匹配',
}

const statusColor: Record<string, string> = {
  passed: 'green', approved: 'green', authorized: 'green', mounted: 'green', active: 'green', ready: 'green',
  failed: 'red', rejected: 'red', blocked: 'red',
  under_review: 'blue', authorization_pending: 'blue', in_progress: 'blue',
  paused: 'orange', needs_more_info: 'orange',
  pending: 'default', not_submitted: 'default', not_started: 'default', draft: 'default',
}

const statusLabel: Record<string, string> = {
  pending: '待预审', passed: '预审通过', failed: '预审未通过',
  not_submitted: '未报备', under_review: '审核中', approved: '已通过', rejected: '未通过', paused: '暂停受理', needs_more_info: '需补件',
  not_started: '未开始', draft: '草稿', service_defined: '服务已定义', authorization_pending: '授权中', authorized: '已授权', mounted: '已挂载', unmounted: '已取消挂载',
  active: '已启用', suspended: '已停用', not_configured: '未配置', configured: '已配置',
}

function StatusTag({ value }: { value: string }) {
  return <Tag color={statusColor[value] || 'default'}>{statusLabel[value] || value}</Tag>
}

type CaseAction = 'precheck' | 'submission' | 'decision'

export function OnboardingPage() {
  const { tenant, user } = useAuth()
  const client = useQueryClient()
  const [caseModal, setCaseModal] = useState(false)
  const [caseAction, setCaseAction] = useState<{ mode: CaseAction; row: OnboardingCaseRecord } | null>(null)
  const [miniModal, setMiniModal] = useState<{ row?: MiniProgramRecord } | null>(null)
  const [mountModal, setMountModal] = useState(false)
  const [transition, setTransition] = useState<{ row: PositionServiceRecord; target: string } | null>(null)
  const [caseForm] = Form.useForm()
  const [actionForm] = Form.useForm()
  const [miniForm] = Form.useForm()
  const [mountForm] = Form.useForm()
  const [transitionForm] = Form.useForm()

  const cases = useQuery({ queryKey: ['onboarding-cases', tenant?.id], queryFn: api.onboardingCases, enabled: Boolean(tenant) })
  const connections = useQuery({ queryKey: ['connections', tenant?.id], queryFn: api.connections, enabled: Boolean(tenant) })
  const stores = useQuery({ queryKey: ['stores', tenant?.id], queryFn: api.stores, enabled: Boolean(tenant) })
  const pois = useQuery({ queryKey: ['pois', tenant?.id], queryFn: api.pois, enabled: Boolean(tenant) })
  const miniPrograms = useQuery({ queryKey: ['mini-programs', tenant?.id], queryFn: api.miniPrograms, enabled: Boolean(tenant) })
  const mounts = useQuery({ queryKey: ['position-services', tenant?.id], queryFn: api.positionServices, enabled: Boolean(tenant) })
  const refreshAll = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: ['onboarding-cases', tenant?.id] }),
      client.invalidateQueries({ queryKey: ['mini-programs', tenant?.id] }),
      client.invalidateQueries({ queryKey: ['position-services', tenant?.id] }),
    ])
  }

  const createCase = useMutation({ mutationFn: api.createOnboardingCase, onSuccess: async () => { setCaseModal(false); caseForm.resetFields(); await refreshAll() } })
  const mutateCase = useMutation({ mutationFn: async (values: Record<string, unknown>) => {
    if (!caseAction) throw new Error('未选择准入工单')
    if (caseAction.mode === 'precheck') {
      const checked = new Set(values.checked as string[])
      const evidence = String(values.evidence_reference)
      const items: QualificationItem[] = Object.entries(requirementLabels).map(([code, label]) => ({ code, label, required: true, present: checked.has(code), verified: checked.has(code), evidence_reference: checked.has(code) ? evidence : null }))
      return api.runOnboardingPrecheck(caseAction.row.id, { items, rule_source_reference: String(values.rule_source_reference) })
    }
    if (caseAction.mode === 'submission') return api.recordOfficialSubmission(caseAction.row.id, { official_reference: String(values.official_reference), evidence_reference: String(values.evidence_reference) })
    return api.recordOfficialDecision(caseAction.row.id, { decision: String(values.decision), evidence_reference: String(values.evidence_reference), message: values.message ? String(values.message) : undefined })
  }, onSuccess: async () => { setCaseAction(null); actionForm.resetFields(); await refreshAll() } })

  const mutateMini = useMutation({ mutationFn: async (values: Record<string, unknown>) => {
    if (miniModal?.row) return api.updateMiniProgram(miniModal.row.id, { ...values, version: miniModal.row.version })
    return api.createMiniProgram(values)
  }, onSuccess: async () => { setMiniModal(null); miniForm.resetFields(); await refreshAll() } })

  const createMount = useMutation({ mutationFn: api.createPositionService, onSuccess: async () => { setMountModal(false); mountForm.resetFields(); await refreshAll() } })
  const transitionMount = useMutation({ mutationFn: (values: Record<string, unknown>) => {
    if (!transition) throw new Error('未选择位置服务')
    return api.transitionPositionService(transition.row.id, { ...values, status: transition.target, version: transition.row.version })
  }, onSuccess: async () => { setTransition(null); transitionForm.resetFields(); await refreshAll() } })

  const storeNames = useMemo(() => new Map((stores.data || []).map(item => [item.id, item.name])), [stores.data])
  const appNames = useMemo(() => new Map((miniPrograms.data || []).map(item => [item.id, item.name])), [miniPrograms.data])

  const openCaseAction = (mode: CaseAction, row: OnboardingCaseRecord) => {
    setCaseAction({ mode, row })
    if (mode === 'precheck') {
      actionForm.setFieldsValue({ checked: row.requirements.filter(item => item.verified).map(item => item.code) })
    }
  }

  const showReadiness = async (row: OnboardingCaseRecord) => {
    try {
      const result = await api.onboardingReadiness(row.id)
      Modal.info({ title: result.ready ? '已具备真实试点条件' : '尚未达到真实试点条件', content: result.ready ? '准入、位置、小程序、支付和回调门禁均已通过。' : <ul>{result.blockers.map(item => <li key={item}>{item}</li>)}</ul> })
    } catch (error) {
      Modal.error({ title: '读取失败', content: error instanceof Error ? error.message : '无法读取门禁状态' })
    }
  }

  const caseColumns = [
    { title: '门店', dataIndex: 'store_id', render: (value: string) => storeNames.get(value) || value },
    { title: '路线/类目', render: (_: unknown, row: OnboardingCaseRecord) => <div><strong>{row.category_name}</strong><br /><Typography.Text type="secondary">{row.route}</Typography.Text></div> },
    { title: '预审', dataIndex: 'precheck_status', render: (value: string) => <StatusTag value={value} /> },
    { title: '官方报备', dataIndex: 'official_status', render: (value: string) => <StatusTag value={value} /> },
    { title: '位置权限', dataIndex: 'position_status', render: (value: string) => <StatusTag value={value} /> },
    { title: '下一步', dataIndex: 'next_action', render: (value?: string, row?: OnboardingCaseRecord) => <div>{value || '-'}{row?.blocker_message && <Typography.Text type="danger"><br />{row.blocker_message}</Typography.Text>}</div> },
    { title: '操作', render: (_: unknown, row: OnboardingCaseRecord) => <Space wrap>
      <Button size="small" onClick={() => openCaseAction('precheck', row)}>填写预审</Button>
      {row.precheck_status === 'passed' && !['under_review', 'approved'].includes(row.official_status) && <Button size="small" onClick={() => openCaseAction('submission', row)}>记录报备</Button>}
      {row.official_status === 'under_review' && user?.is_platform_admin && <Button size="small" type="primary" onClick={() => openCaseAction('decision', row)}>记录官方结果</Button>}
      <Button size="small" onClick={() => void showReadiness(row)}>检查门禁</Button>
    </Space> },
  ]

  const nextTargets: Record<string, string[]> = {
    draft: ['service_defined'], service_defined: ['authorization_pending'], authorization_pending: ['authorized', 'rejected'], authorized: ['mounted', 'unmounted'], mounted: ['unmounted'], unmounted: ['authorization_pending', 'mounted'], rejected: ['authorization_pending'],
  }

  return <section className="workspace-page">
    <div className="page-heading"><div><Typography.Text className="page-kicker">微信位置服务路线</Typography.Text><Typography.Title level={2}>准入与位置权限</Typography.Title><Typography.Paragraph>预审、官方报备、小程序和 POI 挂载分阶段办理；系统不会替代微信审批。</Typography.Paragraph></div><Button icon={<RefreshCw size={15} />} onClick={() => void refreshAll()}>刷新</Button></div>
    <Alert type="warning" showIcon message="官方边界" description="平台可以检查资料、提交申请和记录结果，但不能自行批准官方报备或位置权限。只有保存官方编号和结果凭证后，系统才允许进入真实挂载阶段。" />
    <Tabs items={[
      { key: 'cases', label: <span><ClipboardCheck size={15} /> 准入工单</span>, children: <Card className="workspace-table-card" variant="borderless" title="类目预审与官方报备" extra={<Button type="primary" icon={<Plus size={15} />} onClick={() => setCaseModal(true)}>新建准入工单</Button>}><WorkspaceState loading={cases.isPending} error={cases.error} empty={!cases.data?.length}><Table rowKey="id" dataSource={cases.data || []} columns={caseColumns} scroll={{ x: 1100 }} /></WorkspaceState></Card> },
      { key: 'apps', label: <span><Smartphone size={15} /> 商家小程序</span>, children: <Card className="workspace-table-card" variant="borderless" title="小程序、视频号与商家支付" extra={<Button type="primary" icon={<Plus size={15} />} onClick={() => setMiniModal({})}>登记小程序</Button>}><WorkspaceState loading={miniPrograms.isPending} error={miniPrograms.error} empty={!miniPrograms.data?.length}><Table rowKey="id" dataSource={miniPrograms.data || []} columns={[
        { title: '名称/AppID', render: (_: unknown, row: MiniProgramRecord) => <div><strong>{row.name}</strong><br /><Typography.Text type="secondary">{row.app_id || '待注册'}</Typography.Text></div> },
        { title: '主体', dataIndex: 'owner_subject' },
        { title: '小程序', dataIndex: 'status', render: (value: string) => <StatusTag value={value} /> },
        { title: '位置服务', dataIndex: 'location_service_status', render: (value: string) => <StatusTag value={value} /> },
        { title: '支付归属', render: (_: unknown, row: MiniProgramRecord) => row.payment_owner_verified ? <Tag color="green">已核验 {row.payment_merchant_id}</Tag> : <Tag color="red">未核验</Tag> },
        { title: '回调', dataIndex: 'callback_configured', render: (value: boolean) => value ? <Tag color="green">已配置</Tag> : <Tag>未配置</Tag> },
        { title: '操作', render: (_: unknown, row: MiniProgramRecord) => <Button size="small" onClick={() => { setMiniModal({ row }); miniForm.setFieldsValue(row) }}>配置</Button> },
      ]} /></WorkspaceState></Card> },
      { key: 'mounts', label: <span><Link2 size={15} /> 服务挂载</span>, children: <Card className="workspace-table-card" variant="borderless" title="微信位置相关服务" extra={<Button type="primary" icon={<Plus size={15} />} onClick={() => setMountModal(true)}>新增服务</Button>}><WorkspaceState loading={mounts.isPending} error={mounts.error} empty={!mounts.data?.length}><Table rowKey="id" dataSource={mounts.data || []} columns={[
        { title: '门店', dataIndex: 'store_id', render: (value: string) => storeNames.get(value) || value },
        { title: '服务', render: (_: unknown, row: PositionServiceRecord) => <div><strong>{row.service_name}</strong><br /><Typography.Text type="secondary">{row.service_type}</Typography.Text></div> },
        { title: '小程序', dataIndex: 'mini_program_id', render: (value: string) => appNames.get(value) || value },
        { title: '入口', dataIndex: 'entry_path' },
        { title: '状态', dataIndex: 'status', render: (value: string) => <StatusTag value={value} /> },
        { title: '操作', render: (_: unknown, row: PositionServiceRecord) => <Space wrap>{(nextTargets[row.status] || []).map(target => <Button key={target} size="small" danger={target === 'rejected' || target === 'unmounted'} onClick={() => setTransition({ row, target })}>{statusLabel[target] || target}</Button>)}</Space> },
      ]} scroll={{ x: 950 }} /></WorkspaceState></Card> },
    ]} />

    <Modal title="新建准入工单" open={caseModal} onCancel={() => setCaseModal(false)} footer={null}><Form form={caseForm} layout="vertical" initialValues={{ route: 'wechat_location_miniprogram', category_code: 'beauty_hair', category_name: '美发', subject_type: 'individual_business', region_code: '411102' }} onFinish={values => createCase.mutate(values)}>
      <Form.Item name="store_id" label="门店" rules={[{ required: true }]}><Select options={(stores.data || []).map(item => ({ value: item.id, label: item.name }))} /></Form.Item>
      <Form.Item name="route" label="接入路线"><Select options={[{ value: 'wechat_location_miniprogram', label: '微信位置＋独立小程序' }, { value: 'wechat_shop_local_life', label: '微信小店本地生活（仅保留兼容）' }]} /></Form.Item>
      <Form.Item name="category_name" label="经营类目" rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="category_code" label="内部类目编码" rules={[{ required: true }]}><Input /></Form.Item>
      <Form.Item name="subject_type" label="主体类型"><Select options={[{ value: 'individual_business', label: '个体工商户' }, { value: 'enterprise', label: '企业' }]} /></Form.Item><Form.Item name="region_code" label="行政区划代码"><Input /></Form.Item>
      {createCase.isError && <p className="form-error">{createCase.error.message}</p>}<Button block type="primary" htmlType="submit" loading={createCase.isPending}>创建</Button>
    </Form></Modal>

    <Modal title={caseAction?.mode === 'precheck' ? '填写类目与资料预审' : caseAction?.mode === 'submission' ? '记录官方报备' : '记录官方审核结果'} open={Boolean(caseAction)} onCancel={() => { setCaseAction(null); actionForm.resetFields() }} footer={null}><Form form={actionForm} layout="vertical" initialValues={{ checked: [], decision: 'approved' }} onFinish={values => mutateCase.mutate(values)}>
      {caseAction?.mode === 'precheck' && <><Form.Item name="checked" label="逐项核验"><Checkbox.Group style={{ display: 'grid', gap: 10 }} options={Object.entries(requirementLabels).map(([value, label]) => ({ value, label }))} /></Form.Item><Form.Item name="rule_source_reference" label="当前规则来源/客服工单" rules={[{ required: true }]}><Input placeholder="例如：微信客服工单号或受控截图路径" /></Form.Item></>}
      {caseAction?.mode === 'submission' && <Form.Item name="official_reference" label="官方申请/报备编号" rules={[{ required: true }]}><Input /></Form.Item>}
      {caseAction?.mode === 'decision' && <><Form.Item name="decision" label="官方结果"><Select options={[{ value: 'approved', label: '已通过' }, { value: 'needs_more_info', label: '需补件' }, { value: 'paused', label: '暂停受理' }, { value: 'rejected', label: '未通过' }]} /></Form.Item><Form.Item name="message" label="官方说明"><Input.TextArea /></Form.Item></>}
      <Form.Item name="evidence_reference" label="凭证存放位置" rules={[{ required: true }]}><Input placeholder="受控文件路径、工单链接或不可变存证编号" /></Form.Item>
      {mutateCase.isError && <p className="form-error">{mutateCase.error.message}</p>}<Button block type="primary" htmlType="submit" loading={mutateCase.isPending}>保存</Button>
    </Form></Modal>

    <Modal title={miniModal?.row ? '配置商家小程序' : '登记商家小程序'} open={Boolean(miniModal)} onCancel={() => { setMiniModal(null); miniForm.resetFields() }} footer={null}><Form form={miniForm} layout="vertical" initialValues={{ ownership_mode: 'merchant_owned', status: 'draft', location_service_status: 'not_configured', payment_owner_verified: false, callback_configured: false }} onFinish={values => mutateMini.mutate(values)}>
      <Form.Item name="connection_id" label="独立小程序交易连接" rules={[{ required: true }]}><Select options={((connections.data || []) as Array<{ id: string; capability: string; app_id?: string | null }>).filter(item => item.capability === 'mini_program_commerce').map(item => ({ value: item.id, label: `${item.app_id || '待填 AppID'} · ${item.id}` }))} /></Form.Item>
      <Form.Item name="name" label="小程序名称" rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="app_id" label="AppID"><Input /></Form.Item><Form.Item name="owner_subject" label="所有主体" rules={[{ required: true }]}><Input disabled={Boolean(miniModal?.row)} /></Form.Item>
      {!miniModal?.row && <Form.Item name="ownership_mode" label="所有权"><Select options={[{ value: 'merchant_owned', label: '商家自有（推荐）' }, { value: 'platform_owned', label: '平台自有' }]} /></Form.Item>}
      <Form.Item name="authorization_reference" label="商家授权凭证"><Input /></Form.Item><Form.Item name="payment_merchant_id" label="微信支付商户号"><Input /></Form.Item><Form.Item name="video_channel_id" label="视频号标识"><Input /></Form.Item>
      <Space><Form.Item name="payment_owner_verified" valuePropName="checked"><Checkbox>商户号归属已核验</Checkbox></Form.Item><Form.Item name="callback_configured" valuePropName="checked"><Checkbox>回调已配置</Checkbox></Form.Item></Space>
      {miniModal?.row && <><Form.Item name="status" label="小程序状态"><Select options={['draft', 'authorized', 'active', 'suspended'].map(value => ({ value, label: statusLabel[value] || value }))} /></Form.Item><Form.Item name="location_service_status" label="位置服务状态"><Select options={['not_configured', 'configured', 'authorization_pending', 'authorized'].map(value => ({ value, label: statusLabel[value] || value }))} /></Form.Item></>}
      {mutateMini.isError && <p className="form-error">{mutateMini.error.message}</p>}<Button block type="primary" htmlType="submit" loading={mutateMini.isPending}>保存</Button>
    </Form></Modal>

    <Modal title="新增微信位置服务" open={mountModal} onCancel={() => setMountModal(false)} footer={null}><Form form={mountForm} layout="vertical" initialValues={{ service_type: 'group_buying', service_name: '到店团购', entry_path: 'pages/store/index' }} onFinish={values => createMount.mutate(values)}>
      <Form.Item name="onboarding_case_id" label="已通过预审的工单" rules={[{ required: true }]}><Select options={(cases.data || []).filter(item => item.precheck_status === 'passed').map(item => ({ value: item.id, label: `${storeNames.get(item.store_id) || item.store_id} · ${item.category_name}` }))} onChange={value => { const selected = cases.data?.find(item => item.id === value); if (selected) mountForm.setFieldValue('store_id', selected.store_id) }} /></Form.Item>
      <Form.Item name="store_id" label="门店" rules={[{ required: true }]}><Select options={(stores.data || []).map(item => ({ value: item.id, label: item.name }))} /></Form.Item><Form.Item name="service_poi_id" label="已审核服务 POI" rules={[{ required: true }]}><Select options={(pois.data || []).map(item => ({ value: item.id, label: `${item.name} · ${item.external_poi_id}` }))} /></Form.Item><Form.Item name="mini_program_id" label="商家小程序" rules={[{ required: true }]}><Select options={(miniPrograms.data || []).map(item => ({ value: item.id, label: `${item.name} · ${item.app_id || '待注册'}` }))} /></Form.Item>
      <Form.Item name="service_type" label="服务类型"><Select options={[{ value: 'group_buying', label: '到店团购' }, { value: 'reservation', label: '在线预约' }, { value: 'preorder', label: '预点单' }, { value: 'pickup', label: '到店自取' }, { value: 'delivery', label: '外卖' }]} /></Form.Item><Form.Item name="service_name" label="位置页展示名称" rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="entry_path" label="小程序内部页面路径" rules={[{ required: true }]}><Input /></Form.Item>
      {createMount.isError && <p className="form-error">{createMount.error.message}</p>}<Button block type="primary" htmlType="submit" loading={createMount.isPending}>创建草稿</Button>
    </Form></Modal>

    <Modal title={`位置服务：${transition ? statusLabel[transition.target] || transition.target : ''}`} open={Boolean(transition)} onCancel={() => { setTransition(null); transitionForm.resetFields() }} footer={null}><Form form={transitionForm} layout="vertical" onFinish={values => transitionMount.mutate(values)}><Form.Item name="official_reference" label="官方授权/挂载编号"><Input /></Form.Item><Form.Item name="evidence_reference" label="官方结果凭证"><Input /></Form.Item><Form.Item name="message" label="备注或驳回原因"><Input.TextArea /></Form.Item>{transitionMount.isError && <p className="form-error">{transitionMount.error.message}</p>}<Button block type="primary" htmlType="submit" loading={transitionMount.isPending}>确认状态变更</Button></Form></Modal>
  </section>
}
