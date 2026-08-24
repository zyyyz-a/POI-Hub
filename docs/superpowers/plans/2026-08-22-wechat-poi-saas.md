# WeChat Local Life and POI SaaS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a runnable multi-tenant Chinese administration system for WeChat Local Life and Official Account POIs, with Mock/live adapters and no Docker dependency.

**Architecture:** A FastAPI modular monolith and one SQLite-backed worker share application services and typed connector ports. A React/TypeScript administration frontend consumes versioned REST APIs; every external mutation is represented by a durable operation and every tenant-owned record is scoped by `tenant_id`.

**Tech Stack:** Python 3.12, uv, FastAPI, SQLAlchemy 2, SQLite/aiosqlite, Alembic, HTTPX, React 19, TypeScript, Vite, Ant Design, TanStack Query, pytest, Vitest, Playwright

---

## File Structure

```text
pyproject.toml                         Python dependencies and tool settings
alembic.ini / migrations/             SQLite schema migrations
backend/poi_admin/                     Installable backend package
backend/poi_admin/core/                Configuration, DB, errors, security, tenancy
backend/poi_admin/identity/            Sessions, users, invitations, memberships
backend/poi_admin/connections/         Connection modes, encrypted credentials, gateways
backend/poi_admin/operations/          Durable operation queue and worker
backend/poi_admin/stores/              Canonical stores, POIs, candidates, mappings
backend/poi_admin/local_life/          Products, SKUs, orders, vouchers, accounting
backend/poi_admin/webhooks/            Verification, decryption, inbox, handlers
backend/poi_admin/dashboard/           Aggregate operational summaries
backend/poi_admin/main.py              FastAPI application factory
backend/poi_admin/seed.py              Deterministic demo tenant and data
tests/                                 Backend behavior and request-shape tests
frontend/src/api/                      Typed API client and query keys
frontend/src/auth/                     Session state and protected routing
frontend/src/layout/                   Work-focused application shell
frontend/src/pages/                    Feature pages by backend module
frontend/src/components/               Shared tables, status, and operation controls
frontend/tests/                         Vitest component tests
e2e/                                   Playwright seeded Mock workflow
scripts/                               Local PowerShell launch helpers
```

### Task 1: Tooling, Configuration, Database, and Health API

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`, `alembic.ini`
- Create: `backend/poi_admin/core/config.py`, `backend/poi_admin/core/database.py`, `backend/poi_admin/main.py`
- Create: `migrations/env.py`, `migrations/versions/0001_foundation.py`
- Test: `tests/conftest.py`, `tests/test_health.py`

- [ ] **Step 1: Write a failing health test**

```python
async def test_liveness(client):
    response = await client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 2: Run `uv run pytest tests/test_health.py -q`**

Expected: FAIL because `poi_admin.main` does not exist.

- [ ] **Step 3: Add the package, settings, async SQLite engine, migration base, and application factory**

```python
def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="POI Hub", version="0.1.0")
    app.state.settings = settings or get_settings()
    app.include_router(health_router, prefix="/api/v1")
    return app
```

- [ ] **Step 4: Run `uv sync`, `uv run alembic upgrade head`, and the health test**

Expected: dependency lock is created, migration succeeds, and the test passes.

- [ ] **Step 5: Run `uv run ruff check backend tests` and commit**

```powershell
git add pyproject.toml uv.lock .gitignore .env.example alembic.ini migrations backend tests
git commit -m "build: scaffold FastAPI and SQLite foundation"
```

### Task 2: Identity, Invitation-Only Tenancy, Sessions, and RBAC

**Files:**
- Create: `backend/poi_admin/core/security.py`, `backend/poi_admin/core/permissions.py`, `backend/poi_admin/core/dependencies.py`
- Create: `backend/poi_admin/identity/models.py`, `schemas.py`, `service.py`, `router.py`
- Modify: `migrations/versions/0001_foundation.py`, `backend/poi_admin/main.py`
- Test: `tests/identity/test_sessions.py`, `tests/identity/test_tenant_isolation.py`, `tests/identity/test_permissions.py`

