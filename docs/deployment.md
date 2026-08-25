# POI Hub 中心化 SaaS 部署指南

本文只描述软件方统一运营的服务器部署。商户无需安装程序、数据库或内网穿透，只通过 HTTPS 浏览器访问；微信授权、腾讯地图/微信服务 POI、本地生活 API 与回调均由中央平台处理。

## 1. 生产拓扑

最低受控试点拓扑：

- 1 个 HTTPS 负载均衡/WAF 和固定公网域名。
- 2 个无状态 API 实例，避免发布或单机故障中断回调。
- 2～4 个 Worker 进程，按微信配额调整并发。
- PostgreSQL 14+；推荐受管高可用实例和持续归档备份。
- 前端静态资源由 CDN、对象存储或 Nginx 提供。
- 集中日志、指标与告警；生产密钥使用云密钥管理或受控 Secret 服务。

当前任务队列以 PostgreSQL 为持久协调层，不强制依赖 Redis。达到多实例高并发后，Redis 可用于全局限流、短期缓存和 token 单飞锁，但不可保存唯一的业务或账务事实。

## 2. 生产配置

`.env` 不得提交版本库。中央生产示例：

~~~dotenv
APP_ENV=production
DEPLOYMENT_MODE=saas
APP_NAME=POI Hub
DATABASE_URL=postgresql+asyncpg://poi_app:替换密码@postgres.internal:5432/poi_hub
SECRET_KEY=替换为至少32字符的独立随机密钥
ENCRYPTION_KEY=替换为另一组至少32字符的独立随机密钥
LOG_LEVEL=INFO

WECHAT_API_BASE_URL=https://api.weixin.qq.com
WECHAT_HTTP_MAX_CONNECTIONS=100
WECHAT_HTTP_MAX_KEEPALIVE_CONNECTIONS=20

WORKER_CONCURRENCY=4
WORKER_BURST_SIZE=200
WORKER_LEASE_SECONDS=120
WEBHOOK_MAX_ATTEMPTS=8

# SaaS 收费由租户订阅和账单控制，不使用设备离线许可证。
LICENSE_MODE=off
~~~

应用会拒绝以下危险配置：

- 生产 SaaS 使用 SQLite，即使设置旧版豁免变量也不能启动。
- 生产或预发把微信 API 指向非 `https://api.weixin.qq.com` 的主机。
- 使用默认或不足 32 字符的会话密钥、加密密钥。
- SaaS 开启 `warn/enforce` 离线许可证模式。
- HTTP keep-alive 上限大于总连接上限。

## 3. 构建与迁移

示例使用 Ubuntu/Debian、部署目录 `/opt/poi-hub`、运行用户 `poi`：

~~~bash
cd /opt/poi-hub
uv sync --frozen --no-dev
cd frontend
npm ci
npm run build
cd ..
uv run alembic upgrade head
~~~

数据库迁移必须作为一次性发布任务执行，不能让多个 API 实例同时跑迁移。先备份、验证迁移，再滚动替换 API 和 Worker。生产禁止运行 `python -m poi_admin.seed --reset`，该命令会重建演示数据。

迁移完成后，通过交互式终端创建首个平台管理员：

~~~bash
uv run poi-bootstrap-admin --email owner@example.com --display-name "平台管理员"
~~~

命令会隐藏密码输入并要求二次确认，密码至少 16 个字符。默认只允许创建首个平台管理员；一旦已有平台管理员，再次执行会拒绝创建第二个全局管理员。紧急恢复同一账号时才使用 `--rotate-existing`，该操作会撤销该账号的现有登录会话。不要把密码写进命令参数、Shell 历史、`.env`、部署日志或工单。

## 4. 进程服务

API 示例：

~~~ini
[Unit]
Description=POI Hub API
After=network.target

[Service]
Type=simple
User=poi
Group=poi
WorkingDirectory=/opt/poi-hub
EnvironmentFile=/opt/poi-hub/.env
ExecStart=/opt/poi-hub/.venv/bin/python -m uvicorn poi_admin.main:app --app-dir /opt/poi-hub/backend --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
~~~

Worker 示例：

~~~ini
[Unit]
Description=POI Hub Worker
After=network.target

