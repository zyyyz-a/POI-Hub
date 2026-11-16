import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Card, Checkbox, Descriptions, Form, Image as PhotoPreview, Input, Modal, QRCode, Select, Space, Steps, Table, Tag, Typography } from 'antd'
import { Plus, RefreshCw } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { api, type MerchantApplymentRecord } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { prepareApplymentPhoto, WECHAT_IMAGE_BYTES } from '../common/applymentPhoto'
import { askAboutField } from '../common/assistant'
import { normalizeSettlementAccount } from '../common/settlementAccount'
import { WorkspaceState } from './WorkspaceStates'
import './workspace.css'
import './merchant-applyments.css'

const STATE_LABELS: Record<string, string> = {
  draft: '资料草稿', submitting: '正在提交', submission_unknown: '提交结果待确认',
  reviewing: '微信审核中', rejected: '待修改补件', needs_edit: '待完善资料', needs_confirmation: '经营者待确认／验证',
  needs_signature: '经营者待签约', opening: '权限开通中', finished: '入驻完成',
  canceled: '申请已取消', unknown: '状态待核对',
}
const ERROR_LABELS: Record<string, string> = {
  NO_AUTH: '微信尚未允许本账号执行这项操作，请核实服务商进件权限。',
  SIGN_ERROR: '微信未通过请求签名校验，请联系平台管理员核对证书。',
  PARAM_ERROR: '微信未接受申请参数，请核对资料及官方行业结算规则。',
  APPLYMENT_NOTEXIST: '微信暂未查到申请单。不要重复新建申请，请稍后再次查询。',
  wechat_network_error: '与微信通信中断。若申请可能已发出，请先查询原申请结果。',
  wechat_response_unverified: '微信回复未通过验签，暂不信任其结果，请联系管理员。',
  PROCESSING: '微信已有进行中的申请，请查询原申请进度。',
  wechat_application_mismatch: '微信返回的申请单与当前门店不匹配，已停止关联，请联系管理员。',
}
const REQUIRED_IMAGES: Array<[string, string]> = [
  ['license', '营业执照'], ['id_front', '身份证人像面'], ['id_back', '身份证国徽面'],
  ['store_front', '门头照片'], ['store_inside', '店内照片'], ['mini_program_1', '小程序服务页面截图'],
]
const OPTIONAL_IMAGES: Array<[string, string]> = [
  ...Array.from({ length: 4 }, (_, i): [string, string] => [`mini_program_${i + 2}`, `小程序截图 ${i + 2}`]),
  ...Array.from({ length: 5 }, (_, i): [string, string] => [`qualification_${i + 1}`, `行业特殊资质 ${i + 1}`]),
  ...Array.from({ length: 5 }, (_, i): [string, string] => [`supplement_${i + 1}`, `补充材料 ${i + 1}`]),
]
const PHOTO_HINTS: Record<string, string> = {
  license: '有效营业执照原件照片，文字和四角清晰完整。',
  id_front: '经营者本人身份证人像面，文字和边角完整。',
  id_back: '经营者本人身份证国徽面，签发机关和有效期清晰。',
  store_front: '拍这家实际门店的正门全景，门店招牌、门框完整清晰，不是平台公司的照片。',
  store_inside: '拍这家门店内部真实经营环境，能看出实际提供的服务。',
  mini_program_1: '使用统一平台小程序中展示本店商品/服务的页面；未上线时可提供真实服务页面设计稿。不是要求商家另建小程序，也不要上传报错页。',
}

function TextField({ name, label, hint, secret = false }: { name: string; label: string; hint?: string; secret?: boolean }) {
  const { user } = useAuth()
  return <Form.Item name={name} label={label} normalize={name === 'account_number' ? normalizeSettlementAccount : undefined} extra={<>{hint}{name === 'account_number' && '自动去除账号中的空格，不改动数字；已有旧格式请重新保存草稿。必须填写完整账号，不能只填尾号。'}{user?.is_platform_admin && <Button type="link" size="small" onClick={() => askAboutField(name, label)}>不会填？</Button>}</>}>
    {secret ? <Input.Password autoComplete="off" /> : <Input autoComplete="off" />}
  </Form.Item>
}