- [ ] **Step 1: Write failing tests for opaque-cookie login, invitation acceptance, tenant isolation, and all five roles**

```python
async def test_operator_cannot_manage_members(operator_client):
    response = await operator_client.post("/api/v1/members/invitations", json={"email": "new@example.com", "role": "operator"})
    assert response.status_code == 403
    assert response.json()["code"] == "permission_denied"
```

- [ ] **Step 2: Verify each focused test fails for missing behavior**

Run: `uv run pytest tests/identity -q`
Expected: FAIL with missing identity modules/routes.

- [ ] **Step 3: Implement Argon2id passwords, hashed sessions, CSRF checks, invitations, memberships, tenant context, and fixed role policies**

```python
class Role(StrEnum):
    PLATFORM_ADMIN = "platform_admin"
    TENANT_ADMIN = "tenant_admin"
    OPERATOR = "operator"
    VERIFIER = "verifier"
    AUDITOR = "auditor"
```

- [ ] **Step 4: Run identity tests and the complete backend suite**

Expected: all session, invitation, isolation, and permission cases pass.

- [ ] **Step 5: Commit**

```powershell
git add backend/poi_admin/core backend/poi_admin/identity migrations tests/identity
git commit -m "feat: add invitation-only tenant access"
```

### Task 3: Connections, Encryption, Mock Gateways, and Durable Operations

**Files:**
- Create: `backend/poi_admin/connections/models.py`, `schemas.py`, `ports.py`, `mock.py`, `crypto.py`, `service.py`, `router.py`
- Create: `backend/poi_admin/operations/models.py`, `service.py`, `worker.py`, `router.py`
- Modify: migration and `main.py`
- Test: `tests/connections/test_gateway_contract.py`, `test_secrets.py`, `tests/operations/test_worker.py`

- [ ] **Step 1: Write failing gateway contract, AES-GCM round-trip/redaction, operation lease, idempotency, retry, and terminal-error tests**

```python
async def test_duplicate_idempotency_key_returns_existing(operation_service, tenant):
    first = await operation_service.enqueue(tenant.id, "sync_pois", "sync:pois:1", {})
    second = await operation_service.enqueue(tenant.id, "sync_pois", "sync:pois:1", {})
    assert second.id == first.id
```

- [ ] **Step 2: Run focused tests and confirm expected failures**

- [ ] **Step 3: Implement connection mode selection, encrypted secret bundles, typed gateways, deterministic Mock fixtures, and a single-worker leased SQLite queue**

```python
class OperationStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    RETRY_WAIT = "retry_wait"
    FAILED = "failed"
```

- [ ] **Step 4: Run connection/operation tests and complete backend suite**

- [ ] **Step 5: Commit**

```powershell
git add backend/poi_admin/connections backend/poi_admin/operations migrations tests/connections tests/operations
git commit -m "feat: add tenant connections and durable operations"
```

### Task 4: Canonical Stores, POI Sync, Candidate Matching, and Mapping

**Files:**
- Create: `backend/poi_admin/stores/models.py`, `schemas.py`, `matching.py`, `service.py`, `router.py`
- Modify: `connections/ports.py`, `connections/mock.py`, migration, `main.py`
- Test: `tests/stores/test_matching.py`, `test_mappings.py`, `test_store_api.py`

- [ ] **Step 1: Write failing tests for CRUD, normalized matching, distance scoring, human-only confirmation, one-active-mapping constraints, and tenant isolation**

```python
def test_exact_name_nearby_address_is_high_confidence():
    score = score_candidate(store(name="西湖店", lat=30.25, lng=120.16), poi(name="西湖店", lat=30.2501, lng=120.1601))
    assert score.total >= 0.9
    assert score.distance_meters < 20
```

- [ ] **Step 2: Run store tests and verify missing-module failures**

- [ ] **Step 3: Implement canonical store/POI persistence, Mock sync, transparent name/address/distance scores, candidate dismissal, explicit confirm/manual-map/unbind commands**

- [ ] **Step 4: Run store tests and complete backend suite**

