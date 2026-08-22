# POI Hub 部署指南

本文分别说明 Linux 和 Windows 部署流程。项目由 FastAPI API、独立后台 Worker 和 Vite 前端组成，不使用 Docker。

## 一、通用准备

两种系统都需要：

- Python 3.12+
- uv
- Node.js 20 LTS+
- npm
- Git
- 可持久化的数据目录

生产环境必须将 APP_ENV 设置为 production，并使用随机且至少 32 个字符的 SECRET_KEY、ENCRYPTION_KEY。不要把 .env、AppSecret、EncodingAESKey 或 Access Token 提交到 Git。

生成随机密钥：

~~~bash
uv run python -c "import secrets; print(secrets.token_urlsafe(48))"
~~~

每次执行生成一组密钥，分别填入 SECRET_KEY 和 ENCRYPTION_KEY。

## 二、Linux 部署

以下示例使用 Ubuntu/Debian、部署目录 /opt/poi-hub、运行用户 poi。

### 2.1 获取代码

~~~bash
sudo useradd --system --create-home --home-dir /opt/poi-hub --shell /usr/sbin/nologin poi
sudo mkdir -p /opt/poi-hub
sudo chown -R poi:poi /opt/poi-hub
sudo -u poi git clone <你的仓库地址> /opt/poi-hub
cd /opt/poi-hub
~~~

如果代码已存在，跳过 clone，但要确保运行用户拥有项目目录和 .data 目录的读写权限。

### 2.2 安装依赖和配置环境

~~~bash
cd /opt/poi-hub
uv sync --frozen
cd frontend
npm ci
cd ..
cp .env.example .env
nano .env
mkdir -p .data
chmod 700 .data
~~~

.env 示例：

~~~dotenv
APP_ENV=production
APP_NAME=POI Hub
DATABASE_URL=sqlite+aiosqlite:////opt/poi-hub/.data/poi_admin.sqlite3
SECRET_KEY=替换为随机的32位以上字符串
ENCRYPTION_KEY=替换为另一组随机的32位以上字符串
LOG_LEVEL=INFO
~~~

### 2.3 迁移和构建

~~~bash
uv run alembic upgrade head
cd frontend
npm run build
cd ..
~~~

生产环境不要执行 uv run python -m poi_admin.seed --reset，该命令会清空数据库，仅适用于演示库或测试库。

### 2.4 创建 systemd 服务

创建 /etc/systemd/system/poi-hub-api.service：

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
RestartSec=5

[Install]
WantedBy=multi-user.target
~~~

创建 /etc/systemd/system/poi-hub-worker.service：

~~~ini
[Unit]
Description=POI Hub background worker
After=network.target poi-hub-api.service

[Service]
Type=simple
User=poi
Group=poi
WorkingDirectory=/opt/poi-hub
EnvironmentFile=/opt/poi-hub/.env
ExecStart=/opt/poi-hub/.venv/bin/python -m poi_admin.worker --poll-seconds 2
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
~~~

加载并启动：

~~~bash
sudo systemctl daemon-reload
sudo systemctl enable --now poi-hub-api.service poi-hub-worker.service
sudo systemctl status poi-hub-api.service poi-hub-worker.service
~~~

查看日志：

~~~bash
sudo journalctl -u poi-hub-api.service -f
sudo journalctl -u poi-hub-worker.service -f
~~~

### 2.5 Nginx、HTTPS 和前端

推荐使用 Nginx 暴露 80/443，API 和 Worker 只监听本机。核心配置如下：

