import { Alert, Empty, Skeleton } from 'antd'
import type { ReactNode } from 'react'

export function WorkspaceState({ loading, error, empty, children }: {
  loading: boolean
  error: unknown
  empty: boolean
  children: ReactNode
}) {
  if (loading) return <div className="workspace-state"><Skeleton active paragraph={{ rows: 4 }} /></div>
  if (error) return <Alert type="error" showIcon message={error instanceof Error ? error.message : '数据加载失败'} description="请稍后重试" />
  if (empty) return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无数据" />
  return <>{children}</>
}
