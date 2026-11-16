import { Alert, Button, Checkbox, Drawer, Input, Space, Spin, Typography } from 'antd'
import { RobotOutlined, SendOutlined, SettingOutlined } from '@ant-design/icons'
import { useEffect, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { api, type AssistantStatus, type AssistantMessage } from '../api/client'
import { useAuth } from '../auth/AuthProvider'
import { ASSISTANT_HELP_EVENT } from '../common/assistant'
import './deepseek-assistant.css'

export function DeepSeekAssistant() {
  const { user, tenant } = useAuth()
  if (!user?.is_platform_admin) return null
  return <AssistantWindow key={`${user.id}:${tenant?.id || 'platform'}`} />
}

function AssistantWindow() {
  const location = useLocation()
  const [open, setOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [status, setStatus] = useState<AssistantStatus | null>(null)
  const [messages, setMessages] = useState<AssistantMessage[]>([])
  const [question, setQuestion] = useState('')
  const [field, setField] = useState('')
  const [fieldLabel, setFieldLabel] = useState('')
  const [consent, setConsent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [saving, setSaving] = useState(false)
  const [key, setKey] = useState('')
  const [error, setError] = useState('')
  const requestRef = useRef<AbortController | null>(null)
  const lock = useRef(false)
  const bottom = useRef<HTMLDivElement>(null)

  async function loadStatus() {
    setError('')
    try { setStatus(await api.assistantStatus()) }
    catch (reason) { setError(reason instanceof Error ? reason.message : '助手状态读取失败') }
  }

  useEffect(() => {
    const help = (event: Event) => {
      const detail = (event as CustomEvent<{ field: string; label: string }>).detail
      const target = detail?.field
      if (typeof target !== 'string') return
      setField(target)
      setFieldLabel(typeof detail.label === 'string' ? detail.label : '当前字段')
      setQuestion('请解释这个字段是什么、去哪里找资料，以及如何填写。')
      setOpen(true)
    }
    window.addEventListener(ASSISTANT_HELP_EVENT, help)
    return () => { window.removeEventListener(ASSISTANT_HELP_EVENT, help); requestRef.current?.abort() }
  }, [])
  useEffect(() => {
    if (!open) return
    let active = true
    api.assistantStatus().then(value => { if (active) setStatus(value) })
      .catch(reason => { if (active) setError(reason instanceof Error ? reason.message : '助手状态读取失败') })
    return () => { active = false }
  }, [open])
  useEffect(() => { bottom.current?.scrollIntoView?.({ behavior: 'smooth' }) }, [messages, busy])

  async function send() {
    const text = question.trim()
    if (!text || lock.current || !consent || !status?.configured) return
    lock.current = true; setBusy(true); setError('')
    const controller = new AbortController()
    requestRef.current = controller
    const history = messages.slice(-6).map(item => ({ ...item, content: item.content.slice(0, 1200) }))
    const outgoing: AssistantMessage[] = [...history, { role: 'user', content: text }]
    try {
      const answer = await api.assistantChat(outgoing, location.pathname, field, controller.signal)
      if (controller.signal.aborted) return
      setMessages(current => [...current, { role: 'user', content: text }, { role: 'assistant', content: answer.reply }])
      setQuestion('')
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '提问失败，请稍后重试')
    } finally {
      lock.current = false
      if (!controller.signal.aborted) setBusy(false)
    }
  }

  async function saveKey() {
    if (!key.trim() || saving) return
    setSaving(true); setError('')
    try {
      setStatus(await api.saveAssistantKey(key.trim()))
      setKey(''); setSettingsOpen(false)
    } catch (reason) { setError(reason instanceof Error ? reason.message : '密钥保存失败') }
    finally { setSaving(false) }
  }

  return <>
    <Button className="deepseek-launcher" aria-label="DeepSeek 助手" type="primary" shape="round" icon={<RobotOutlined />} onClick={() => setOpen(true)}>DeepSeek 助手</Button>
    <Drawer title={<Space><RobotOutlined />DeepSeek 填写助手</Space>} open={open} onClose={() => { setOpen(false); setSettingsOpen(false); setKey('') }} width="min(460px, 100vw)" mask={false} zIndex={1100} className="deepseek-drawer" extra={<Button type="text" aria-label="助手设置" icon={<SettingOutlined />} onClick={() => { setSettingsOpen(value => !value); setKey('') }} />}>
      <div className="deepseek-layout">
        <Alert type="info" showIcon message="帮你解释和指导，不会自动修改或提交" description="仅发送你主动输入的问题及页面/字段说明；不读取表单值、照片或商户记录。不要发送身份证、银行卡、密码或密钥。AI回答须核对。" />
        {(settingsOpen || status?.configured === false) && <div className="deepseek-settings">
          <Typography.Text strong>连接 DeepSeek（仅平台管理员）</Typography.Text>
          <p>请从 <a href="https://platform.deepseek.com/api_keys" target="_blank" rel="noopener noreferrer">DeepSeek 开放平台</a> 创建 API Key。不是登录密码，API调用按其账户计费。</p>
          <Input.Password aria-label="DeepSeek API Key" value={key} onChange={event => setKey(event.target.value)} placeholder="在此粘贴 API Key" autoComplete="off" maxLength={250} />
          <Button type="primary" loading={saving} disabled={!key.trim()} onClick={() => void saveKey()}>加密保存密钥</Button>
          <small>密钥不会回显，不存入浏览器；保存不代表已验证余额或调用权限，发送一次问题后确认。</small>
        </div>}
        {!status && <Button onClick={() => void loadStatus()}>重试读取助手状态</Button>}
        {error && <Alert type="error" showIcon message={error} closable onClose={() => setError('')} />}
        <div className="deepseek-history" role="log" aria-label="助手对话" aria-live="polite">
          {!messages.length && <div className="deepseek-welcome"><Typography.Title level={4}>卡在哪一步？直接问我</Typography.Title><p>例如“子商户号怎么取得？”“结算规则ID去哪找？”也可以点击字段旁的「不会填？」。</p><Space wrap>{['当前页面下一步怎么操作？', '子商户号和原商户号有什么区别？', '结算规则ID去哪里找？'].map(text => <Button key={text} size="small" onClick={() => { setField(''); setQuestion(text) }}>{text}</Button>)}</Space></div>}
          {messages.map((item, i) => <div key={i} className={`deepseek-message ${item.role}`}><strong>{item.role === 'user' ? '我' : 'DeepSeek'}</strong><div>{item.content}</div></div>)}
          {busy && <div className="deepseek-working"><Spin size="small" /> 正在整理操作步骤，请稍候…</div>}
          <div ref={bottom} />
        </div>
        <div className="deepseek-composer">
          <div className="deepseek-context"><span>{field ? `正在咨询：${fieldLabel}` : '结合当前页面说明回答'}</span><Button type="text" size="small" disabled={busy} onClick={() => { setMessages([]); setField(''); setQuestion('') }}>清空对话</Button></div>
          <Input.TextArea aria-label="向DeepSeek提问" placeholder="把不懂的字段或操作写在这里…" value={question} onChange={event => setQuestion(event.target.value)} maxLength={1800} showCount autoSize={{ minRows: 3, maxRows: 6 }} disabled={busy} onKeyDown={event => { if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); void send() } }} />
          <Checkbox checked={consent} onChange={event => setConsent(event.target.checked)}>同意将主动输入的问题发送至 DeepSeek</Checkbox>
          <Button block aria-label="发送问题" type="primary" icon={<SendOutlined />} loading={busy} disabled={!question.trim() || !consent || !status?.configured} onClick={() => void send()}>发送问题</Button>
          <small>对话只保留在当前窗口，刷新或切换商户空间即清空。</small>
        </div>
      </div>
    </Drawer>
  </>
}
