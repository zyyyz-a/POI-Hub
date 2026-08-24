# WeChat Local Life and POI SaaS Design

**Date:** 2026-08-22
**Status:** Approved by delegated architecture authority

## 1. Context

The requested product is a multi-tenant operations SaaS for two separate WeChat capabilities:

1. WeChat Shop Local Life, formerly named Video Accounts Shop Local Life, manages group-buying products, inventory, voucher codes, orders, voucher consumption, after-sales, and settlement data.
2. Official Account Store Mini Program POI APIs manage Tencent Map points and store metadata.

These capabilities do not share an official store key. Local Life accepts a merchant-defined `out_store_id` during consumption and a free-text `available_store_desc` on a product; neither is validated against an Official Account `poi_id`. The SaaS therefore owns canonical stores and keeps the WeChat identifiers as optional mappings.

## 2. Goals

- Deliver a runnable Python backend and an interactive Chinese-language administration frontend.
- Support multiple isolated tenant organizations through an invitation-only SaaS model.
- Support both deterministic Mock connections and credential-backed live WeChat connections per tenant.
- Manage canonical stores and provide suggested, human-confirmed mappings to Official Account POIs.
- Cover the complete documented Local Life operations surface needed by merchant operators.
- Receive, verify, deduplicate, and process WeChat callbacks safely.
- Make every external mutation observable, retryable, and auditable.
- Be straightforward to run locally with `uv`, Node.js, and no external services.

## 3. Non-Goals

- Public registration, plans, billing, subscriptions, or payment collection for this SaaS.
- A customer-facing Mini Program, order page, reservation page, or voucher-consumption Mini Program component.
- WeChat Pay merchant coupons or commodity coupons. They are different products from Local Life vouchers.
- Automatic binding of canonical stores to POIs without human confirmation.
- Splitting WeChat settlement funds between physical stores. Current Local Life guidance settles to the shop merchant account.
- Microservices, Kubernetes, or infrastructure for high request volume.

## 4. Architecture

Use a modular monolith in one repository:

```text
Browser
  -> React administration application
  -> FastAPI REST API
       -> application/domain modules
       -> SQLite database
       -> integration operation outbox
  -> worker process claims outbox jobs
       -> Mock adapters or live WeChat adapters
       -> SQLite operation and audit records

WeChat callbacks
  -> public callback endpoints
  -> signature/decryption and durable inbox
  -> worker applies idempotent state transitions
```

The API and worker are separate processes built from the same Python package. A local SQLite database is the only required state service. The first release runs one worker process and uses leased database-backed operations for durable retries and visibility without Redis or containers. SQLAlchemy boundaries keep a later move to a hosted PostgreSQL database possible without changing domain services.

### 4.1 Technology Stack

- Python 3.12
- `uv` for the virtual environment, dependency locking, and commands
- FastAPI and Pydantic v2
- SQLAlchemy 2 async ORM and Alembic
- SQLite 3 through `aiosqlite`, with a configurable SQLAlchemy database URL
- HTTPX for WeChat requests
- React 19, TypeScript, Vite
- Ant Design, TanStack Query, React Router
- pytest, pytest-asyncio, respx, Ruff, mypy
- Vitest, React Testing Library, Playwright
- Local process scripts for the API, worker, and frontend

### 4.2 Backend Modules

- `identity`: users, password authentication, sessions, invitations, and memberships.
- `tenancy`: tenants, tenant context, role checks, and platform administration.
- `stores`: canonical store records and address/coordinate normalization.
- `connections`: Mock/live connection configuration, encrypted credentials, authorization state, token lifecycle, and permission snapshots.
- `service_poi`: POI mirror records, remote POI commands, candidate matching, and confirmed mappings.
- `local_life`: products, SKUs, inventory, orders, vouchers, consumption, after-sales, funds, and bills.
- `webhooks`: handshake, signature verification, AES decryption, durable event inbox, and handlers.
- `operations`: transactional outbox, worker claiming, retries, scheduling, manual retry, and sanitized diagnostics.
- `audit`: immutable operator and integration audit events.
- `dashboard`: aggregate counts, action queues, connection health, and reconciliation summaries.

Modules expose application services and repository interfaces. HTTP routers may call application services but may not call a WeChat adapter or SQLAlchemy model directly. Connector DTOs remain inside the connector boundary and are translated to domain models.

## 5. Tenant and Access Model

