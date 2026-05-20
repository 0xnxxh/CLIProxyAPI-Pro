# CLIProxyAPI Pro

CLIProxyAPI Pro 是对两个 upstream 项目的最小化定制层集合：

- `cliproxyapi-pro-core/`：基于 `router-for-me/CLIProxyAPI` 的后端 Docker 构建定制。
- `cliproxyapi-pro-management/`：基于 `router-for-me/Cli-Proxy-API-Management-Center` 的前端管理中心定制。

本项目不维护 upstream 的完整 fork，而是维护可重复应用的 patch、overlay 和构建流程。发布时会拉取 upstream 最新 release，应用本项目定制层，再生成 Pro 版本产物。

## 项目结构

```text
.
├── cliproxyapi-pro-core/
│   ├── Dockerfile
│   ├── entrypoint.sh
│   ├── embeddedusage/
│   └── patches/
│
├── cliproxyapi-pro-management/
│   ├── apply.sh
│   ├── apply_customizations.py
│   ├── monitoring-locales.json
│   └── overlay/
│
└── .github/workflows/
    ├── release-core.yml
    └── release-mangement.yml
```

## 子项目说明

### cliproxyapi-pro-core

后端定制层，用于构建 Pro Docker 镜像。

主要能力：

- 构建 upstream CLIProxyAPI release 的多架构 Docker 镜像。
- 内嵌 SQLite usage service。
- 暴露 `/v0/management/usage` 系列 API，包括状态、增量事件轮询和 SSE 流。
- 支持 usage JSONL/NDJSON 导入导出，包含 usage events、模型价格、quota cache 和账号巡检调度。
- 支持 WebDAV usage 备份恢复。
- 支持 SQLite-backed quota cache。
- 支持模型价格持久化。
- 启动时强制写入必要 upstream 配置：`usage-statistics-enabled=true` 和 Pro 管理面板仓库。
- 支持后端账号巡检调度器和执行器，巡检探测前可刷新 token。
- 支持 Komari agent 可选启动。
- 将 `/` 跳转到 `/management.html`。
- 增强 `/healthz` 返回信息。

详见：

- `cliproxyapi-pro-core/README.md`
- `cliproxyapi-pro-core/README_CN.md`

### cliproxyapi-pro-management

前端管理中心定制层，用于生成单文件 `management.html`。

主要能力：

- 新增 `/monitoring` 请求监控页面。
- 新增 `/account-inspection` 账号巡检页面。
- 请求量、成功率、延迟、token 和成本统计。
- 模型价格 SQLite 持久化。
- quota cache SQLite 持久化。
- 配额卡片缓存时间显示和单卡刷新。
- 对接后端账号巡检，负责运行控制、状态轮询、结果展示和操作确认。
- 账号禁用、启用、删除建议与执行。
- 多语言文案补丁。
- 最小化 overlay + patch 应用流程。

详见：

- `cliproxyapi-pro-management/README.md`
- `cliproxyapi-pro-management/README_CN.md`

## 前后端关系

`cliproxyapi-pro-management` 的部分功能依赖 `cliproxyapi-pro-core` 提供的增强 management API。

核心依赖接口包括：

```text
/v0/management/usage
/v0/management/usage/status
/v0/management/usage/events
/v0/management/usage/stream
/v0/management/usage/export
/v0/management/usage/import
/v0/management/usage/quota-cache
/v0/management/usage/model-prices
/v0/management/account-inspection/schedule
/v0/management/account-inspection/status
/v0/management/account-inspection/logs
/v0/management/account-inspection/run
/v0/management/account-inspection/pause
/v0/management/account-inspection/resume
/v0/management/account-inspection/stop
/v0/management/account-inspection/actions
```

账号巡检只由后端执行。管理端负责配置调度、启动和控制巡检、轮询状态/进度/结果，通过 WebSocket/WSS 接收日志和实时状态，并确认手动操作。

后端巡检时，如果认证记录本来已经进入正常刷新窗口，会在配额/账号探测前尝试刷新 token。巡检刷新路径会跳过 API key 账号、未到刷新窗口的账号，以及仍受 `NextRefreshAfter` 限制的账号；disabled 账号允许刷新。刷新成功后使用刷新后的 auth 继续探测；刷新失败时保留该账号，并跳过该账号本次探测。

后端启动时会强制 `usage-statistics-enabled=true` 和 `remote-management.panel-github-repository=https://github.com/ssfun/CLIProxyAPI-Pro`，并且只在加载到的配置不一致时同步回写 `config.yaml`。

如果只使用 upstream 后端，管理端中的请求监控、SQLite 持久化、模型价格和后端账号巡检等功能会显示错误或空数据。

## 发布流程

### Core 镜像发布

Workflow：

```text
.github/workflows/release-core.yml
```

流程概览：

1. 检查 upstream `router-for-me/CLIProxyAPI` 最新 release。
2. 与 Docker Hub 当前镜像 tag 比较。
3. upstream 更新时构建并推送 Docker 镜像。
4. 备份 usage statistics 到 WebDAV。
5. 触发 Render 部署。
6. 发送 Telegram 通知。
7. 清理旧 workflow runs。

