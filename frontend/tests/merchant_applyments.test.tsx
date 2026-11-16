import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthContext, type AuthContextValue } from '../src/auth/AuthProvider'
import { setCsrfToken } from '../src/api/client'
import { MerchantApplymentsPage } from '../src/pages/MerchantApplymentsPage'

const auth: AuthContextValue = {
  status: 'authenticated',
  user: { id: 'u1', email: 'admin@example.com', display_name: 'Admin', status: 'active', is_platform_admin: false },
  tenant: { id: 't1', name: 'Demo Tenant', slug: 'demo', status: 'active' },
  membership: { id: 'm1', tenant_id: 't1', tenant_name: 'Demo Tenant', user_id: 'u1', email: 'admin@example.com', display_name: 'Admin', role: 'tenant_admin', status: 'active' },
  tenants: [], csrfToken: 'csrf', login: vi.fn(), logout: vi.fn(), selectTenant: vi.fn(), refresh: vi.fn(),
}

const initial = {
  id: 'a1', store_id: 's1', connection_id: 'c1', business_code: 'POI_test_only',
  sp_mchid: '1900000000', platform_app_id: 'wx0000000000000000', state: 'draft',
  applyment_id: null, sub_mchid: null, last_error_code: null, last_request_id: null,
  version: 1, updated_at: '2026-10-19T00:00:00Z', editable: true,
  fields: { merchant_name: '测试执照', store_name: '测试门店', account_number: '622200001234' },
  attachments: [], issues: [] as string[], audit_details: [], sign_url: null as string | null,
}

function json(data: unknown) {
  return Promise.resolve(new Response(JSON.stringify(data), { status: 200, headers: { 'Content-Type': 'application/json' } }))
}

function mockApi(enabled = false, changes: Partial<typeof initial> = {}) {
  let row = { ...initial, ...changes }
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const path = String(input)
    if (path.endsWith('/capabilities')) return json({ real_submission_enabled: enabled })
    if (path.endsWith('/submit')) { row = { ...row, state: 'reviewing', editable: false }; return json(row) }
    if (path.endsWith('/sync')) { row = { ...row, state: 'needs_signature', sign_url: 'https://pay.weixin.qq.com/apply?id=test' }; return json(row) }
    if (path.endsWith('/a1') && init?.method === 'PUT') {
      row = { ...row, ...JSON.parse(String(init.body)), version: row.version + 1 }
      return json(row)
    }
    if (path.endsWith('/a1')) return json(row)
    if (path.endsWith('/merchant-applyments')) return json([row])
    if (path.endsWith('/stores')) return json([{ id: 's1', name: '测试门店' }])
    if (path.endsWith('/connections')) return json([{ id: 'c1', capability: 'mini_program_commerce', mode: 'live', app_id: row.platform_app_id, merchant_id: row.sp_mchid }])
    if (path.includes('/attachments/')) { row = { ...row, attachments: [{ kind: 'license', size_bytes: (init?.body as File).size }] as typeof row.attachments, version: row.version + 1 }; return json(row) }
    throw new Error(`Unexpected test request: ${path}`)
  })
}

function renderPage(context = auth) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><AuthContext.Provider value={context}><MemoryRouter><MerchantApplymentsPage /></MemoryRouter></AuthContext.Provider></QueryClientProvider>)
}

async function openEditor(label = '继续填写') {
  fireEvent.click(await screen.findByRole('button', { name: label }))
  await screen.findByLabelText('营业执照名称')
}

function review() {
  for (let i = 0; i < 3; i++) fireEvent.click(screen.getByRole('button', { name: '下一步' }))
}