- [ ] **Step 5: Commit**

```powershell
git add backend/poi_admin/stores backend/poi_admin/connections migrations tests/stores
git commit -m "feat: add store and POI mapping workflow"
```

### Task 5: Local Life Products and Inventory

**Files:**
- Create: `backend/poi_admin/local_life/models.py`, `schemas.py`, `products.py`, `router_products.py`
- Modify: gateway ports/Mock, operations worker, migration, `main.py`
- Test: `tests/local_life/test_products.py`, `test_inventory.py`, `test_product_operations.py`

- [ ] **Step 1: Write failing tests for product validation, state transitions, create-then-stock sequencing, audit/list/delist/delete commands, and idempotency**

```python
async def test_create_product_enqueues_stock_after_remote_ids(product_service, mock_gateway):
    product = await product_service.create(valid_product_command(stock=25))
    await drain_operations()
    assert mock_gateway.calls == ["add_product", "update_stock"]
    assert product.skus[0].stock == 25
```

- [ ] **Step 2: Verify focused failures**

- [ ] **Step 3: Implement product/SKU models, validators, lifecycle policies, routes, Mock gateway methods, and operation handlers**

- [ ] **Step 4: Run local-life product tests and complete backend suite**

- [ ] **Step 5: Commit**

```powershell
git add backend/poi_admin/local_life backend/poi_admin/connections backend/poi_admin/operations migrations tests/local_life
git commit -m "feat: manage Local Life products and stock"
```

### Task 6: Orders, Vouchers, Consumption, After-Sales, Funds, and Bills

**Files:**
- Create: `backend/poi_admin/local_life/orders.py`, `vouchers.py`, `accounting.py`, `router_orders.py`, `router_accounting.py`
- Modify: `backend/poi_admin/local_life/models.py`, `backend/poi_admin/local_life/schemas.py`, `backend/poi_admin/connections/ports.py`, `backend/poi_admin/connections/mock.py`, `backend/poi_admin/operations/worker.py`, `migrations/versions/0001_foundation.py`, `backend/poi_admin/main.py`
- Test: `tests/local_life/test_orders.py`, `test_vouchers.py`, `test_accounting.py`

- [ ] **Step 1: Write failing tests for seeded order sync, masked voucher output, mapped-store consumption, timeout reconciliation, revoke, after-sales, and bill differences**

```python
async def test_verifier_consumes_with_confirmed_store_mapping(verifier_client, mapped_voucher):
    response = await verifier_client.post(f"/api/v1/local-life/vouchers/{mapped_voucher.id}/consume", json={"store_id": str(mapped_voucher.store_id)})
    assert response.status_code == 202
    assert response.json()["operation"]["status"] == "queued"
```

- [ ] **Step 2: Verify focused failures**

- [ ] **Step 3: Implement read models, safe serialization, consume/revoke policies, state-query-before-retry behavior, and reconciliation summaries**

- [ ] **Step 4: Run focused and complete backend tests**

- [ ] **Step 5: Commit**

```powershell
git add backend/poi_admin/local_life backend/poi_admin/connections backend/poi_admin/operations migrations tests/local_life
git commit -m "feat: add voucher operations and reconciliation"
```

### Task 7: Encrypted Webhooks and Live HTTP Request Adapters

**Files:**
- Create: `backend/poi_admin/webhooks/crypto.py`, `models.py`, `service.py`, `handlers.py`, `router.py`
- Create: `backend/poi_admin/connections/wechat_http.py`, `local_life_live.py`, `service_poi_live.py`, `tokens.py`
- Modify: gateway factory, migration, `main.py`
- Test: `tests/webhooks/test_crypto.py`, `test_inbox.py`, `tests/connections/test_live_request_shapes.py`

- [ ] **Step 1: Write failing golden-vector callback tests and one exact request-shape test for every live gateway method**

