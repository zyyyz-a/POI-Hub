# POI Hub

面向线下商家的微信位置服务与独立小程序交易中台。主路线是“腾讯位置／服务 POI＋商家自有小程序＋商家微信支付”，同时保留微信小店本地生活兼容模块。后端使用 FastAPI、SQLAlchemy 和 PostgreSQL（本地开发可用 SQLite）；前端使用 React、TypeScript、Vite。开发环境默认使用 Mock 微信连接，不需要 Docker。

## 本地运行

1. uv sync
2. Copy-Item .env.example .env
3. uv run alembic upgrade head
4. uv run python -m poi_admin.seed --reset
5. 分别运行 scripts/dev-api.ps1、scripts/dev-worker.ps1、scripts/dev-web.ps1

浏览器访问 http://127.0.0.1:5173。演示账号：admin@example.com / correct-horse-battery-staple。数据保存在 .data/poi_admin.sqlite3。

## 商业化部署边界

- 默认商业形态是软件方统一运营的中心化 SaaS：`DEPLOYMENT_MODE=saas`、PostgreSQL、多 API/Worker；商户只登录使用，不安装本地节点。
- 总部“商户主控”可停用或恢复租户；停用后商户成员不能继续访问业务接口，数据和审计记录保留。
- Worker 支持并发槽、队列突发抽取、租约续期、回调退避/死信和批量人工重试。
- 独立小程序订单使用商家绑定的微信支付商户号收款；平台软件服务费必须通过独立合同和独立账单收取，不能从顾客订单中擅自截留。详见 [微信位置与独立小程序上线手册](docs/wechat-location-miniapp-runbook.md) 与 [服务器部署指南](docs/deployment.md)。

## 验证

后端：uv run pytest -q、uv run ruff check backend tests、uv run mypy backend。

前端：在 frontend 目录运行 npm.cmd test -- --run、npm.cmd run typecheck、npm.cmd run lint、npm.cmd run build。
浏览器验收：首次在 frontend 目录运行 npm.cmd install（Playwright 会使用已安装的 Chromium），然后运行 npm.cmd run e2e。该命令会启动临时 API、worker 和 Vite 服务，并重置本地测试数据库；不需要 Docker。

## 功能范围

- 邀请制租户、会话 Cookie、CSRF、五级 RBAC 与租户隔离。
- 门店主数据、微信服务 POI 镜像、候选匹配、人工确认/解绑。
- 类目资料预审、官方报备留痕、官方结果双人权限门禁、微信位置服务挂载。
- 商家独立小程序登记、商品、原子库存、顾客登录、JSAPI 支付、预约和一次性券码核销。
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
