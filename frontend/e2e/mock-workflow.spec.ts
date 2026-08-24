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
