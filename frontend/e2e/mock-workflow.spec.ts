import { expect, test } from '@playwright/test'

test('seeded Mock operator workflow reaches mapping and operation center', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('邮箱').fill('admin@example.com')
  await page.getByLabel('密码').fill('correct-horse-battery-staple')
  await page.locator('button[type="submit"]').click()
  await expect(page.getByRole('heading', { name: '运营总览' })).toBeVisible()

  await page.getByRole('link', { name: '门店管理' }).click()
  await page.getByRole('button', { name: '新建门店' }).click()
  await page.getByLabel('门店编码').fill('E2E-001')
  await page.getByLabel('门店名称').fill('浏览器验收门店')
  await page.getByLabel('详细地址').fill('杭州市西湖区验收路 1 号')
  await page.getByRole('button', { name: '创建门店' }).click()
  await expect(page.getByText('浏览器验收门店')).toBeVisible()

  await page.getByRole('link', { name: '服务 POI' }).click()
  await page.locator('.ant-select').first().click()
  await page.locator('.ant-select-item-option').first().click()
  await page.getByRole('link', { name: '操作中心' }).click()
  await expect(page.getByText('service_poi.sync')).toBeVisible({ timeout: 20_000 })
  await expect(page.getByText('succeeded')).toBeVisible({ timeout: 20_000 })

  await page.getByRole('link', { name: 'POI 映射' }).click()
  await expect(page.getByRole('cell', { name: '浏览器验收门店' }).first()).toBeVisible({ timeout: 20_000 })
  await page.getByRole('button', { name: '确认' }).first().click()
  await expect(page.getByText('当前活动映射')).toBeVisible()
})

test('fixed sidebar does not cover tenant controls', async ({ page }) => {
  await page.goto('/login')
  await page.getByLabel('邮箱').fill('admin@example.com')
  await page.getByLabel('密码').fill('correct-horse-battery-staple')
  await page.locator('button[type="submit"]').click()
  await expect(page.getByRole('heading', { name: '运营总览' })).toBeVisible()

  const sider = await page.locator('.poi-sider').boundingBox()
  const trigger = await page.getByRole('button', { name: /\u5207\u6362\u79df\u6237/ }).boundingBox()
  expect(sider).not.toBeNull()
  expect(trigger).not.toBeNull()
  expect(trigger!.x).toBeGreaterThanOrEqual(sider!.x + sider!.width - 1)

  await page.getByRole('button', { name: /\u5207\u6362\u79df\u6237/ }).click()
  const menu = await page.getByRole('menu').boundingBox()
  expect(menu).not.toBeNull()
  expect(menu!.x).toBeGreaterThanOrEqual(sider!.x + sider!.width - 1)
})

