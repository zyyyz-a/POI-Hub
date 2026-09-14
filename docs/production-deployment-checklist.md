# 统一平台小程序＋中心化 SaaS 生产部署清单

本文是上线前的操作清单，配合 [中心化 SaaS 部署指南](deployment.md)（架构与 systemd 示例）、
[统一平台小程序交接方案](unified-platform-miniapp-handoff.md) 和
[上线手册](wechat-location-miniapp-runbook.md) 使用。按顺序执行，未打勾项不得对外营业。

原则：外部资质时间不由开发团队控制；开发只承诺“具备提交与测试条件”，不承诺官方通过日期。

---

## 0. 外部前置条件（与开发并行）

- [ ] 平台主体已注册统一小程序，取得 AppID / AppSecret。
- [ ] 小程序备案、服务类目、隐私保护指引、用户协议、客服联系方式已提交且状态可查。
- [ ] 一个正式 HTTPS API 域名，并在小程序后台配置为 request 合法域名。
- [ ] 微信支付普通商户号（第一店直连）或服务商资质（批量）；商户号与平台 AppID 绑定关系已确认。
- [ ] 缔丝风尚：营业执照、结算账户、商户超级管理员确认、商户号、腾讯地图 POI 标识与认领凭证。
- [ ] 腾讯地图/微信位置服务入口审核（外部流程，时间不受控）。

密钥只通过受控后台/密钥库交付，不得经聊天传输；曾以非受控渠道发送过的生产密钥一律轮换。

---

## 1. 服务器盘点与 3x-ui 保护

- [ ] 只读盘点现有服务、监听端口、证书、防火墙、磁盘与内存（`ss -lntup`、`systemctl`、`df -h`、`free -m`）。
- [ ] 记录 3x-ui 的入站、节点、监听端口、证书和数据库路径；**不修改**其任何业务配置。
- [ ] 确认 SaaS 使用独立系统用户、目录、数据库、内部端口和子域名，不复用 3x-ui 管理域名。
- [ ] 1 核 1.5GB / 10GB 系统盘的 AkileCloud 机器只可用于极小流量临时试点；正式收费前迁到独立资源，避免与 3x-ui 共同故障域。
- [ ] 部署前后各截一次监听端口与服务状态，出现冲突先停止 SaaS 发布，不改 3x-ui 解决。

## 2. 系统与账号

- [ ] Ubuntu/Debian，创建独立运行用户 `poi`（无登录 shell 或受限）。
- [ ] 部署目录 `/opt/poi-hub`，属主 `poi:poi`，权限 `755`（`.env` 为 `640`）。
- [ ] 安装 `uv`、Node LTS、Nginx/Caddy、PostgreSQL 14+ 客户端。
- [ ] 系统时区设为 `Asia/Shanghai`，开启 NTP 时间同步（微信回调对时间戳敏感）。

## 3. 代码与依赖

- [ ] 从 `user/POI-Hub` 的 `feat/platform-miniapp`（或合并后的发布分支）拉取，记录 commit 与 tag。
- [ ] 后端：`uv sync --frozen --no-dev`。
- [ ] 前端：`cd frontend && npm ci && npm run build`。
- [ ] 小程序：复制 `miniapp/config.example.js` 为 `miniapp/config.js` 填 API 域名与客服电话，用开发者工具上传体验版；不得提交 `config.js`。

## 4. 环境变量（只列名称，值不写入文档）

- [ ] `APP_ENV=production`
- [ ] `DEPLOYMENT_MODE=saas`
- [ ] `DATABASE_URL`（PostgreSQL + asyncpg，启用 TLS，最小权限账号）
- [ ] `SECRET_KEY`、`ENCRYPTION_KEY`（两组独立随机、≥32 字符；加密密钥丢失将无法解密已存 openid/手机号/券码）
- [ ] `APP_NAME`、`LOG_LEVEL`
- [ ] `WECHAT_API_BASE_URL=https://api.weixin.qq.com`
- [ ] `WECHAT_HTTP_MAX_CONNECTIONS`、`WECHAT_HTTP_MAX_KEEPALIVE_CONNECTIONS`
- [ ] `WORKER_CONCURRENCY`、`WORKER_BURST_SIZE`、`WORKER_LEASE_SECONDS`、`WEBHOOK_MAX_ATTEMPTS`
- [ ] `LICENSE_MODE=off`