```python
@respx.mock
async def test_local_product_list_uses_server_token(live_gateway):
    route = respx.post("https://api.weixin.qq.com/channels/ec/product/locallife/list/get").mock(return_value=httpx.Response(200, json={"errcode": 0, "product_ids": []}))
    await live_gateway.list_products(status=None, cursor=None, page_size=30)
    assert route.calls[0].request.url.params["access_token"] == "test-authorizer-token"
```

- [ ] **Step 2: Verify crypto and request-shape tests fail**

- [ ] **Step 3: Implement URL verification, signature validation, AES decrypt/AppID check, durable fingerprinted inbox, event handlers, bounded HTTP client, token refresh lock, error classification, and all documented live methods**

- [ ] **Step 4: Run webhook/live tests and complete backend suite**

- [ ] **Step 5: Commit**

```powershell
git add backend/poi_admin/webhooks backend/poi_admin/connections migrations tests/webhooks tests/connections
git commit -m "feat: integrate secure WeChat callbacks and APIs"
```

### Task 8: Dashboard, Audit Log, and Deterministic Demo Seed

**Files:**
- Create: `backend/poi_admin/audit/models.py`, `service.py`, `router.py`
- Create: `backend/poi_admin/dashboard/service.py`, `router.py`, `backend/poi_admin/seed.py`
- Modify: `backend/poi_admin/identity/service.py`, `backend/poi_admin/connections/service.py`, `backend/poi_admin/stores/service.py`, `backend/poi_admin/local_life/products.py`, `backend/poi_admin/local_life/vouchers.py`, `backend/poi_admin/operations/service.py`, `migrations/versions/0001_foundation.py`, `backend/poi_admin/main.py`, `pyproject.toml`
- Test: `tests/test_dashboard.py`, `tests/test_audit.py`, `tests/test_seed.py`

- [ ] **Step 1: Write failing tests for aggregate counts, immutable audit entries, redaction, and idempotent seed execution**

- [ ] **Step 2: Verify failures**

- [ ] **Step 3: Implement audit hooks, dashboard summaries, seeded platform admin/tenant/connections/stores/POIs/products/orders/vouchers/funds/failures, and reset command**

- [ ] **Step 4: Run `uv run python -m poi_admin.seed --reset` twice and all backend tests**

Expected: both seed runs succeed and result counts remain stable.

- [ ] **Step 5: Commit**

```powershell
git add backend/poi_admin/audit backend/poi_admin/dashboard backend/poi_admin/seed.py migrations tests pyproject.toml
git commit -m "feat: add operational dashboard and demo data"
```

### Task 9: Frontend Tooling, Authentication, and Application Shell

**Files:**
- Create: `frontend/package.json`, `package-lock.json`, `tsconfig*.json`, `vite.config.ts`, `eslint.config.js`, `index.html`
- Create: `frontend/src/main.tsx`, `styles.css`, `api/client.ts`, `auth/AuthProvider.tsx`, `layout/AppShell.tsx`, `pages/LoginPage.tsx`, `pages/DashboardPage.tsx`
- Test: `frontend/tests/auth.test.tsx`, `frontend/tests/shell.test.tsx`

- [ ] **Step 1: Write failing Vitest tests for sign-in, protected redirect, tenant switcher, role-aware navigation, dashboard loading/error/data states**

```tsx
it('hides member administration from operators', async () => {
  renderApp({ role: 'operator' })
  expect(screen.queryByText('成员管理')).not.toBeInTheDocument()
})
```

- [ ] **Step 2: Run `npm.cmd test -- --run` in `frontend` and verify failures**

- [ ] **Step 3: Implement Vite/React tooling, same-origin cookie client, auth provider, compact Ant Design shell, protected routes, and dashboard**

- [ ] **Step 4: Run frontend tests, typecheck, and build**

Run: `npm.cmd test -- --run`, `npm.cmd run typecheck`, `npm.cmd run build`
Expected: all pass without warnings.

- [ ] **Step 5: Commit**

```powershell
git add frontend
git commit -m "feat: build administration shell and dashboard"
```

### Task 10: Store, POI, and Mapping Frontend

