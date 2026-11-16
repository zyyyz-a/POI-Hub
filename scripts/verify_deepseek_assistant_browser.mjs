// Intercept every API; no real merchant writes or AI requests.
import { createRequire } from 'node:module'
const require = createRequire(new URL('../frontend/package.json', import.meta.url))
const { chromium } = require('@playwright/test')
const browser = await chromium.launch({ channel: 'msedge', headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1360, height: 1000 } })
  const chatRequests = []
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const row = { id: 'a1', store_id: 's1', state: 'draft', version: 1, sp_mchid: '1900000000', platform_app_id: 'wxtest', editable: true, fields: { merchant_name: 'Synthetic only' }, attachments: [], issues: ['Test only'], audit_details: [] }
  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    let value = []
    if (path.endsWith('/assistant/status')) value = { configured: true, model: 'deepseek-flash', provider: 'DeepSeek' }
    else if (path.endsWith('/assistant/chat')) {
      chatRequests.push(request.postDataJSON())
      value = { reply: '1. 打开微信官方行业结算规则。\n2. 核对实际经营类目，不要随意填写ID。', model: 'deepseek-flash' }
    } else if (request.method() !== 'GET') throw new Error('Business write forbidden')
    else if (path.endsWith('/me')) value = { user: { id: 'u', email: 'test@example.com', display_name: 'Test', status: 'active', is_platform_admin: true }, tenant: { id: 't', name: 'Synthetic', slug: 'test', status: 'active' }, membership: null, tenants: [] }
    else if (path.endsWith('/auth/csrf')) value = { csrf_token: 'test-only' }
    else if (path.endsWith('/capabilities')) value = { real_submission_enabled: true, max_image_bytes: 5242880 }
    else if (path.endsWith('/merchant-applyments/a1')) value = row
    else if (path.endsWith('/merchant-applyments')) value = [row]
    else if (path.endsWith('/stores')) value = [{ id: 's1', name: 'Synthetic store' }]
    await route.fulfill({ json: value })
  })
  await page.goto('http://127.0.0.1:5180/merchant-applyments')
  await page.getByRole('button', { name: '继续填写' }).click()
  await page.getByRole('button', { name: '不会填？' }).first().click()
  await page.getByText('正在咨询：营业执照名称').waitFor()
  if (chatRequests.length) throw new Error('Help auto-sent without consent')
  await page.getByRole('checkbox', { name: '同意将主动输入的问题发送至 DeepSeek' }).check()
  await page.getByRole('button', { name: '发送问题', exact: true }).click()
  await page.getByText('1. 打开微信官方行业结算规则。', { exact: false }).waitFor()
  if (chatRequests.length !== 1 || chatRequests[0].field !== 'merchant_name' || JSON.stringify(chatRequests).includes('Synthetic only')) throw new Error('Incorrect context or data leakage')
  await page.screenshot({ path: 'screenshots/deepseek-assistant-desktop.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.waitForFunction(() => { const box = document.querySelector('[role="dialog"]')?.getBoundingClientRect(); return box && box.width <= window.innerWidth + 1 && box.x >= -1 })
  const drawer = await page.getByRole('dialog').boundingBox()
  if (!drawer || drawer.width > 391 || drawer.x < -1) throw new Error('Mobile drawer overflow')
  await page.screenshot({ path: 'screenshots/deepseek-assistant-mobile.png', fullPage: true })
  if (errors.length) throw new Error(errors.join('; '))
  console.log(JSON.stringify({ result: 'passed', mockedAIRequests: chatRequests.length, formValuesSent: false, actualMerchantSubmissions: 0, mobileWidth: drawer.width }))
} finally { await browser.close() }