应用会拒绝：生产用 SQLite、微信 API 指向非官方域名、默认或过短密钥、SaaS 开启离线许可证、keep-alive 大于总连接。

## 5. 数据库

- [ ] PostgreSQL 已开启自动备份 + WAL 持续归档，备份与主库不同故障域，备份介质加密。
- [ ] 迁移作为一次性发布任务执行，**禁止多实例同时迁移**：
      `uv run alembic upgrade head`（当前 head 为 `0018_reconciliation`）。
- [ ] 生产**禁止** `python -m poi_admin.seed --reset`（会重建演示数据）。
- [ ] 创建首个平台管理员：
      `uv run poi-bootstrap-admin --email owner@example.com --display-name "平台管理员"`（≥16 位密码，不写入命令/历史/.env）。
- [ ] 校验迁移后存在：`billing_*`、`direct_refunds`、`direct_reconciliation_*`、`platform_mini_programs`、`mini_program_store_bindings`、`merchant_payment_profiles`。

## 6. 后台初始化配置（登录 SaaS 后按顺序）

- [ ] 平台管理员登录 → 建立租户（商户）。
- [ ] 平台小程序接入页：登记唯一平台小程序（AppID、交易连接、回调已配置）→ 启用。
- [ ] 门店入口绑定：门店 + 公开 `store_code` + 腾讯地图 POI + 官方审核编号/凭证 → 启用。
- [ ] 支付档案：按门店选择普通商户直连（`mchid`）或服务商（`sp_mchid` + `sub_mchid`），核验归属 → 启用。
- [ ] 平台服务费：建套餐 → 给商户建订阅（含宽限期）。
- [ ] 商户侧：建门店、服务 POI、准入工单、商品；商品数量上限固定为 1。
- [ ] 用「平台小程序接入 → 门店入口」预览公开接口：`GET /api/v1/public/platform/stores/{store_code}` 应返回 `tradable=true` 且无 blocker。

## 7. 进程与反向代理

- [ ] API：`python -m uvicorn poi_admin.main:app --host 127.0.0.1 --port 8000`（systemd，见部署指南）。
- [ ] Worker：`python -m poi_admin.worker`（systemd；自动执行关单与账单逾期维护）。
- [ ] 前端：Nginx 提供 `frontend/dist`，SPA 路由回退 `index.html`。
- [ ] 反向代理：仅暴露 443，HTTP 跳 HTTPS，TLS 1.2+、HSTS、请求体大小限制、回调路径不改写请求体。
- [ ] API/数据库只监听内网或回环；多 API 实例 + 多 Worker（SQLite 只允许单 Worker，生产已用 PostgreSQL）。
- [ ] `/api/` 代理到 API；登录与后台接口限速；微信回调依靠签名验证，不用 IP 白名单替代。

## 8. 微信支付回调地址

- [ ] 平台统一回调（推荐）：`https://<API域名>/api/v1/public/platform/wechatpay/notify/{payment_profile_id}`，
      写入对应门店支付连接的 `notify_url` 密钥项；回调按订单号 + 支付档案快照校验 `appid/mchid/sub_mchid/金额`。
- [ ] 兼容旧单店回调：`https://<API域名>/api/v1/public/wechatpay/notify/{mini_program_id}`。
- [ ] 用真实微信后台“支付回调测试”或体验版低额支付验证：验签、解密、幂等、金额校验通过。
- [ ] 确认回调域名证书链完整、`Content-Type` 与原始 body 未被代理改动。

## 9. 监控与告警

