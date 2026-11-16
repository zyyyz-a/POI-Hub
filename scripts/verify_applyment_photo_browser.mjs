// Synthetic photos and intercepted APIs only: no real merchant data or external uploads.
import { createRequire } from 'node:module'
const require = createRequire(new URL('../frontend/package.json', import.meta.url))
const { chromium } = require('@playwright/test')
const browser = await chromium.launch({ channel: 'msedge', headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1360, height: 960 } })
  const requests = []
  const row = {
    id: 'photo-test-a', store_id: 's1', connection_id: 'c1', business_code: 'POI_test_only',
    sp_mchid: '1900000000', platform_app_id: 'wx0000000000000000', state: 'draft',
    applyment_id: null, sub_mchid: null, last_error_code: null, last_request_id: null,
    version: 1, updated_at: '2026-10-21T00:00:00Z', editable: true,
    fields: { merchant_name: 'Synthetic photo test' }, attachments: [], issues: ['Test only'], audit_details: [], sign_url: null,
  }
  await page.route('**/api/v1/**', async route => {
    const request = route.request()
    const path = new URL(request.url()).pathname
    let value = []
    if (path.includes('/attachments/')) {
      if (request.method() !== 'POST') throw new Error('Unexpected upload method')
      const bytes = request.postDataBuffer().length
      requests.push({ bytes, type: request.headers()['content-type'] })
      row.attachments = [{ kind: 'license', size_bytes: bytes }]; row.version++
      value = row
    } else if (request.method() !== 'GET') throw new Error('Real submissions are forbidden in this test')
    else if (path.endsWith('/me')) value = { user: { id: 'u', email: 'test@example.com', display_name: 'Test', status: 'active', is_platform_admin: false }, tenant: { id: 't', name: 'Test', slug: 'test', status: 'active' }, membership: { role: 'tenant_admin', tenant_id: 't' }, tenants: [] }
    else if (path.endsWith('/auth/csrf')) value = { csrf_token: 'test-only' }
    else if (path.endsWith('/capabilities')) value = { real_submission_enabled: true, max_image_bytes: 5 * 1024 * 1024 }
    else if (path.endsWith('/merchant-applyments/photo-test-a')) value = row
    else if (path.endsWith('/merchant-applyments')) value = [row]
    else if (path.endsWith('/stores')) value = [{ id: 's1', name: 'Synthetic store' }]
    await route.fulfill({ json: value })
  })
  await page.goto('http://127.0.0.1:5180/merchant-applyments')
  await page.getByRole('button', { name: '继续填写' }).click()
  const source = await page.evaluate(async () => {
    const canvas = document.createElement('canvas')
    canvas.width = 3000; canvas.height = 2000
    const context = canvas.getContext('2d')
    const pixels = context.createImageData(canvas.width, canvas.height)
    let seed = 13859
    for (let i = 0; i < pixels.data.length; i += 4) {
      seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0
      pixels.data[i] = seed & 255; pixels.data[i + 1] = seed >>> 8 & 255; pixels.data[i + 2] = seed >>> 16 & 255; pixels.data[i + 3] = 255
    }
    context.putImageData(pixels, 0, 0)
    const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'))
    if (blob.size <= 5 * 1024 * 1024 || blob.size > 20 * 1024 * 1024) throw new Error('Unexpected synthetic source size')
    const file = new File([blob], 'synthetic-phone-photo.png', { type: 'image/png' })
    const transfer = new DataTransfer(); transfer.items.add(file)
    const input = document.querySelector('input[aria-label="上传营业执照"]')
    input.files = transfer.files; input.dispatchEvent(new Event('change', { bubbles: true }))
    canvas.width = 0; canvas.height = 0
    return { size: file.size, type: file.type }
  })
  await page.getByText('图片已自动处理至5MB内，请预览确认清晰度').waitFor({ timeout: 30000 })
  if (requests.length !== 1 || requests[0].bytes > 5 * 1024 * 1024 || requests[0].type !== 'image/jpeg') throw new Error('Incorrect prepared upload')
  const image = page.getByAltText('营业执照上传预览').first()
  await image.waitFor()
  const dimensions = await image.evaluate(element => ({ width: element.naturalWidth, height: element.naturalHeight }))
  if (dimensions.width !== 3000 || dimensions.height !== 2000) throw new Error('Photo unexpectedly cropped or stretched')
  console.log(JSON.stringify({ result: 'passed', source, uploaded: requests[0], dimensions, actualMerchantSubmissions: 0 }))
} finally {
  await browser.close()
}
