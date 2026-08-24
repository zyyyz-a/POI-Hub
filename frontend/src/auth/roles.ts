import type { Role } from '../api/client'

export const roleLabels: Record<Role, string> = {
  platform_admin: '平台管理员',
  tenant_admin: '租户管理员',
  operator: '运营员',
  verifier: '核销员',
  auditor: '审计员',
}