- [ ] API：5xx、P95/P99 延迟、登录失败突增、数据库连接池耗尽。
- [ ] 回调：验签失败、解密失败、积压数量、最老未处理时间、死信。
- [ ] 操作队列：深度、最老任务年龄、成功率、重试率、租约回收、Worker 心跳。
- [ ] 交易：超时未关单、退款失败、对账差异数（`difference_count > 0`）。
- [ ] 账单：逾期账单数、订阅即将到期/已停用。
- [ ] 基础设施：PostgreSQL 主从、磁盘、备份失败、证书与域名到期。
- [ ] 日志含请求 ID 并尽量关联租户/订单/操作/回调指纹；**禁止**记录明文券码、openid、AppSecret、完整手机号或解密回调整包。

## 10. 备份与恢复演练

- [ ] 完成一次真实恢复：从备份恢复到隔离库，校验租户、连接、订单、券、退款、账单、对账、审计表。
- [ ] 记录 RPO/RTO（受控试点建议 RPO 15 分钟、RTO 2 小时，后续收紧）。
- [ ] 演练 Worker 强杀与租约回收、微信回调重放、重复回调幂等。
- [ ] `sessions`、`operations`、`webhook_events`、`audit_logs` 有保留/归档策略，不无条件删除。

## 11. 安全加固

- [ ] 密钥仅用云密钥管理或受控 Secret；不进入仓库、镜像、日志与工单。
- [ ] 防火墙只放行 443 与必要的运维端口；关闭调试端点与默认账号。
- [ ] 平台管理员停用/恢复商户等高风险操作仅授予平台管理员并进入审计日志。
- [ ] 消费者货款与平台服务费账务完全分开；服务费只按独立合同/账单收取。
- [ ] 图片/视频使用 HTTPS 对象存储/CDN，并限制类型、大小与来源（当前为 URL 引用）。

## 12. 上线冒烟（对照方案二验收）

- [ ] 两家测试租户共用一个平台 AppID：各自 `store_code` 只看到本店商品，篡改入口参数不串店。
- [ ] 从腾讯地图入口直达正确门店；入口失效显示独立错误页。
- [ ] 体验版闭环：登录 → 下单 → 微信支付 → 预约 → 出券 → 店员核销。
- [ ] 支付取消可继续支付；支付结果未知不重复付款；超时关单释放库存。
- [ ] 全额退款与重复退款拦截；退款后券作废、预约取消、库存回补。
- [ ] 顾客账单、微信商户平台、SaaS 订单三方金额与商户号一致。
- [ ] 导入一日真实账单完成对账，差异项可登记处理。
- [ ] 订阅停用/逾期超宽限后，门店自动变为不可交易（`tradable=false`）。
- [ ] 平台管理员、商户管理员、运营、核销员、审计员权限分别验证；跨租户不可见。
- [ ] 3x-ui 服务、端口、连接在部署前后均正常。

## 13. 回滚

- [ ] 发布前记录 commit/tag 与备份可恢复点。
- [ ] 应用回滚不盲目反向执行破坏性迁移；不兼容时用前向修复迁移或从验证过的备份恢复。
- [ ] 记录回滚期间产生的微信外部副作用（已支付、已退款、已挂载入口），人工核对。
- [ ] 回滚后重新跑第 12 节冒烟关键项。

## 14. 上线验收 Gate（全部通过才可标记正式营业）

- [ ] 平台小程序、备案、类目、隐私、版本审核有效。
- [ ] 腾讯地图入口直达正确 `store_code`。
- [ ] 服务端按门店决定收款账户，客户端无法篡改。
- [ ] 消费者货款进入对应商户账户，不进入平台普通账户。
- [ ] 支付成功/取消/超时/查单/关单/退款全部通过。
- [ ] 回调验签、解密、AppID/商户号/订单号/金额/幂等校验通过。
- [ ] 单店入口、商品、订单、预约、券码无跨租户泄漏。
- [ ] 券码只核销一次，退款券不可核销，误核销有审批与审计。
- [ ] 服务费有独立合同、账单与收款记录。
- [ ] 数据库完成一次真实恢复验证。
- [ ] 24 小时观察期无未处理回调、死信与账务差异。
