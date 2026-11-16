import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthContext, type AuthContextValue } from '../src/auth/AuthProvider'
import { DeepSeekAssistant } from '../src/components/DeepSeekAssistant'
import { askAboutField } from '../src/common/assistant'
import { setCsrfToken } from '../src/api/client'
import { act } from 'react'

const auth: AuthContextValue = {
  status: 'authenticated', user: { id: 'u1', email: 'admin@example.com', display_name: 'Admin', status: 'active', is_platform_admin: true },
  tenant: { id: 't1', name: 'Test', slug: 'test', status: 'active' }, membership: null,
  tenants: [], csrfToken: 'csrf', login: vi.fn(), logout: vi.fn(), selectTenant: vi.fn(), refresh: vi.fn(),
}

function setup(configured = true, context = auth) {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = String(input)
    const value = url.endsWith('/chat') ? { reply: '先打开子商户入驻，保存草稿后核对。', model: 'deepseek-flash' } : { configured: init?.method === 'PUT' || configured, provider: 'DeepSeek', model: 'deepseek-flash' }
    return new Response(JSON.stringify(value), { status: 200, headers: { 'Content-Type': 'application/json' } })
  })
  const view = render(<AuthContext.Provider value={context}><MemoryRouter initialEntries={['/merchant-applyments']}><DeepSeekAssistant /></MemoryRouter></AuthContext.Provider>)
  return { fetchMock, view }
}

describe('DeepSeek contextual help', () => {
  afterEach(() => { vi.restoreAllMocks(); setCsrfToken(undefined) })

  it('is platform-admin only and makes no requests while closed', () => {
    const { fetchMock } = setup(true, { ...auth, user: { ...auth.user!, is_platform_admin: false } })
    expect(screen.queryByRole('button', { name: 'DeepSeek 助手' })).not.toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('requires explicit consent, sends safe context and never submits business forms', async () => {
    const { fetchMock } = setup()
    setCsrfToken('test-csrf')
    expect(fetchMock).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'DeepSeek 助手' }))
    fireEvent.change(await screen.findByLabelText('向DeepSeek提问'), { target: { value: '子商户号怎么拿到？' } })
    expect(screen.getByRole('button', { name: '发送问题' })).toBeDisabled()
    fireEvent.click(screen.getByRole('checkbox', { name: '同意将主动输入的问题发送至 DeepSeek' }))
    await waitFor(() => expect(screen.getByRole('button', { name: '发送问题' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: '发送问题' }))
    await screen.findByText('先打开子商户入驻，保存草稿后核对。')
    const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/chat'))!
    expect(JSON.parse(String(call[1]?.body))).toEqual({ messages: [{ role: 'user', content: '子商户号怎么拿到？' }], page: '/merchant-applyments', field: '', consent: true })
    expect(new Headers(call[1]?.headers).get('X-CSRF-Token')).toBe('test-csrf')
    expect(fetchMock.mock.calls.every(([url]) => String(url).startsWith('/api/v1/assistant/'))).toBe(true)
  })

  it('opens field help without reading form values or automatically asking AI', async () => {
    const { fetchMock } = setup()
    act(() => askAboutField('account_number', '结算银行账号'))
    await screen.findByText('正在咨询：结算银行账号')
    expect(screen.getByLabelText('向DeepSeek提问')).toHaveValue('请解释这个字段是什么、去哪里找资料，以及如何填写。')
    expect(fetchMock.mock.calls.every(([, init]) => !init?.method || init.method === 'GET')).toBe(true)
  })

  it('saves a key only by explicit action and clears the input afterwards', async () => {
    const { fetchMock } = setup(false)
    fireEvent.click(screen.getByRole('button', { name: 'DeepSeek 助手' }))
    fireEvent.change(await screen.findByLabelText('DeepSeek API Key'), { target: { value: 'sk-synthetic-test-key-only' } })
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === 'PUT')).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: '加密保存密钥' }))
    await waitFor(() => expect(screen.queryByLabelText('DeepSeek API Key')).not.toBeInTheDocument())
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'PUT')).toHaveLength(1)
    expect(localStorage.getItem('deepseek_api_key')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: '助手设置' }))
    expect(await screen.findByLabelText('DeepSeek API Key')).toHaveValue('')
  })

  it('clears the conversation and does not render model output as HTML', async () => {
    const { fetchMock } = setup()
    fetchMock.mockImplementation(async input => new Response(JSON.stringify(String(input).endsWith('/chat') ? { reply: '<img src=x onerror=alert(1) />' } : { configured: true }), { status: 200 }))
    fireEvent.click(screen.getByRole('button', { name: 'DeepSeek 助手' }))
    fireEvent.change(await screen.findByLabelText('向DeepSeek提问'), { target: { value: '怎么填？' } })
    fireEvent.click(screen.getByRole('checkbox'))
    await waitFor(() => expect(screen.getByRole('button', { name: '发送问题' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: '发送问题' }))
    await screen.findByText('<img src=x onerror=alert(1) />')
    expect(screen.queryByRole('img', { name: 'x' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: '清空对话' }))
    expect(screen.queryByText('<img src=x onerror=alert(1) />')).not.toBeInTheDocument()
  })
})
