// Local visual QA only: every API call uses synthetic fixtures, never production data.
import { createRequire } from 'node:module'
import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'

const require = createRequire(new URL('../frontend/package.json', import.meta.url))
const { chromium } = require('@playwright/test')
const output = resolve(process.env.APPLYMENT_PREVIEW_OUTPUT || 'screenshots/merchant-applyments-preview')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: process.env.APPLYMENT_PREVIEW_CHANNEL || 'msedge', headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1080 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  const row = {
    id: 'preview-a', store_id: 'preview-s', connection_id: 'preview-c', business_code: 'POI_preview_only',
    sp_mchid: '1900000000', platform_app_id: 'wx0000000000000000', state: 'draft',
    applyment_id: null, sub_mchid: null, last_error_code: null, last_request_id: null,
    version: 1, updated_at: '2026-10-19T00:00:00Z', editable: true,
    fields: { merchant_name: '个体户示例经营者', store_name: '示例试点门店', store_address: '示例经营地址', bank_account_type: 'personal', settlement_rule_confirmed: false },
    attachments: [], issues: ['请上传营业执照照片', '请填写经营者信息', '请核对结算银行与微信行业规则'], audit_details: [], sign_url: null,
  }
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (route.request().method() !== 'GET') throw new Error('Preview must not mutate any API')
    let value = []
    if (path.endsWith('/me')) value = { user: { id: 'preview-u', email: 'preview@example.com', display_name: '测试管理员', status: 'active', is_platform_admin: false }, tenant: { id: 'preview-t', name: '测试商户空间', slug: 'preview', status: 'active' }, membership: { id: 'preview-m', role: 'tenant_admin', tenant_id: 'preview-t' }, tenants: [] }
    else if (path.endsWith('/auth/csrf')) value = { csrf_token: 'preview-only' }
    else if (path.endsWith('/capabilities')) value = { real_submission_enabled: false }
    else if (path.endsWith('/merchant-applyments/preview-a')) value = row
    else if (path.endsWith('/merchant-applyments')) value = [row]
    else if (path.endsWith('/stores')) value = [{ id: 'preview-s', name: '示例试点门店' }]
    else if (path.endsWith('/connections')) value = [{ id: 'preview-c', capability: 'mini_program_commerce', mode: 'live', app_id: row.platform_app_id, merchant_id: row.sp_mchid }]
    await route.fulfill({ json: value })
  })
  await page.goto((process.env.APPLYMENT_PREVIEW_URL || 'http://127.0.0.1:5180') + '/merchant-applyments')
  await page.getByRole('button', { name: '继续填写' }).click()
  await page.getByLabel('营业执照名称', { exact: true }).waitFor()
  await page.screenshot({ path: resolve(output, 'desktop.png'), fullPage: true })
  for (let i = 0; i < 3; i++) await page.getByRole('button', { name: '下一步', exact: true }).click()
  if (!(await page.getByRole('button', { name: '确认资料，提交微信审核' }).isDisabled())) throw new Error('Submission gate missing')
  await page.screenshot({ path: resolve(output, 'review.png'), fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.waitForFunction(() => document.querySelector('.poi-sider')?.getBoundingClientRect().width === 0)
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.screenshot({ path: resolve(output, 'mobile.png'), fullPage: true })
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)
  if (overflow) throw new Error('Mobile page has horizontal overflow')
  if (errors.length) throw new Error(errors.join('\n'))
  console.log(JSON.stringify({ result: 'passed', output, layouts: ['desktop', 'review', 'mobile'], realApiRequests: 0 }))
} finally {
  await browser.close()
}