describe('visual submerchant onboarding', () => {
  afterEach(() => { setCsrfToken(undefined); vi.restoreAllMocks(); vi.unstubAllGlobals() })

  it('does not fetch private data for an operator', () => {
    const fetchMock = mockApi()
    renderPage({ ...auth, membership: { ...auth.membership!, role: 'operator' } })
    expect(screen.getByText('只有平台管理员或商户管理员可以查看入驻资料。')).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('saves a draft without submitting to WeChat and respects the server switch', async () => {
    const fetchMock = mockApi()
    setCsrfToken('csrf')
    renderPage()
    await openEditor()
    fireEvent.change(screen.getByLabelText('营业执照名称'), { target: { value: '修改后的测试执照' } })
    fireEvent.click(screen.getByRole('button', { name: '保存草稿' }))
    await screen.findByText('草稿已加密保存，未提交微信。')
    const save = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')
    expect(JSON.parse(String(save?.[1]?.body))).toMatchObject({ fields: { merchant_name: '修改后的测试执照' } })
    review()
    expect(screen.getByRole('button', { name: '确认资料，提交微信审核' })).toBeDisabled()
    expect(fetchMock.mock.calls.some(([path]) => String(path).endsWith('/submit'))).toBe(false)
  })

  it('requires saved complete fields, merchant consent and a second confirmation', async () => {
    const fetchMock = mockApi(true)
    renderPage()
    await openEditor()
    review()
    const submit = screen.getByRole('button', { name: '确认资料，提交微信审核' })
    expect(submit).toBeDisabled()
    fireEvent.click(screen.getByRole('checkbox', { name: '经营者已知情并授权平台代办，本次资料真实准确' }))
    expect(submit).toBeEnabled()
    fireEvent.click(submit)
    await screen.findByText('确认向微信提交真实入驻申请？')
    expect(fetchMock.mock.calls.some(([path]) => String(path).endsWith('/submit'))).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: '确认授权并提交' }))
    await waitFor(() => expect(fetchMock.mock.calls.filter(([path]) => String(path).endsWith('/submit'))).toHaveLength(1))
    const call = fetchMock.mock.calls.find(([path]) => String(path).endsWith('/submit'))
    expect(JSON.parse(String(call?.[1]?.body))).toEqual({ version: 1, merchant_authorized: true, confirm_real_submission: true })
  })

  it('blocks incomplete saved applications even with consent', async () => {
    const fetchMock = mockApi(true, { issues: ['请上传营业执照照片'] })
    renderPage()
    await openEditor()
    review()
    expect(screen.getByText('请上传营业执照照片')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('checkbox', { name: '经营者已知情并授权平台代办，本次资料真实准确' }))
    expect(screen.getByRole('button', { name: '确认资料，提交微信审核' })).toBeDisabled()
    expect(fetchMock.mock.calls.some(([path]) => String(path).endsWith('/submit'))).toBe(false)
  })

  it('queries an uncertain application instead of resubmitting and shows official signing', async () => {
    const fetchMock = mockApi(true, { state: 'submission_unknown', editable: false })
    renderPage()
    await openEditor('查看进度')
    expect(screen.getByText('可能已向微信提交，暂时禁止再次提交。请查询原申请进度；不要新建申请。')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '保存草稿' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: '查询微信进度' }))
    expect(await screen.findByRole('link', { name: '打开微信官方办理页面' })).toHaveAttribute('href', 'https://pay.weixin.qq.com/apply?id=test')
    expect(fetchMock.mock.calls.some(([path]) => String(path).endsWith('/submit'))).toBe(false)
  })

  it('rejects unreasonable source sizes before making a request', async () => {
    const fetchMock = mockApi()
    renderPage()
    await openEditor()
    const file = new File([new Uint8Array(20 * 1024 * 1024 + 1)], 'photo.png', { type: 'image/png' })
    fireEvent.change(screen.getByLabelText('上传营业执照'), { target: { files: [file] } })
    expect((await screen.findAllByText('原照片超过20MB，请选择普通手机照片或先裁去无关背景。')).length).toBeGreaterThan(0)
    expect(fetchMock.mock.calls.some(([path]) => String(path).includes('/attachments/'))).toBe(false)
  })

  it('allows photos larger than the old two-megabyte limit', async () => {
    const fetchMock = mockApi()
    vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:photo-preview-test')
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
    class TestImage {
      naturalWidth = 1200
      naturalHeight = 800
      onload: (() => void) | null = null
      set src(_url: string) { queueMicrotask(() => this.onload?.()) }
    }
    vi.stubGlobal('Image', TestImage)
    renderPage()
    await openEditor()
    const data = new Uint8Array(3 * 1024 * 1024)
    data.set([137, 80, 78, 71, 13, 10, 26, 10])
    const file = new File([data], 'photo.png', { type: 'image/png' })
    fireEvent.change(screen.getByLabelText('上传营业执照'), { target: { files: [file] } })
    await waitFor(() => expect(fetchMock.mock.calls.some(([path]) => String(path).includes('/attachments/'))).toBe(true))
    expect(await screen.findByText('照片已加密保存，尚未发送微信。请点击预览确认文字清晰，原文件未修改。')).toBeInTheDocument()
    expect(screen.getAllByAltText('营业执照上传预览').length).toBeGreaterThan(0)
    expect(fetchMock.mock.calls.some(([path]) => String(path).endsWith('/submit'))).toBe(false)
  })

  it('normalizes old saved account spacing only when the user saves the draft', async () => {
    const fetchMock = mockApi(false, { fields: { ...initial.fields, account_number: '0012 3456 7890' } })
    renderPage()
    await openEditor()
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'PUT')).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: '保存草稿' }))
    await screen.findByText('草稿已加密保存，未提交微信。')
    const save = fetchMock.mock.calls.find(([, init]) => init?.method === 'PUT')!
    expect(JSON.parse(String(save[1]?.body)).fields.account_number).toBe('001234567890')
    expect(fetchMock.mock.calls.some(([path]) => String(path).endsWith('/submit'))).toBe(false)
  })
})
