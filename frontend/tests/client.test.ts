import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api, setCsrfToken } from '../src/api/client'

function response(data: unknown, status = 400) {
  return Promise.resolve(new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/problem+json' },
  }))
}

async function dashboardError(payload: unknown): Promise<ApiError> {
  vi.spyOn(globalThis, 'fetch').mockImplementation(() => response(payload))
  try {
    await api.dashboard()
  } catch (error) {
    expect(error).toBeInstanceOf(ApiError)
    return error as ApiError
  }
  throw new Error('期望 dashboard 请求失败')
}

describe('API error normalization', () => {
  afterEach(() => {
    setCsrfToken(undefined)
    vi.restoreAllMocks()
  })

  it('preserves metadata from FastAPI nested detail objects', async () => {
    const error = await dashboardError({
      detail: {
        message: '当前角色无权执行此操作',
        code: 'permission_denied',
        correlation_id: 'corr-nested',
        field_errors: { email: ['邮箱不可用'] },
      },
    })

    expect(error).toMatchObject({
      message: '当前角色无权执行此操作',
      code: 'permission_denied',
      correlation_id: 'corr-nested',
      field_errors: { email: ['邮箱不可用'] },
    })
  })

  it('preserves metadata from top-level problem details', async () => {
    const error = await dashboardError({
      message: '请求参数无效',
      code: 'validation_failed',
      correlation_id: 'corr-top-level',
      field_errors: [{ field: 'email', message: '请输入有效邮箱' }],
    })

    expect(error).toMatchObject({
      message: '请求参数无效',
      code: 'validation_failed',
      correlation_id: 'corr-top-level',
      field_errors: [{ field: 'email', message: '请输入有效邮箱' }],
    })
  })

  it('uses a string problem detail as the user message', async () => {
    const error = await dashboardError({ detail: '汇总服务暂不可用', code: 'dashboard_unavailable' })

    expect(error).toMatchObject({
      message: '汇总服务暂不可用',
      code: 'dashboard_unavailable',
    })
  })
})
