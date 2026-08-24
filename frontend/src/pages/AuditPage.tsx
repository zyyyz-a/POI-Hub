import { api } from '../api/client'
import { ListWorkspacePage } from './ListWorkspacePage'
export function AuditPage() { return <ListWorkspacePage kind="audit" queryFn={async () => await api.audit() as Record<string, unknown>[]} /> }
