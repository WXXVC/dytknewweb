# NEWWEB

这是一个不改动原始 `TikTokDownloader` 代码的外置控制层，当前包括：

- `backend`：FastAPI 后端
- `frontend`：自用 Web 管理面板
- 多账号链接存储
- 多下载配置存储
- 扫描账号作品并过滤已下载内容
- 调用原项目作为下载引擎
- 同步面板配置到原项目 `Volume/settings.json`
- 读取原项目 `Volume/DouK-Downloader.db` 的下载历史

## 启动方式

第一次使用先安装依赖：

```powershell
cd NEWWEB\backend
pip install -r requirements.txt
```

### 方式 1：分别启动

启动后端：

```powershell
.\NEWWEB\start_backend.ps1
```

启动前端静态服务：

```powershell
.\NEWWEB\start_frontend.ps1
```

### 方式 2：一键启动

```powershell
.\NEWWEB\start_all.ps1
```

默认地址：

- 后端 API：`http://127.0.0.1:8000`
- Swagger：`http://127.0.0.1:8000/docs`
- 前端页面：`http://127.0.0.1:4173`

## Docker 部署

`NEWWEB` 已提供前后端 Docker 化方案，文件如下：

- `NEWWEB/docker/backend.Dockerfile`
- `NEWWEB/docker/frontend.Dockerfile`
- `NEWWEB/docker/nginx.conf`
- `NEWWEB/docker-compose.yml`
- `NEWWEB/docker-compose.deploy.yml`

### 本地构建部署

`docker-compose.yml` 同时支持本地构建和使用预构建镜像，默认假设：

- 原引擎项目的 `Volume` 挂载目录是 `/ddata/tkdown`
- 面板自己的数据目录使用 `/ddata/tkdown/newweb`
- 原引擎 Web API 通过宿主机 `5555` 端口访问

创建面板数据目录：

```bash
mkdir -p /ddata/tkdown/newweb
```

启动：

```bash
cd NEWWEB
docker compose up -d --build
```

### 单镜像一键部署

默认单镜像地址：

- `ghcr.io/wxxvc/dytknewweb:latest`

一键部署指令：

```bash
docker run -d \
  --name dytknewweb \
  -p 4173:8000 \
  -e ENGINE_API_BASE=http://host.docker.internal:5555 \
  --add-host host.docker.internal:host-gateway \
  -v /ddata/tkdown/newweb:/app/data \
  -v /ddata/tkdown:/app/Volume \
  ghcr.io/wxxvc/dytknewweb:latest
```

这个单镜像会同时提供：

- 前端页面：`http://你的服务器IP:4173`
- 后端 API：`http://你的服务器IP:4173/api`
- Swagger：`http://你的服务器IP:4173/api/docs`

### 双镜像部署

如果你更喜欢前后端分离部署，仍然可以使用 `docker-compose.deploy.yml`：

```bash
mkdir -p /opt/newweb /ddata/tkdown/newweb && cd /opt/newweb && curl -fsSL https://raw.githubusercontent.com/WXXVC/dytknewweb/main/docker-compose.deploy.yml -o docker-compose.deploy.yml && docker compose -f docker-compose.deploy.yml pull && docker compose -f docker-compose.deploy.yml up -d
```

如果你的引擎 API 地址不是宿主机 `5555`，请修改对应 Compose 文件中的 `ENGINE_API_BASE`，或者在启动前通过环境变量覆盖。

## 使用说明

1. 在“下载配置”里新增一个或多个下载配置。
2. 在“账号管理”里新增一个或多个 UP 主主页链接，并绑定下载配置。
3. 进入“扫描结果”选择账号后执行扫描。
4. 默认只显示未下载作品。
5. 勾选“显示已下载作品”后，可以看到被隐藏的历史作品。
6. 可以下载单个作品、选中作品，或者直接整号下载。

## 下载根目录写法

“下载配置”里的“下载根目录”建议按实际运行环境填写：

- Windows 本地直接运行 `NEWWEB` 时，建议填写 Windows 绝对路径，例如：`F:\Media\抖音`
- Linux 直接运行时，建议填写 Linux 绝对路径，例如：`/ddata/tkdown/抖音`
- Linux Docker 部署且引擎卷挂载为 `/ddata/tkdown` 时，容器内推荐填写：`/Volume/抖音`

为避免本地调试时把 Docker 路径误判为无效目录，`NEWWEB` 当前已兼容以下写法：

- `/Volume`
- `/Volume/抖音`
- `Volume/抖音`

它们都会自动映射到当前引擎卷目录下：

- Windows 本地示例：`F:\TKDOWN\Volume\抖音`
- Linux / Docker 示例：`/Volume/抖音`

推荐用法：

- 只在你明确知道宿主机真实路径时，再填写宿主机绝对路径
- 如果你希望同一套配置同时兼容本地调试和 Docker，优先填写 `/Volume/子目录名`
- 如果留空，则会跟随引擎默认下载目录

## 当前实现说明

- 扫描时优先尝试原项目 Web API。
- 如果原项目 Web API 未启动，或者账号链接还无法解析到 `sec_user_id`，会回退到 mock 数据。
- 已下载过滤依赖原项目数据库：`Volume/DouK-Downloader.db`
- 面板自己的存储目前使用：`NEWWEB/data/panel_store.json`
- 任务日志输出目录：`NEWWEB/data/task_logs/`
