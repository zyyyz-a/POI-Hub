# Test Coverage Completeness Design

## Goal

补齐微信团购 POI 后台的自动化测试，使后端关键路由、租户与权限边界、异步操作、微信适配器、Webhook 和 worker，以及前端页面交互都有可重复的行为验证。

## Scope

- 后端：真实 Alembic schema、HTTP 路由、CSRF/RBAC/跨租户、订单/券码/售后/对账、连接密钥、Webhook 加密与错误、token/HTTP 重试、Live adapter request-shape、worker 生命周期。
- 前端：Connections、Members、Products、POI、Orders、Accounting、Operations、Webhooks、Audit 页面状态和 mutation 交互。
- E2E：在现有 Mock 门店/POI 流程之外，增加商品、订单券码和对账主流程；不引入 Docker。

## Test strategy

测试优先级为 P0 安全与数据正确性、P1 外部集成和核心业务、P2 前端回归。后端优先通过 ASGI HTTP client 验证完整依赖链；纯适配器使用 respx 验证请求路径、查询参数、请求体和响应映射；worker 使用真实 SQLite 与可控 handler。测试 fixture 将保留 `create_all` 的快速单元测试，同时增加独立的 Alembic upgrade 测试，避免迁移漂移。

每个新行为遵循 TDD：先写一个能证明缺口的失败测试，再做最小实现或修复，最后运行领域测试和全套回归。

## Success criteria

- 后端、前端单元测试和 E2E 均通过。
- `uv run ruff check backend tests`、`uv run mypy backend`、前端 lint/build 通过。
- 覆盖率命令可在项目开发依赖中复现，并输出后端与前端报告。
- 测试不使用宽泛 `Exception` 作为主要断言，关键测试验证真实状态变化而非仅验证 queued/processed。
