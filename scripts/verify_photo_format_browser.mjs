// Real browser decoders + synthetic images only; every business API is intercepted.
import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
const require = createRequire(new URL('../frontend/package.json', import.meta.url))
const { chromium } = require('@playwright/test')
const browser = await chromium.launch({ channel: 'msedge', headless: true })
await mkdir('.data/photo-format-fixtures', { recursive: true })
try {
  const page = await browser.newPage({ viewport: { width: 1360, height: 1000 } })
  const uploads = []
  let explicitSaves = 0
  let activeCase = ''
  const row = { id: 'a1', store_id: 's1', state: 'draft', version: 1, sp_mchid: '1900000000', platform_app_id: 'wxtest', editable: true, fields: { account_number: '0012 3456 7890' }, attachments: [], issues: ['Test only'], audit_details: [] }
  await page.route('**/api/v1/**', async route => {
    const req = route.request(); const path = new URL(req.url()).pathname
    let value = []
    if (path.includes('/attachments/')) {
      const data = req.postDataBuffer()
      const png = data.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))
      const jpeg = data[0] === 255 && data[1] === 216 && data[2] === 255 && data.at(-2) === 255 && data.at(-1) === 217
      if ((!png && !jpeg) || data.length > 5242880) throw new Error('Prepared bytes still fail the real backend signature check')
      const kind = path.split('/').at(-1)
      await writeFile(`.data/photo-format-fixtures/${activeCase}.bin`, data)
      uploads.push({ case: activeCase, kind, bytes: data.length, type: req.headers()['content-type'] })
      row.attachments = [...row.attachments.filter(item => item.kind !== kind), { kind, size_bytes: data.length }]; row.version++
      value = row
    } else if (req.method() === 'PUT' && path.endsWith('/merchant-applyments/a1')) {
      const fields = req.postDataJSON().fields
      if (fields.account_number !== '001234567890') throw new Error('Account digits changed or formatting not normalized')
      row.fields = fields; row.version++; explicitSaves++
      value = row
    } else if (req.method() !== 'GET') throw new Error('Real business write forbidden')
    else if (path.endsWith('/me')) value = { user: { id: 'u', email: 'test@example.com', display_name: 'Test', status: 'active', is_platform_admin: false }, tenant: { id: 't', name: 'Test', slug: 'test', status: 'active' }, membership: { role: 'tenant_admin' }, tenants: [] }
    else if (path.endsWith('/auth/csrf')) value = { csrf_token: 'test-only' }
    else if (path.endsWith('/capabilities')) value = { real_submission_enabled: true, max_image_bytes: 5242880 }
    else if (path.endsWith('/merchant-applyments/a1')) value = row
    else if (path.endsWith('/merchant-applyments')) value = [row]
    else if (path.endsWith('/stores')) value = [{ id: 's1', name: 'Synthetic store' }]
    await route.fulfill({ json: value })
  })
  await page.goto('http://127.0.0.1:5180/merchant-applyments')
  await page.getByRole('button', { name: '继续填写' }).click()
  await page.getByText('门店与结算', { exact: true }).click()
  await page.getByText('所有门店统一使用平台小程序，无需商家另建').waitFor()
  for (const [testCase, label] of [['webp-as-jpg', '门头照片'], ['jpeg-with-trailer', '店内照片'], ['png-as-jpg', '小程序服务页面截图']]) {
    activeCase = testCase
    await page.getByLabel(`上传${label}`, { exact: true }).waitFor()
    await page.waitForFunction(label => !document.querySelector(`input[aria-label="上传${label}"]`).disabled, label)
    const before = uploads.length
    await page.evaluate(async ({ testCase, label }) => {
      const canvas = document.createElement('canvas'); canvas.width = 1600; canvas.height = 1000
      const ctx = canvas.getContext('2d'); ctx.fillStyle = '#eeeeee'; ctx.fillRect(0, 0, 1600, 1000)
      ctx.fillStyle = '#123456'; ctx.font = '40px sans-serif'; ctx.fillText('Synthetic storefront - not merchant evidence', 50, 100)
      const type = testCase === 'webp-as-jpg' ? 'image/webp' : testCase === 'png-as-jpg' ? 'image/png' : 'image/jpeg'
      const blob = await new Promise(resolve => canvas.toBlob(resolve, type, 0.95))
      if (blob.type !== type) throw new Error('Browser did not generate expected fixture type')
      const parts = testCase === 'jpeg-with-trailer' ? [blob, '\nextra trailing camera metadata'] : [blob]
      const file = new File(parts, 'wechat-photo.jpg', { type: 'image/jpeg' })
      const transfer = new DataTransfer(); transfer.items.add(file)
      const input = document.querySelector(`input[aria-label="上传${label}"]`)
      input.files = transfer.files; input.dispatchEvent(new Event('change', { bubbles: true }))
      canvas.width = 0; canvas.height = 0
    }, { testCase, label })
    await page.waitForFunction(label => !!document.querySelector(`img[alt="${label}上传预览"]`) && !document.querySelector(`input[aria-label="上传${label}"]`).disabled, label)
    if (uploads.length !== before + 1) throw new Error('Expected exactly one compatible upload')
    const image = page.getByAltText(`${label}上传预览`).first()
    const size = await image.evaluate(img => [img.naturalWidth, img.naturalHeight])
    if (size[0] !== 1600 || size[1] !== 1000) throw new Error('Photo cropped or stretched')
  }
  const before = uploads.length
  await page.getByLabel('上传门头照片', { exact: true }).setInputFiles({ name: 'broken.jpg', mimeType: 'image/jpeg', buffer: Buffer.from([255, 216, 255, 0, 0, 0, 255, 217]) })
  await page.getByText('照片无法读取。', { exact: false }).first().waitFor()
  if (uploads.length !== before) throw new Error('Corrupt image was sent upstream')
  if (explicitSaves) throw new Error('Unexpected automatic draft save')
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await page.getByText('草稿已加密保存，未提交微信。', { exact: true }).waitFor()
  if (explicitSaves !== 1) throw new Error('Expected one explicit save')
  await page.screenshot({ path: 'screenshots/photo-format-help.png', fullPage: true })
  console.log(JSON.stringify({ result: 'passed', uploads, corruptImageBlockedBeforeUpload: true, explicitMockDraftSaves: explicitSaves, accountDigitsPreserved: true, actualMerchantSubmissions: 0 }))
} finally { await browser.close() }