镜像 tag 与 upstream release tag 保持一致。

### Management Release 发布

Workflow：

```text
.github/workflows/release-mangement.yml
```

流程概览：

1. 检查 upstream `router-for-me/Cli-Proxy-API-Management-Center` 最新 release。
2. 与当前仓库最新 release 比较，比较时归一化 `-pro` 后缀。
3. upstream 更新时 checkout 最新 release tag。
4. 应用 `cliproxyapi-pro-management` 定制层。
5. 执行 `npm ci` 和 `npm run build`。
6. 将 `dist/index.html` 重命名为 `management.html`。
7. 创建 GitHub Release 并上传 `management.html`。
8. 清理旧 workflow runs。

Management release tag 格式：

```text
<upstream-tag>-pro
```

示例：

```text
v1.7.41-pro
```

## 本地构建

### 构建 core Docker 镜像

已发布镜像：

```bash
docker pull sfun/cliproxyapi-pro:latest
```

本地构建：

```bash
docker build -t cliproxyapi-pro ./cliproxyapi-pro-core
```

指定 upstream release：

```bash
docker build \
  --build-arg CLIPROXY_VERSION=v6.10.1 \
  -t cliproxyapi-pro:v6.10.1 \
  ./cliproxyapi-pro-core
```

### 应用 management 定制层

```bash
./cliproxyapi-pro-management/apply.sh /path/to/Cli-Proxy-API-Management-Center
```

或：

```bash
python3 ./cliproxyapi-pro-management/apply_customizations.py /path/to/Cli-Proxy-API-Management-Center
```

目标目录必须是 upstream management center checkout，并包含：

- `src/`
- `package.json`

应用后可在目标目录执行：

```bash
npm install
npm run type-check
npm run build
```

## Runtime 数据目录

core 镜像默认使用：

```text
/CLIProxyAPI/usage
```

该目录保存：

- usage SQLite 数据库：`usage.sqlite`
- 账号巡检调度文件：`account-inspection-schedule.json`
- quota cache
- model prices

Usage 导入导出会使用 NDJSON 元数据记录保存模型价格、quota cache 和账号巡检调度，因此 WebDAV 备份恢复可以随 usage events 一起恢复监控相关状态。

建议在生产环境中为该目录配置持久化 volume。

## 关键环境变量

### Usage service

```text
USAGE_SERVICE_ENABLED
USAGE_DATA_DIR
USAGE_DB_PATH
USAGE_BATCH_SIZE
USAGE_POLL_INTERVAL_MS
USAGE_QUERY_LIMIT
```

### WebDAV 恢复

```text
WEBDAV_URL
WEBDAV_USERNAME
WEBDAV_PASSWORD
MANAGEMENT_PASSWORD
```

### 账号巡检

```text
ACCOUNT_INSPECTION_SCHEDULE_PATH
```

### Komari agent

```text
KOMARI_SERVER
KOMARI_SECRET
```

完整说明见 `cliproxyapi-pro-core/README_CN.md`。

## 设计原则

本项目遵循最小化定制原则：

- 不复制 upstream 完整源码。
- 尽量通过 overlay 和 patch 注入功能。
- upstream 更新时重新应用定制层。
- 文档、脚本和 workflow 尽量保持可验证、可重复。

## 版权与鸣谢

本仓库是围绕 upstream 项目的定制层和发布流程，不声明拥有 upstream 代码、名称或资源的版权。upstream 代码和产物仍保留其原始版权声明和许可证。

- `router-for-me/CLIProxyAPI` 使用 MIT License。其 upstream `LICENSE` 当前声明：
  - Copyright (c) 2025-2005.9 Luis Pater
  - Copyright (c) 2025.9-present Router-For.ME
- `router-for-me/Cli-Proxy-API-Management-Center` 使用 MIT License。其 upstream `LICENSE` 当前声明：
  - Copyright (c) 2026 Router-For.ME

特别鸣谢：

- [router-for-me/CLIProxyAPI](https://github.com/router-for-me/CLIProxyAPI) — 本项目 core 定制层所基于的 upstream 后端项目。
- [router-for-me/Cli-Proxy-API-Management-Center](https://github.com/router-for-me/Cli-Proxy-API-Management-Center) — 本项目 management 定制层所基于的 upstream 管理 UI 项目。
- [seakee/CPA-Manager](https://github.com/seakee/CPA-Manager) — 重要的 CLIProxyAPI 管理与监控项目，对 Pro usage、monitoring 和账号巡检方向提供了参考。

## 参考文档

- Core 中文文档：`cliproxyapi-pro-core/README.md`
- Core English README：`cliproxyapi-pro-core/README_EN.md`
- Management 中文文档：`cliproxyapi-pro-management/README.md`
- Management English README：`cliproxyapi-pro-management/README_EN.md`
- English project overview：`README.md_EN`