~~~nginx
server {
    listen 80;
    server_name poi.example.com;
    root /opt/poi-hub/frontend/dist;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /callbacks/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
~~~

再使用 Certbot 或企业证书配置 HTTPS。真实微信回调必须使用公网 HTTPS。防火墙只开放 80/443：

~~~bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
~~~

## 三、Windows 部署

以下示例使用 D:\\Services\\POI-Hub 作为部署目录。PowerShell 5.1/7 均可。

### 3.1 获取代码和安装依赖

~~~powershell
New-Item -ItemType Directory -Force D:\\Services\\POI-Hub | Out-Null
Set-Location D:\\Services\\POI-Hub
git clone <你的仓库地址> .
uv sync --frozen
Set-Location frontend
npm.cmd ci
Set-Location ..
~~~

### 3.2 创建 .env

~~~powershell
Set-Location D:\\Services\\POI-Hub
Copy-Item .env.example .env
notepad .env
New-Item -ItemType Directory -Force .data | Out-Null
~~~

.env 示例：

~~~dotenv
APP_ENV=production
APP_NAME=POI Hub
DATABASE_URL=sqlite+aiosqlite:///D:/Services/POI-Hub/.data/poi_admin.sqlite3
SECRET_KEY=替换为随机的32位以上字符串
ENCRYPTION_KEY=替换为另一组随机的32位以上字符串
LOG_LEVEL=INFO
~~~

### 3.3 迁移和构建

~~~powershell
Set-Location D:\\Services\\POI-Hub
uv run alembic upgrade head
Set-Location frontend
npm.cmd run build
Set-Location ..
~~~

生产环境不要执行 uv run python -m poi_admin.seed --reset。

### 3.4 手动启动

API：

~~~powershell
Set-Location D:\\Services\\POI-Hub
& .\\.venv\\Scripts\\python.exe -m uvicorn poi_admin.main:app --app-dir backend --host 127.0.0.1 --port 8000
~~~

Worker：

~~~powershell
Set-Location D:\\Services\\POI-Hub
& .\\.venv\\Scripts\\python.exe -m poi_admin.worker --poll-seconds 2
~~~

前端预览服务：

~~~powershell
Set-Location D:\\Services\\POI-Hub\\frontend
npm.cmd run preview -- --host 127.0.0.1 --port 5173
~~~

上述方式适合内网或临时部署。公网环境建议使用 IIS 或 Windows Nginx 提供 HTTPS、静态文件和反向代理。

### 3.5 使用任务计划程序开机启动

为 API 和 Worker 分别创建任务，选择“系统启动时”触发，并勾选“无论用户是否登录都运行”。两个任务的“起始于”都设置为：

~~~text
D:\\Services\\POI-Hub
~~~

API 程序：

~~~text
D:\\Services\\POI-Hub\\.venv\\Scripts\\python.exe
~~~

API 参数：

~~~text
-m uvicorn poi_admin.main:app --app-dir backend --host 127.0.0.1 --port 8000
~~~

Worker 参数：

~~~text
-m poi_admin.worker --poll-seconds 2
~~~

如果使用专用服务账号，确保该账号对项目目录和 .data 目录有读写权限。IIS/反向代理需要将 /api/ 和 /callbacks/ 转发到 http://127.0.0.1:8000，并为前端路由配置回退到 index.html。

## 四、升级流程

升级前先备份数据库并停止 API/Worker。

Linux：

~~~bash
sudo systemctl stop poi-hub-worker.service poi-hub-api.service
cd /opt/poi-hub
git pull
uv sync --frozen
uv run alembic upgrade head
cd frontend
npm ci
npm run build
cd ..
sudo systemctl start poi-hub-api.service poi-hub-worker.service
~~~

Windows：先停止 API 和 Worker 任务，再执行：

~~~powershell
Set-Location D:\\Services\\POI-Hub
git pull
uv sync --frozen
uv run alembic upgrade head
Set-Location frontend
npm.cmd ci
npm.cmd run build
Set-Location ..
~~~

然后重新启动任务。

## 五、备份和健康检查

停止 Worker 后备份 SQLite 文件：

Linux：

~~~bash
cp /opt/poi-hub/.data/poi_admin.sqlite3 /opt/poi-hub/.data/poi_admin.sqlite3.backup
~~~

Windows：

~~~powershell
Copy-Item D:\\Services\\POI-Hub\\.data\\poi_admin.sqlite3 D:\\Services\\POI-Hub\\.data\\poi_admin.sqlite3.backup
~~~

检查 API：

~~~bash
curl http://127.0.0.1:8000/api/v1/health/live
~~~

Windows PowerShell：

~~~powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health/live
~~~

部署完成后至少验证：

1. 登录页面可以打开。
2. /api/v1/health/live 返回成功。
3. Worker 能处理一条 Mock 或真实连接操作。
4. 操作状态可以从 queued 变为 succeeded 或明确失败状态。
5. 真实微信回调地址能够从公网访问。

## 六、真实微信回调

回调地址为：

~~~text
https://你的域名/api/v1/callbacks/wechat/{connection_id}
~~~

微信平台中的 Token、EncodingAESKey 必须与连接中的 callback_token、encoding_aes_key 一致。回调路径需要经过反向代理转发到 API，不能被前端 SPA 的 index.html 回退规则拦截。

## 七、常见问题

### 操作一直是 queued

确认 Worker 正在运行，并且 API 与 Worker 使用同一个 DATABASE_URL 和同一个 .env。

### 真实连接提示 credentials_missing

确认 Live 连接配置了 AppID 和 AppSecret，并确认 API 与 Worker 的 ENCRYPTION_KEY 一致。

### 回调返回 403

检查公网 URL、Token、时间戳、Nonce、签名和 EncodingAESKey，并确认请求到达 /api/v1/callbacks/wechat/{connection_id}。

### Windows 服务启动后退出

确认任务的“起始于”设置为项目根目录，并使用项目 .venv\\Scripts\\python.exe，而不是系统 Python。