**Files:**
- Create: `frontend/src/pages/StoresPage.tsx`, `StoreDetailPage.tsx`, `PoisPage.tsx`, `MappingsPage.tsx`
- Create: `frontend/src/api/stores.ts`, `frontend/src/components/MatchEvidence.tsx`
- Modify: routes/navigation/styles
- Test: `frontend/tests/stores.test.tsx`, `frontend/tests/mappings.test.tsx`

- [ ] **Step 1: Write failing tests for store CRUD, POI sync pending state, candidate evidence, confirm/dismiss/manual map/unbind, and URL-persisted filters**

- [ ] **Step 2: Verify focused failures**

- [ ] **Step 3: Implement dense table/detail workspaces and all expected loading, empty, error, optimistic-version, permission, and confirmation states**

- [ ] **Step 4: Run frontend tests, typecheck, and build**

- [ ] **Step 5: Commit**

```powershell
git add frontend/src frontend/tests
git commit -m "feat: add store and POI mapping workspace"
```

### Task 11: Local Life, Operations, Connections, and Administration Frontend

**Files:**
- Create: `frontend/src/pages/ProductsPage.tsx`, `ProductDetailPage.tsx`, `OrdersPage.tsx`, `VoucherDetailPage.tsx`, `AccountingPage.tsx`, `ConnectionsPage.tsx`, `OperationsPage.tsx`, `WebhooksPage.tsx`, `AuditPage.tsx`, `MembersPage.tsx`
- Create: `frontend/src/api/products.ts`, `orders.ts`, `accounting.ts`, `connections.ts`, `operations.ts`, `members.ts`
- Create: `frontend/src/components/OperationStatus.tsx`, `ConfirmAction.tsx`, `MoneyText.tsx`
- Modify: `frontend/src/main.tsx`, `frontend/src/layout/AppShell.tsx`, `frontend/src/styles.css`
- Test: `frontend/tests/products.test.tsx`, `vouchers.test.tsx`, `accounting.test.tsx`, `connections.test.tsx`, `operations.test.tsx`, `members.test.tsx`

- [ ] **Step 1: Write failing tests for product lifecycle, stock, voucher consume/revoke, reconciliation filters, Mock/live connection forms, operation retry, callback detail, invitations, and role restrictions**

- [ ] **Step 2: Verify focused failures**

- [ ] **Step 3: Implement the pages with feature-complete forms, status timelines, destructive confirmations, pending-operation feedback, pagination, and sanitized diagnostics**

- [ ] **Step 4: Run complete frontend tests, typecheck, lint, and build**

- [ ] **Step 5: Commit**

```powershell
git add frontend/src frontend/tests
git commit -m "feat: complete Local Life operations interface"
```

### Task 12: Local Launch, End-to-End Tests, Documentation, and Visual Verification

**Files:**
- Create: `scripts/dev-api.ps1`, `scripts/dev-worker.ps1`, `scripts/dev-web.ps1`
- Create: `playwright.config.ts`, `e2e/mock-workflow.spec.ts`, `README.md`
- Modify: `backend/poi_admin/main.py`, `frontend/package.json`, `.env.example`, `.gitignore`
- Test: full backend, frontend, and Playwright suites

- [ ] **Step 1: Write the failing Playwright seeded workflow from login through mapping, product/stock, consume/revoke, callback deduplication, reconciliation, and permission denial**

- [ ] **Step 2: Start API, worker, and frontend using local scripts and confirm the E2E test fails only for missing integration details**

- [ ] **Step 3: Complete static build serving, local scripts, accessible labels, responsive constraints, README commands, official-document references, and demo credentials**

- [ ] **Step 4: Run final verification**

```powershell
uv run ruff check backend tests
uv run mypy backend
uv run pytest -q
npm.cmd test -- --run
npm.cmd run typecheck
npm.cmd run build
npm.cmd run e2e
git diff --check
```

Expected: every command exits 0; Playwright screenshots show non-overlapping desktop and mobile layouts; browser console contains no application errors.

- [ ] **Step 5: Commit**

```powershell
git add scripts e2e playwright.config.ts README.md backend frontend .env.example
git commit -m "test: verify complete Mock operations workflow"
```
