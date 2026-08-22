# POI Hub

微信团购本地生活与服务 POI 的多租户后台管理系统。后端使用 FastAPI、SQLAlchemy、SQLite；前端使用 React、TypeScript、Vite。默认使用 Mock 连接，不需要 Docker 或外部服务。

## 本地运行

1. uv sync
2. Copy-Item .env.example .env
3. uv run alembic upgrade head
4. uv run python -m poi_admin.seed --reset
5. 分别运行 scripts/dev-api.ps1、scripts/dev-worker.ps1、scripts/dev-web.ps1

浏览器访问 http://127.0.0.1:5173。演示账号：admin@example.com / correct-horse-battery-staple。数据保存在 .data/poi_admin.sqlite3。

## 验证

后端：uv run pytest -q、uv run ruff check backend tests、uv run mypy backend。

前端：在 frontend 目录运行 npm.cmd test -- --run、npm.cmd run typecheck、npm.cmd run lint、npm.cmd run build。

## 功能范围

- 邀请制租户、会话 Cookie、CSRF、五级 RBAC 与租户隔离。
- 门店主数据、微信服务 POI 镜像、候选匹配、人工确认/解绑。
- 本地生活商品、SKU 库存、审核/上架/下架/删除生命周期。
- 订单、券码脱敏、映射门店核销、撤销、售后、资金流水和券账单对账。
- Mock 与 HTTP live gateway、token 刷新锁、重试分类、durable operation worker。
- 微信回调签名/AES 解密、AppID 校验、大小限制、指纹去重和回调收件箱。
- 审计日志、dashboard 聚合、确定性 seed/reset。

## 官方文档

- 本地生活接入指南: https://developers.weixin.qq.com/doc/channels/dev_before/locallife/guide.html
- 本地生活 API: https://developers.weixin.qq.com/doc/channels/api/locallife/
- 新增本地生活商品: https://developers.weixin.qq.com/doc/channels/api/locallife/shop/api_addlocalproduct.html
- 核销券码: https://developers.weixin.qq.com/doc/channels/api/locallife/useing/api_consumevoucher.html
- 微信服务 POI: https://developers.weixin.qq.com/doc/service/guide/product/WeChat_Store.html
- POI 搜索: https://developers.weixin.qq.com/doc/service/api/stores/miniapp/api_poilistsearch
