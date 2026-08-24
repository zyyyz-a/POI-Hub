import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  reporter: process.env.CI ? 'line' : 'list',
  use: {
    baseURL: 'http://127.0.0.1:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: 'powershell -NoProfile -ExecutionPolicy Bypass -File scripts/e2e-api.ps1',
      cwd: '..',
      port: 8000,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: 'powershell -NoProfile -ExecutionPolicy Bypass -File scripts/dev-web.ps1 -Port 5173',
      cwd: '..',
      port: 5173,
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
})
