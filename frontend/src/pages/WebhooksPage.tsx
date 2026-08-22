import { api } from '../api/client'
import { ListWorkspacePage } from './ListWorkspacePage'
export function WebhooksPage() { return <ListWorkspacePage kind="webhooks" queryFn={async () => await api.webhooks() as Record<string, unknown>[]} /> }
