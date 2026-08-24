# Comprehensive Test Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development or executing-plans to implement this plan task-by-task.

**Goal:** 补齐后端和前端的高风险行为测试，并用完整验证命令确认可提交。

**Architecture:** 保持现有 FastAPI/SQLAlchemy、React/Vitest/Playwright 结构；新增测试按领域文件组织。路由测试使用 ASGI client，adapter 测试使用 respx，worker 使用真实 SQLite。只在失败测试证明现有实现错误时修改生产代码。

**Tech Stack:** Python 3.12、uv、pytest、pytest-asyncio、respx、Alembic、FastAPI；React 19、Vitest、Testing Library、Playwright。

---

### Task 1: 后端 schema 与路由安全矩阵

**Files:**
- Create: `tests/test_migrations_real.py`
- Create: `tests/test_route_security_matrix.py`
- Modify: `pyproject.toml` only if coverage tooling is made reproducible

- [ ] 用临时 SQLite 执行 `alembic upgrade head`，校验 head revision、关键表、唯一约束和外键。
- [ ] 通过 HTTP client 验证 connections、operations、webhooks、accounting、orders 的认证、CSRF、RBAC、跨租户和错误状态。
- [ ] 运行领域测试确认失败原因，再修正最小缺陷。

### Task 2: Local Life 交易与对账

**Files:**
- Create/modify: `tests/local_life/test_order_routes.py`, `tests/local_life/test_accounting_routes.py`
- Modify if needed: `backend/poi_admin/local_life/*.py`

- [ ] 覆盖订单同步/详情、券码列表/详情/核销/撤销、售后同步/详情。
- [ ] 运行 worker，断言订单、券码、售后最终状态及幂等行为。
- [ ] 写入资金流水和券账单，验证对账数量、总额和差异。

### Task 3: 微信 adapter、token、HTTP 与 Webhook

**Files:**
- Create/modify: `tests/connections/test_live_contracts.py`, `tests/connections/test_tokens_http.py`, `tests/webhooks/test_encrypted_callbacks.py`, `tests/worker/test_lifecycle.py`
- Modify if needed: `backend/poi_admin/connections/*.py`, `backend/poi_admin/webhooks/*.py`, `backend/poi_admin/worker.py`

- [ ] 对 Local Life 和 Service POI 每个协议方法验证路径、查询参数、请求体和响应映射。
- [ ] 验证 token 首次获取、刷新、并发锁、错误分类、429/5xx/超时。
- [ ] 验证加密回调、签名/AppID/AES/JSON/body size 错误和业务状态更新。
- [ ] 验证 worker 轮询、失败恢复、空队列和 graceful shutdown。

### Task 4: 前端页面与 E2E

**Files:**
- Create: `frontend/tests/domain_pages.test.tsx`
- Modify: `frontend/tests/workspaces.test.tsx`, `frontend/e2e/mock-workflow.spec.ts`, `frontend/package.json`

- [ ] 覆盖 Connections、Members、Products、Pois、Orders、Accounting、Operations、Webhooks、Audit 的加载、空态、错误态和主要 mutation。
- [ ] 扩展 Playwright 覆盖商品、订单/券码和对账流程。
- [ ] 加入前端 coverage provider，记录可复现命令。

### Task 5: 全套验证与提交

- [ ] 运行 `uv run pytest -q`、前端 Vitest、Playwright、Ruff、mypy、lint、build。
- [ ] 运行后端和前端覆盖率，检查关键模块没有回退。
- [ ] 检查 `git diff`、工作区和提交内容。
- [ ] 提交测试与必要的最小生产修复。