[Service]
Type=simple
User=poi
Group=poi
WorkingDirectory=/opt/poi-hub
EnvironmentFile=/opt/poi-hub/.env
ExecStart=/opt/poi-hub/.venv/bin/python -m poi_admin.worker
Restart=always
RestartSec=3
TimeoutStopSec=180

[Install]
WantedBy=multi-user.target
~~~

多 API 服务器使用相同构建产物和配置，但每个实例独立启动进程。Worker 已生成唯一实例 ID，不要人为设置成相同值。扩容前先核算 PostgreSQL 最大连接数：API 实例池、Worker 并发、迁移和运维连接总和必须保留安全余量。

## 5. HTTPS 与微信回调

反向代理至少设置：

- 仅开放 443，HTTP 永久跳转 HTTPS。
- TLS 1.2+、自动续期证书、HSTS、请求大小限制和合理超时。
- `/api/` 代理到 API 集群；前端路由回退到 `index.html`。
- 保留原始请求体、查询参数和必要头部，回调验签前不得改写载荷。
- 对登录和管理接口限速；微信回调不能用简单 IP 白名单代替签名验证。

回调域名由软件方统一维护。每个微信连接保存独立 callback token、EncodingAESKey、AppID/授权方标识；接收后依次执行大小限制、签名验证、AES 解密、AppID 校验、指纹去重、加密落库，再由 Worker 异步处理。

## 6. 数据库与备份

- 开启自动备份和 PostgreSQL WAL 持续归档，备份与主库使用不同故障域。
- 至少每月恢复到隔离环境并校验租户、连接、券、操作、回调、审计和账务表。
- 监控连接数、锁等待、慢查询、膨胀、磁盘、复制延迟和备份失败。
- 对 sessions、operations、webhook_events、audit_logs 制定保留/归档策略，不能直接无条件删除。
- 敏感字段密文备份仍属于敏感数据；备份介质必须加密并限制下载权限。

建议目标由合同等级决定。受控试点可先采用 RPO 15 分钟、RTO 2 小时；收费和核销规模扩大后再收紧，并用恢复演练证明，而不是只依赖云控制台显示“备份成功”。

## 7. 监控和告警

最低告警清单：

- API 5xx、P95/P99 延迟、登录失败突增和数据库池耗尽。
- 回调验签失败、解密失败、积压数量、最老未处理时间和死信。
- 操作队列深度、最老任务年龄、成功率、重试率、租约回收和 Worker 心跳。
- 微信 401/token 刷新失败、429、5xx 和上游超时。
- PostgreSQL 主库/副本、磁盘、备份、证书和域名到期。
- 商户停用/恢复、平台管理员登录、连接密钥变化和未来的账单/支付异常。

所有日志应包含请求 ID，并在可能时关联租户 ID、连接 ID、操作 ID、微信请求号和回调指纹；不得记录明文券码、openid、AppSecret、refresh token、完整手机号或解密后的回调整包。

## 8. 发布与回滚

1. 在预发使用生产等价 PostgreSQL 跑完整迁移和回归。
2. 备份生产库并确认可恢复点。
3. 暂停或收敛旧 Worker，执行一次迁移任务。
4. 滚动发布 API，检查健康、登录、租户隔离和回调接收。
5. 滚动发布 Worker，观察队列租约、重试和微信错误率。
6. 发布前端并做商品、POI、发券回调、核销、撤销、账单的冒烟验证。

应用回滚不能盲目反向执行破坏性数据库迁移。若新旧版本数据结构不兼容，应使用前向修复迁移或从已验证备份恢复，并记录受影响的微信外部副作用。

## 9. 上线前检查

- [ ] `DEPLOYMENT_MODE=saas`，PostgreSQL 连接启用 TLS 和最小权限账号。
- [ ] 至少两台 API 和多个 Worker，无共享本地磁盘依赖。
- [ ] 公网 HTTPS、证书续期、WAF、回调签名/AES 验证通过。
- [ ] 微信各商户权限、授权刷新、取消授权和 token 失效流程已演练。
- [ ] 备份恢复、数据库切换、Worker 强杀和回调重放已演练。
- [ ] 总部商户停用/恢复权限仅授予平台管理员并进入审计日志。
- [ ] 消费者货款与软件服务费账务完全分开。
- [ ] 自动收费上线前已完成订阅、用量、账单、支付、退款/冲正台账和合同审核。