The platform administrator creates a tenant and sends invitations. There is no public signup. A user may belong to multiple tenants and explicitly selects an active tenant. Every tenant-owned table contains `tenant_id`; unique keys include it where appropriate. Repositories require tenant context, and cross-tenant isolation is covered by automated tests.

Roles are fixed for the first release:

| Role | Capabilities |
| --- | --- |
| Platform administrator | Create and suspend tenants, invite tenant administrators, inspect platform health and cross-tenant audit metadata |
| Tenant administrator | Manage users, connections, stores, mappings, all Local Life operations, and tenant audit logs |
| Operator | Manage stores, mappings, products, inventory, synchronization, orders, and reconciliation; cannot view secrets or manage members |
| Verifier | Look up vouchers, consume vouchers, and revoke consumption; no product, connection, or member administration |
| Read-only auditor | View tenant business data, operations, reconciliation, and audit records without mutation |

All authorization is enforced in backend policies. Frontend route and control visibility improves usability but is not a security boundary.

## 6. Core Data Model

All primary identifiers are UUIDs generated by the application. External identifiers are strings to avoid numeric overflow and preserve undocumented formatting.

- `Tenant`: name, slug, status, created metadata.
- `User`: email, display name, Argon2 password hash, status, last-login metadata.
- `Membership`: user, tenant, role, status.
- `Invitation`: tenant, email, role, hashed token, expiry, acceptance metadata.
- `Session`: hashed opaque token, user, expiry, revoked timestamp, client metadata.
- `WeChatConnection`: tenant, capability (`local_life` or `service_poi`), mode (`mock` or `live`), authorization state, app identifiers, encrypted secret bundle, token expiry, permission snapshot, last health check.
- `Store`: tenant-owned canonical store code, name, contact details, structured address, longitude, latitude, operating status, version.
- `ServicePoi`: connection, remote `poi_id`, remote status, name, address, coordinates, category and qualification summary, raw version checksum, last synchronized timestamp.
- `StorePoiMapping`: canonical store, POI, state, confirmation actor/time, match score and evidence. A store and POI may each have at most one active mapping per connection.
- `MatchCandidate`: store, POI, score, component scores for normalized name/address/distance, generation timestamp, dismissed timestamp.
- `LocalProduct`: connection, external product ID, merchant product ID, type, name, category, brand, images, verification settings, code source, rule payload, remote audit/listing state, desired state, synchronization metadata.
- `LocalSku`: product, external SKU ID, price, stock, sold count, version.
- `LocalOrder`: connection, external order ID, status, payment data, amounts, masked customer reference, raw version checksum, synchronization metadata.
- `Voucher`: order, external voucher reference, encrypted or masked code only, SKU, state, validity, consume store marker, consume/revoke metadata.
- `AfterSale`: order, external after-sale ID, type, state, amounts, timestamps.
- `FundsFlow` and `VoucherBill`: immutable remote accounting entries and reconciliation state.
- `WebhookEvent`: connection, event fingerprint, event type, encrypted/sanitized payload, received/processed status, attempt count, error summary.
- `IntegrationOperation`: tenant, connection, command type, idempotency key, resource reference, status, attempts, next attempt, sanitized request/response, error classification.
- `AuditLog`: tenant, actor, action, resource, before/after summary, request correlation ID, timestamp.

Raw payload retention is minimized. Phone numbers, OpenIDs, voucher codes, tokens, and secrets are never written to ordinary logs.

## 7. Connector Contracts

Each capability defines a typed gateway protocol with Mock and live implementations. A tenant selects the connection mode; application services are unaware of the selected adapter. Mock adapters use deterministic tenant-scoped fixtures and support explicit failure scenarios for UI testing. Live adapters use official server-side APIs and never expose access tokens to the browser.

### 7.1 Local Life Gateway

The first release covers these official operations:

- Add, update, audit-free update, get, list, cancel audit, list, delist, and delete group-buying products.
- Update SKU stock and upload merchant voucher codes.
- Get order details.
- Find voucher list, get voucher details, consume vouchers, and revoke consumption.
- Get after-sale details.
- Get funds-flow entries and voucher bills.

Product creation is modeled as two observable steps because the official create API cannot set stock: create the product, then enqueue stock updates after external IDs are returned.

### 7.2 Official Account POI Gateway

The first release covers remote POI list/detail synchronization, Tencent Map POI search, POI creation, update, deletion, and remote audit status refresh where exposed by the current Store Mini Program APIs. POI state is not treated as Local Life state.

