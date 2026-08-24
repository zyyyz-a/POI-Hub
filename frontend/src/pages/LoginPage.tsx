import { Alert, Button, Form, Input, Typography } from 'antd'
import { LockOutlined, MailOutlined } from '@ant-design/icons'
import { useState, type FormEvent } from 'react'
import { useAuth } from '../auth/AuthProvider'
import './login.css'

export function LoginPage() {
  const auth = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string>()

  async function submit(event: FormEvent) {
    event.preventDefault()
    setError(undefined)
    setSubmitting(true)
    try { await auth.login(email, password) } catch (err) { setError(err instanceof Error ? err.message : '登录失败，请检查账号信息') } finally { setSubmitting(false) }
  }

  return <main className="login-page">
    <section className="login-panel">
      <div className="login-brand"><span className="brand-mark">P</span><span>POI Hub</span></div>
      <Typography.Title level={1}>登录 POI Hub</Typography.Title>
      <Typography.Paragraph className="login-subtitle">微信团购与门店运营工作台</Typography.Paragraph>
      {(error || auth.error) && <Alert role="alert" type="error" showIcon message={error || auth.error} className="login-alert" />}
      <Form layout="vertical" onSubmitCapture={submit}>
        <Form.Item label="邮箱" required>
          <Input aria-label="邮箱" prefix={<MailOutlined />} type="email" autoComplete="username" value={email} onChange={event => setEmail(event.target.value)} placeholder="name@company.cn" />
        </Form.Item>
        <Form.Item label="密码" required>
          <Input.Password aria-label="密码" prefix={<LockOutlined />} autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} />
        </Form.Item>
        <Button type="primary" htmlType="submit" block loading={submitting} disabled={!email || !password}>登录</Button>
      </Form>
      <p className="login-note">仅限受邀成员使用，请联系平台管理员获取账号。</p>
    </section>
    <aside className="login-aside"><span className="aside-kicker">本地生活 / 门店点位</span><h2>让每一次核销，<br />都清晰可追溯。</h2><p>连接门店、商品、订单与券码，集中处理微信本地生活运营。</p><div className="aside-rule" /></aside>
  </main>
}