export function MerchantApplymentsPage() {
  const { tenant, user, membership } = useAuth()
  const allowed = Boolean(user?.is_platform_admin || membership?.role === 'tenant_admin')
  if (!allowed) return <Alert type="warning" message="只有平台管理员或商户管理员可以查看入驻资料。" />
  return <ApplymentWorkspace key={tenant?.id || 'none'} />
}

function ApplymentWorkspace() {
  const { tenant } = useAuth()
  const client = useQueryClient()
  const [selectedId, setSelectedId] = useState('')
  const [creating, setCreating] = useState(false)
  const [createForm] = Form.useForm()
  const applications = useQuery({ queryKey: ['merchant-applyments', tenant?.id], queryFn: api.merchantApplyments, enabled: Boolean(tenant) })
  const stores = useQuery({ queryKey: ['stores', tenant?.id], queryFn: api.stores, enabled: Boolean(tenant) })
  const connections = useQuery({ queryKey: ['connections', tenant?.id], queryFn: api.connections, enabled: Boolean(tenant) })
  const capabilities = useQuery({ queryKey: ['applyment-capabilities', tenant?.id], queryFn: api.applymentCapabilities, enabled: Boolean(tenant) })
  const refresh = () => client.invalidateQueries({ queryKey: ['merchant-applyments', tenant?.id] })
  const create = useMutation({
    mutationFn: (values: { store_id: string; connection_id: string }) => api.createMerchantApplyment(values.store_id, values.connection_id),
    onSuccess: async row => { setCreating(false); createForm.resetFields(); setSelectedId(row.id); await refresh() },
  })
  const liveConnections = ((connections.data || []) as Array<{ id: string; capability: string; mode: string; app_id?: string; merchant_id?: string }>).filter(row => row.capability === 'mini_program_commerce' && row.mode === 'live')
  const existingStores = new Set((applications.data || []).map(row => row.store_id))
  return <section className="workspace-page">
    <div className="page-heading"><div><Typography.Text className="page-kicker">微信支付服务商</Typography.Text><Typography.Title level={2}>子商户入驻</Typography.Title><Typography.Paragraph>适用于个体工商户，由营业执照经营者本人担任管理员。先存草稿，确认后才向微信提交。</Typography.Paragraph></div><Space><Button icon={<RefreshCw size={15} />} onClick={() => void refresh()}>刷新列表</Button><Button type="primary" icon={<Plus size={15} />} onClick={() => setCreating(true)}>新建入驻申请</Button></Space></div>
    {capabilities.isError && <Alert type="error" showIcon message="无法读取提交开关，真实提交保持不可用，请稍后重试。" />}
    {capabilities.data && !capabilities.data.real_submission_enabled && <Alert type="warning" showIcon message="真实进件提交暂未开启" description="可以创建草稿、填写资料和保存照片。管理员核对进件权限并开启服务端提交开关后，才可明确确认并提交微信。" />}
    <Card className="workspace-table-card" variant="borderless">
      <WorkspaceState loading={applications.isPending} error={applications.error} empty={!applications.data?.length}>
        <Table<MerchantApplymentRecord> rowKey="id" scroll={{ x: 760 }} dataSource={applications.data || []} columns={[
          { title: '门店', render: (_, row) => stores.data?.find(store => store.id === row.store_id)?.name || row.store_id },
          { title: '进度', dataIndex: 'state', render: (state: string) => <Tag color={state === 'finished' ? 'green' : state === 'rejected' ? 'red' : 'blue'}>{STATE_LABELS[state] || '状态待核对'}</Tag> },
          { title: '微信申请单号', dataIndex: 'applyment_id', render: (value: string | null) => value || '尚未提交' },
          { title: '子商户号', dataIndex: 'sub_mchid', render: (value: string | null) => value || '入驻完成后取得' },
          { title: '操作', render: (_, row) => <Button onClick={() => setSelectedId(row.id)}>{row.editable ? '继续填写' : '查看进度'}</Button> },
        ]} />
      </WorkspaceState>
    </Card>
    {selectedId && <ApplymentEditor key={selectedId} id={selectedId} enabled={Boolean(capabilities.data?.real_submission_enabled)} imageLimit={capabilities.data?.max_image_bytes || WECHAT_IMAGE_BYTES} onChange={refresh} />}
    <Modal title="新建子商户入驻草稿" open={creating} onCancel={() => setCreating(false)} footer={null}>
      <Form form={createForm} layout="vertical" onFinish={values => create.mutate(values)}>
        <Form.Item name="store_id" label="服务门店" rules={[{ required: true, message: '请选择门店' }]}><Select options={(stores.data || []).filter(row => !existingStores.has(row.id)).map(row => ({ value: row.id, label: row.name }))} /></Form.Item>
        <Form.Item name="connection_id" label="平台真实支付连接" rules={[{ required: true, message: '请选择真实支付连接' }]}><Select options={liveConnections.map(row => ({ value: row.id, label: `${row.app_id || '未填AppID'} · 服务商 ${row.merchant_id || '未填商户号'}` }))} /></Form.Item>
        {!liveConnections.length && <Alert type="warning" message="请先到“微信连接”配置本商户的真实小程序交易与支付连接。" />}
        <p>固定主体：个体工商户；管理员：执照经营者；首版证件：中国大陆居民身份证。</p>
        {(stores.error || connections.error) && <Alert type="error" message="门店或支付连接读取失败，请关闭后刷新重试。" />}
        {create.isError && <p className="form-error">{create.error.message}</p>}
        <Button block type="primary" htmlType="submit" loading={create.isPending}>创建草稿（不提交微信）</Button>
      </Form>
    </Modal>
  </section>
}