### 7.3 Store Matching

The candidate generator compares normalized names, normalized structured addresses, and geographic distance. It returns transparent component scores and does not create mappings. Tenant administrators and operators can confirm or dismiss a candidate, manually select a different POI, or unbind an existing mapping. Confirmed mappings are the only source used to populate merchant store markers in operations.

## 8. External Operation Flow

External mutations follow one pattern:

1. Authenticate the user, resolve the active tenant, and authorize the action.
2. Validate the command and acquire optimistic resource version checks.
3. Store the desired local state and a unique `IntegrationOperation` in one database transaction.
4. Return `202 Accepted` with the operation identifier.
5. The worker claims the operation with a database lock, resolves Mock/live adapter, and executes it.
6. Store the sanitized result, update the resource state, and append an audit event.
7. Retry rate limits, timeouts, token expiry, and server errors with bounded exponential backoff and jitter.
8. Mark permission, validation, and business-rule errors as terminal and show an actionable Chinese message in the operation center.

The same idempotency key is retained for retries. Consumption timeouts never create a new business command blindly; the worker queries current voucher state before deciding whether to retry.

Read synchronization uses cursor-aware paginated jobs. Manual synchronization and periodic incremental synchronization share the same operation model.

## 9. Callback Flow

Public callback endpoints support WeChat URL verification and encrypted JSON messages. The endpoint verifies the signature, performs AES-256-CBC/PKCS#7 decryption, validates the embedded AppID, enforces body-size limits, and calculates an event fingerprint before acknowledging. Invalid messages are rejected without persistence.

Valid messages are inserted into the durable inbox with a unique fingerprint and acknowledged quickly. A worker applies product audit, product update/listing, low-stock, payment, voucher issuance, and after-sale events idempotently. Duplicate events are no-ops. For out-of-order or incomplete events, a compensating remote detail query determines current state. Operators can inspect sanitized callback metadata and retry failed handlers.

## 10. HTTP API and Authentication

The browser uses same-origin REST endpoints under `/api/v1`. Authentication uses a high-entropy opaque session cookie; only a hash is stored in the database. Cookies are HttpOnly, Secure in non-local environments, and SameSite=Lax. Mutating requests require a matching CSRF token header. Passwords use Argon2id. Sessions can be revoked by the user or an administrator.

API groups include:

- `/auth`, `/me`, `/invitations`
- `/platform/tenants`
- `/members`, `/connections`
- `/stores`, `/pois`, `/store-poi-mappings`, `/match-candidates`
- `/local-life/products`, `/skus`, `/orders`, `/vouchers`, `/after-sales`, `/funds`, `/bills`
- `/operations`, `/webhook-events`, `/audit-logs`, `/dashboard`
- `/callbacks/wechat/{connection_id}`
- `/health/live`, `/health/ready`

Errors use `application/problem+json` with a stable code, Chinese user message, correlation ID, field errors where applicable, and no secret-bearing upstream payload.

## 11. Frontend Experience

The application opens on the operational dashboard, not a marketing page. It uses a restrained light workspace with a fixed sidebar, compact header, tenant switcher, connection-health indicators, and dense tables optimized for repeated work. All visible product copy is Chinese.

Primary views:

- Sign in and invitation acceptance.
- Platform tenant administration.
- Dashboard with pending audits, failed operations, low stock, unmapped stores, reconciliation differences, and connection health.
- Canonical store list/detail editor.
- POI list/detail and synchronization controls.
- Mapping workspace showing candidate evidence, confirm/dismiss/manual-map actions, and mapping history.
- Group-product list, detail, create/edit form, SKU inventory, qualification metadata, and lifecycle actions.
- Order, voucher, consumption, revoke, and after-sale views.
- Funds-flow and voucher-bill reconciliation tables.
- Connection authorization/settings and Mock scenario controls.
- Operation center, callback inbox, audit log, member and invitation management.

Destructive and financial actions require confirmation. Voucher consumption uses a focused modal that displays store, voucher state, and idempotency status; results cannot be mistaken for immediate success while an external operation is pending. Tables preserve filters in the URL, support pagination and empty/error/loading states, and never expose raw credentials or voucher codes.

## 12. Security and Reliability

