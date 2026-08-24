# Repository Cleanup and Documentation Design

**Date:** 2026-08-22  
**Status:** Approved direction

## Goal

Make the POI Hub repository easy to clone, understand, run, operate, and maintain without changing the product's runtime architecture or deleting required source assets.

## Scope

The work has two bounded parts:

1. Remove local/generated artifacts from the working tree and prevent them from being tracked again.
2. Replace the short README with a documentation index and add task-oriented Chinese guides for operators, developers, WeChat integration, API usage, and troubleshooting.

No business behavior, database schema, API contract, or frontend workflow is changed. The only frontend adjustment allowed in this cleanup is documentation-facing navigation text if it is needed to remove a misleading unfinished entry; functional pages remain unchanged.

## Cleanup Policy

Keep these repository assets:

- Backend and frontend source code.
- Alembic configuration and all migrations under `migrations/`.
- Python and Node lockfiles.
- Tests, Playwright specs, and local process scripts.
- `.env.example`, official WeChat links, and existing design/implementation records.

Remove only reproducible local output or temporary state:

- Python caches: `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `__pycache__/`.
- Local database and runtime state: `.data/`.
- Frontend dependencies and build/test output when present locally: `frontend/node_modules/`, `frontend/dist/`, `frontend/test-results/`, `frontend/.vite/`.
- Temporary scratch directories such as `.tmp/` and empty generated directories.

The existing `.gitignore` will be reviewed and extended only where a generated artifact is currently missing. Cleanup commands will target explicit repository-relative paths; no broad filesystem deletion is used.

## Documentation Information Architecture

`README.md` becomes the short entry point. It will explain the product, supported capabilities, prerequisites, a five-minute Mock startup, verification commands, and links to the detailed guides.

The `docs/` directory will contain:

- `docs/quick-start.md`: Windows-first setup with `uv`, Node/npm, migrations, seed data, three local processes, Playwright, and reset instructions.
- `docs/operator-guide.md`: tenant selection, connection setup, store and POI workflows, mapping confirmation, product/SKU lifecycle, orders/vouchers/after-sales, reconciliation, operations, callbacks, and role boundaries.
- `docs/development.md`: repository map, request flow, modular backend boundaries, frontend query patterns, worker lifecycle, migrations, seed behavior, test commands, lint/typecheck/build, and contribution checklist.
- `docs/wechat-integration.md`: distinction between Local Life and Service POI, official documentation links, Mock versus Live behavior, credential fields, callback setup, AES/signature requirements, permissions, and production safety notes.
- `docs/api.md`: authentication and CSRF sequence, tenant header, response/error conventions, route catalog by domain, durable operation polling, and representative curl/PowerShell examples.
- `docs/troubleshooting.md`: port conflicts, stale database state, worker queues, migration failures, Live credential errors, callback signature failures, frontend dependency issues, Playwright failures, and how to collect safe diagnostics.

Every guide will include prerequisites, copyable commands, expected outcomes, and links back to related guides. Secrets, voucher codes, access tokens, and personal identifiers will never be included in examples.

## Verification

After cleanup and documentation edits:

1. `uv run pytest -q`
2. `uv run ruff check backend tests`
3. `uv run mypy backend`
4. `npm.cmd test -- --run` from `frontend/`
5. `npm.cmd run typecheck` from `frontend/`
6. `npm.cmd run lint` from `frontend/`
7. `npm.cmd run build` from `frontend/`
8. `npm.cmd run e2e` from `frontend/`
9. `git diff --check` and a final ignored-artifact audit

The cleanup is complete only when the working tree contains source, documentation, tests, configuration, and intentionally versioned assets, with no generated output or temporary state.