function ApplymentEditor({ id, enabled, imageLimit, onChange }: { id: string; enabled: boolean; imageLimit: number; onChange: () => Promise<unknown> }) {
  const [form] = Form.useForm()
  const [step, setStep] = useState(0)
  const [row, setRow] = useState<MerchantApplymentRecord | null>(null)
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [authorized, setAuthorized] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [photoPreview, setPhotoPreview] = useState<{ kind: string; url: string; compressed: boolean; converted: boolean } | null>(null)
  const [photoError, setPhotoError] = useState<{ kind: string; message: string } | null>(null)
  const mounted = useRef(true)
  const photoUrls = useRef(new Set<string>())
  useEffect(() => {
    mounted.current = true
    const urls = photoUrls.current
    return () => { mounted.current = false; urls.forEach(url => URL.revokeObjectURL(url)); urls.clear() }
  }, [])
  const detail = useQuery({ queryKey: ['merchant-applyment', id], queryFn: () => api.merchantApplyment(id), retry: false, refetchOnWindowFocus: false, gcTime: 0 })
  useEffect(() => {
    if (detail.data) { setRow(detail.data); form.setFieldsValue(detail.data.fields || {}); setDirty(false); setAuthorized(false) }
  }, [detail.data, form])
  useEffect(() => {
    if (!dirty) return
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])
  async function perform(action: () => Promise<MerchantApplymentRecord>, message: string, resetFields = false) {
    if (busy) return
    setBusy(true); setError(''); setNotice(''); setAuthorized(false)
    try {
      const next = await action()
      setRow(next)
      if (resetFields) { form.setFieldsValue(next.fields || {}); setDirty(false); setAuthorized(false) }
      setNotice(message); await onChange()
    } catch (reason) { setError(reason instanceof Error ? reason.message : '操作失败，请稍后重试') }
    finally { setBusy(false) }
  }
  function upload(kind: string, file?: File) {
    if (!file || !row) return
    setPhotoError(null)
    void perform(async () => {
      try {
        const prepared = await prepareApplymentPhoto(file, imageLimit)
        const next = await api.uploadApplymentAttachment(id, row.version, kind, prepared.file)
        if (mounted.current) {
          photoUrls.current.forEach(url => URL.revokeObjectURL(url)); photoUrls.current.clear()
          const url = URL.createObjectURL(prepared.file)
          photoUrls.current.add(url)
          setPhotoPreview({ kind, url, compressed: prepared.compressed, converted: prepared.converted })
        }
        return next
      } catch (reason) {
        if (mounted.current) setPhotoError({ kind, message: reason instanceof Error ? reason.message : '照片上传失败，请重新选择。' })
        throw reason
      }
    }, '照片已加密保存，尚未发送微信。请点击预览确认文字清晰，原文件未修改。')
  }
  function imageInput(kind: string, label: string) {
    const present = row?.attachments.some(item => item.kind === kind)
    return <div className="applyment-upload" key={kind}><div><strong>{label}</strong><Tag color={present ? 'green' : 'default'}>{present ? '已保存' : '未上传'}</Tag>{PHOTO_HINTS[kind] && <p className="applyment-photo-hint">{PHOTO_HINTS[kind]}</p>}</div><Space wrap>
      <label className="applyment-file-label">{present ? '更换照片' : '选择照片'}<input aria-label={`上传${label}`} type="file" accept="image/jpeg,image/png,image/bmp,image/webp,image/avif,image/heic,image/heif,.jpg,.jpeg,.png,.bmp,.webp,.avif,.heic,.heif" disabled={busy || !row?.editable} onChange={event => { upload(kind, event.target.files?.[0]); event.target.value = '' }} /></label>
      {present && <Button size="small" danger disabled={busy || !row?.editable} onClick={() => row && void perform(() => api.removeApplymentAttachment(id, row.version, kind), '已移除本地保存的照片。')}>移除</Button>}
    </Space>{photoError?.kind === kind && <Alert type="error" showIcon message={photoError.message} />}{photoPreview?.kind === kind && present && <div><PhotoPreview src={photoPreview.url} width={100} height={74} style={{ objectFit: 'contain' }} alt={`${label}上传预览`} /><p>{photoPreview.compressed ? '图片已自动处理至5MB内，请预览确认清晰度' : photoPreview.converted ? '格式已自动兼容处理，请预览确认清晰度' : '点击预览检查照片'}</p></div>}</div>
  }
  const locked = !row?.editable || busy
  return <Card title="入驻申请详情" className="workspace-table-card applyment-editor" variant="borderless">
    <WorkspaceState loading={detail.isPending} error={detail.error} empty={false}>
      {row && <>
        <Space wrap><Tag>{STATE_LABELS[row.state] || '状态待核对'}</Tag><span>服务商号：{row.sp_mchid}</span><span>申请单号：{row.applyment_id || '尚未取得'}</span></Space>
        {row.last_error_code && <Alert className="workspace-alert" type="error" showIcon message={ERROR_LABELS[row.last_error_code] || '本次操作未完成，请核对配置或联系管理员。'} description={<span>错误代码：{row.last_error_code}{row.last_request_id ? `；查询凭据：${row.last_request_id}` : ''}</span>} />}
        {row.state === 'submission_unknown' && <Alert className="workspace-alert" type="warning" message="可能已向微信提交，暂时禁止再次提交。请查询原申请进度；不要新建申请。" />}
        {row.audit_details.length > 0 && <Alert className="workspace-alert" type="warning" message="微信补件意见" description={<ul>{row.audit_details.map((item, i) => <li key={i}>{item}</li>)}</ul>} />}
        {row.sign_url && <div className="applyment-sign"><div><Typography.Title level={4}>请执照经营者本人扫码</Typography.Title><p>用于微信官方确认、账户验证或签约。平台工作人员不要代替经营者操作。</p><a href={row.sign_url} target="_blank" rel="noopener noreferrer">打开微信官方办理页面</a></div><QRCode type="svg" value={row.sign_url} /></div>}
        {row.sub_mchid && <Alert className="workspace-alert" type="success" message={`微信已确认入驻完成，子商户号：${row.sub_mchid}`} description="可关联为待启用支付档案；不会自动启用交易，还需核对小程序关联和支付授权。" />}
        <Space wrap style={{ marginTop: 16, marginBottom: 24 }}>
          <Button disabled={busy || !row.applyment_id && row.state === 'draft' || dirty} onClick={() => void perform(() => api.syncMerchantApplyment(id, row.version), '已查询微信进度。', true)}>查询微信进度</Button>
          {row.state === 'finished' && <Button disabled={busy} onClick={async () => { setBusy(true); setError(''); try { const result = await api.linkApplymentPayment(id, row.version); setNotice(result.message); await detail.refetch(); await onChange() } catch (reason) { setError(reason instanceof Error ? reason.message : '关联失败') } finally { setBusy(false) } }}>关联待启用支付档案</Button>}
        </Space>
        <Steps current={step} onChange={setStep} size="small" items={['执照信息', '经营者信息', '门店与结算', '核对提交'].map(title => ({ title }))} />
        <Form form={form} layout="vertical" initialValues={{ bank_account_type: 'personal', settlement_rule_confirmed: false }} disabled={locked} onValuesChange={() => { setDirty(true); setAuthorized(false); setNotice('') }}>
          <div hidden={step !== 0} className="applyment-step"><Typography.Paragraph>按执照原文填写。无字号个体户名称按微信要求填写“个体户＋经营者姓名”。</Typography.Paragraph>
            <div className="applyment-grid"><TextField name="merchant_name" label="营业执照名称" /><TextField name="license_number" label="注册号／统一社会信用代码" /><TextField name="license_address" label="执照注册地址" /><TextField name="license_period_begin" label="执照有效期开始日期（选填）" hint="YYYY-MM-DD；起止日期一起填写或一起留空" /><TextField name="license_period_end" label="执照有效期结束日期（选填）" hint="YYYY-MM-DD 或 长期" /></div>{imageInput('license', '营业执照')}
          </div>
          <div hidden={step !== 1} className="applyment-step"><Typography.Paragraph>管理员固定为执照经营者本人，不填写平台工作人员的信息。</Typography.Paragraph><div className="applyment-grid"><TextField name="owner_name" label="经营者姓名" /><TextField name="id_number" label="经营者身份证号码" secret /><TextField name="id_period_begin" label="身份证有效期开始日期" hint="YYYY-MM-DD" /><TextField name="id_period_end" label="身份证有效期结束日期" hint="YYYY-MM-DD 或 长期" /><TextField name="mobile_phone" label="经营者手机" secret /><TextField name="contact_email" label="经营者联系邮箱" /></div>{imageInput('id_front', '身份证人像面')}{imageInput('id_back', '身份证国徽面')}</div>
          <div hidden={step !== 2} className="applyment-step"><div className="applyment-grid"><TextField name="store_name" label="门店名称" /><TextField name="store_address" label="实际经营地址" /><TextField name="store_area_code" label="经营地址行政区划编码" hint="6位行政区划编码，非地图POI编号" /><TextField name="merchant_shortname" label="支付账单商户简称" /><TextField name="service_phone" label="门店客服电话" /><Form.Item name="bank_account_type" label="结算账户类型"><Select options={[{ value: 'personal', label: '经营者本人银行卡' }, { value: 'corporate', label: '个体户对公账户' }]} /></Form.Item><TextField name="account_bank" label="开户银行" hint="使用微信支持的银行名称；不自动选择银行" /><TextField name="bank_name" label="开户支行完整名称" /><TextField name="bank_branch_id" label="开户支行联行号（选填）" /><TextField name="account_number" label="结算银行卡号／对公账号" secret /><TextField name="settlement_id" label="微信结算规则编号" hint="由平台管理员按当前官方规则核对，不自动猜测费率" /><TextField name="qualification_type" label="微信行业名称" hint="门店实际经营行业，不是平台的软件开发类目" /></div>
            <Typography.Paragraph>个人银行卡开户人自动使用经营者姓名；对公账户开户名使用执照名称。<a href="https://pay.wechatpay.cn/doc/v3/partner/4012719997" target="_blank" rel="noopener noreferrer">查看微信官方填写规则及对照表</a></Typography.Paragraph>
            <Form.Item name="settlement_rule_confirmed" valuePropName="checked"><Checkbox>已核对官方结算规则、行业名称及所需特殊资质</Checkbox></Form.Item>
            <Alert type="info" showIcon message="所有门店统一使用平台小程序，无需商家另建" description={`本申请使用平台AppID：${row.platform_app_id}。统一的是小程序入口；门头、店内照片及服务页面仍需真实对应这家门店。`} />
            {REQUIRED_IMAGES.slice(3).map(([kind, label]) => imageInput(kind, label))}
            <details><summary>更多小程序截图、行业资质与补充材料（按实际需要上传）</summary>{OPTIONAL_IMAGES.map(([kind, label]) => imageInput(kind, label))}</details>
            <Form.Item name="addition_message" label="补充说明（选填）"><Input.TextArea maxLength={512} rows={3} /></Form.Item>
          </div>
          <div hidden={step !== 3} className="applyment-step"><Typography.Paragraph>提交范围：个体工商户、经营者本人、中国大陆居民身份证，经营场景为实际门店＋统一平台小程序，无需门店单独开发小程序。支持JPG、PNG、BMP及浏览器能解码的WebP/AVIF照片；原图可达20MB，系统按真实图片内容识别格式，需要时在浏览器本地转换、压缩至5MB以内。HEIC/HEIF若无法读取，请在手机中导出JPG再上传。请预览确认清晰度；原文件不会修改。</Typography.Paragraph>
            <Descriptions size="small" column={1} bordered items={[
              { key: 'merchant', label: '已保存执照名称', children: String(row.fields?.merchant_name || '未填写') },
              { key: 'store', label: '已保存服务门店', children: String(row.fields?.store_name || '未填写') },
              { key: 'account', label: '已保存结算账户', children: row.fields?.account_number ? `尾号 ${String(row.fields.account_number).slice(-4)}` : '未填写' },
              { key: 'app', label: '使用的平台小程序', children: row.platform_app_id },
            ]} />
            {dirty && <Alert type="warning" message="有未保存修改，请先保存草稿，再核对缺项并提交。" />}
            {row.issues.length > 0 ? <Alert type="warning" message={`已保存资料还需补充 ${row.issues.length} 项`} description={<ul>{row.issues.map(item => <li key={item}>{item}</li>)}</ul>} /> : <Alert type="success" message="本地必填检查通过，最终以微信审核为准。" />}
            <Typography.Paragraph style={{ marginTop: 16 }}>身份证、银行卡、照片和联系方式会发送给微信支付用于商户开户审核。保存草稿不会发送，提交需要另行确认。</Typography.Paragraph>
          </div>
        </Form>
        {error && <Alert className="workspace-alert" type="error" showIcon message={error} />}
        {notice && <Alert className="workspace-alert" type="info" showIcon message={notice} />}
        <div className="applyment-actions"><Space wrap><Button disabled={step === 0 || busy} onClick={() => setStep(step - 1)}>上一步</Button>{step < 3 && <Button disabled={busy} onClick={() => setStep(step + 1)}>下一步</Button>}<Button type="primary" disabled={locked} loading={busy} onClick={() => void perform(() => api.saveMerchantApplyment(id, row.version, form.getFieldsValue(true)), '草稿已加密保存，未提交微信。', true)}>保存草稿</Button></Space>
          {step === 3 && row.editable && <Space direction="vertical"><Checkbox checked={authorized} disabled={dirty || busy} onChange={event => setAuthorized(event.target.checked)}>经营者已知情并授权平台代办，本次资料真实准确</Checkbox><Button danger type="primary" disabled={!enabled || dirty || !authorized || row.issues.length > 0 || busy} onClick={() => setConfirming(true)}>确认资料，提交微信审核</Button></Space>}
        </div>
        <Modal title="确认向微信提交真实入驻申请？" open={confirming} onCancel={() => setConfirming(false)} okText="确认授权并提交" cancelText="返回核对" okButtonProps={{ danger: true, disabled: !authorized || dirty || !enabled || busy }} onOk={async () => { setConfirming(false); await perform(() => api.submitMerchantApplyment(id, row.version), '提交结果已更新，请查看进度和错误提示。', true) }}>
          <p>将发送已保存的营业执照、经营者证件、门店照片、联系方式及结算账户，申请在服务商 {row.sp_mchid} 下入驻。</p><p>这不是模拟操作。提交后由微信审核，后续确认和签约必须由经营者本人完成。本操作不发起扣款。</p>
        </Modal>
      </>}
    </WorkspaceState>
  </Card>
}