- Encrypt WeChat secrets and refresh tokens at rest with AES-GCM using a deployment master key.
- Redact secret, token, phone, OpenID, and voucher-code fields from logs and operation diagnostics.
- Apply least-privilege role policies and tenant-scoped repositories on every business endpoint.
- Record security-sensitive and business-sensitive actions in immutable audit logs.
- Use optimistic versions for operator-edited resources and unique constraints for idempotency and external IDs.
- Bound HTTP timeouts, retries, response sizes, and pagination.
- Track connection permission snapshots because documentation availability does not prove account authorization.
- Make failed operations and failed callbacks visible; never silently discard them.
- Support graceful worker shutdown so claimed jobs return to a retryable state.

## 13. Testing Strategy

Backend tests use TDD and include:

- Unit tests for policies, state transitions, matching scores, retry classification, encryption, and payload redaction.
- Repository and API tests for tenant isolation, role permissions, pagination, validation, and optimistic concurrency.
- Gateway contract tests shared by Mock/live adapters.
- HTTP request-shape tests for every live WeChat method using `respx`; no test calls production WeChat.
- Golden-vector tests for callback signature, AES decryption, deduplication, and out-of-order handling.
- Worker tests for lease ownership, duplicate prevention, idempotency, retry/backoff, and recovery.

Frontend tests include component behavior, permission visibility, forms, pending operation states, failure recovery, and URL filters. Playwright verifies the complete seeded Mock workflow in Chromium at desktop and mobile-width viewports.

The acceptance workflow is:

1. Sign in as the seeded platform administrator.
2. Create or open a seeded tenant and switch into it.
3. Inspect healthy Mock connections for both capabilities.
4. Create canonical stores, synchronize POIs, and confirm a suggested mapping.
5. Create a group-buying product, observe asynchronous completion, update stock, and list it.
6. Inspect a seeded paid order and vouchers, consume one at a mapped store, then revoke it.
7. Process a simulated callback and confirm deduplication.
8. Inspect funds/bill reconciliation, operation history, and audit records.
9. Verify a lower-privilege role cannot access forbidden actions or another tenant.

## 14. Local Development and Deployment

The repository provides locked Python and Node dependencies, `.env.example`, SQLite migrations, deterministic seed data, and local process commands. The normal local flow is `uv sync`, run migrations and seed data through `uv run`, start the API and worker through `uv run`, then start Vite through npm. SQLite data lives under the ignored `.data/` directory. The frontend production build can be served by FastAPI so a demo needs only the API and worker processes. No Dockerfile or container orchestration is delivered in this release.

Configuration distinguishes local, test, and production environments. Startup fails clearly when production security keys are absent. Mock mode is enabled per connection, never through global branching in business code. Live credentials are supplied only through encrypted settings or environment bootstrap and are never committed.

## 15. Delivery Slices

The system remains one deployable application but is implemented in testable slices:

1. Repository foundation, tenancy, identity, roles, database, and application shell.
2. Connection abstraction, Mock adapters, operation queue, audit, and dashboard.
3. Canonical stores, POI mirror, candidate matching, and mapping UI.
4. Local Life product and inventory lifecycle.
5. Orders, vouchers, consumption/revoke, after-sales, funds, and reconciliation.
6. Live WeChat HTTP adapters, authorization/token handling, callbacks, and synchronization.
7. End-to-end hardening, local process packaging, documentation, and visual verification.

Each slice must leave the Mock demonstration runnable. Live behavior requiring merchant permissions is verified through request-shape tests until real credentials are supplied.

## 16. Official References

- [Local Life onboarding guide](https://developers.weixin.qq.com/doc/channels/dev_before/locallife/guide.html)
- [Local Life API index](https://developers.weixin.qq.com/doc/channels/api/locallife/)
- [Local Life callback configuration](https://developers.weixin.qq.com/doc/channels/dev_before/locallife/callback/callback_notification.html)
- [WeChat message push security](https://developers.weixin.qq.com/doc/channels/dev_before/base/message_push.html)
- [Add Local Life product](https://developers.weixin.qq.com/doc/channels/api/locallife/shop/api_addlocalproduct.html)
- [Consume Local Life voucher](https://developers.weixin.qq.com/doc/channels/api/locallife/useing/api_consumevoucher.html)
- [Official Account WeChat Store overview](https://developers.weixin.qq.com/doc/service/guide/product/WeChat_Store.html)
- [Search Tencent Map POIs](https://developers.weixin.qq.com/doc/service/api/stores/miniapp/api_poilistsearch)

The implementation treats current public documentation as an interface reference, not proof that a tenant has passed recruitment, qualification review, or obtained each permission set.
