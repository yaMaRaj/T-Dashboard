# T-Dashboard

本机 Playwright 自动化测试控制台：用 Vue 编排用例步骤，用 FastAPI + Playwright（Python）在本机执行，并查看结果、基础分析与 **Allure** 报告。模型可通过 MCP 调用执行与报告能力。

## 技术栈

- 前端：Vue 3 + Vite + TypeScript + Pinia + Vue Router
- 后端：Python + FastAPI + SQLAlchemy + SQLite
- 执行：Playwright for Python
- 报告：Allure 2（results 自动写出，HTML 按需生成）
- MCP：
  - [`mcp-playwright/`](mcp-playwright/) — 列项目/用例、发起与取消运行、查结果
  - [`mcp-allure/`](mcp-allure/) — Allure summary / 生成 HTML / 失败用例

## 常用脚本（推荐）

按操作系统分目录（功能一致：`dev` / `restart` / `stop` / `build`）：

```
scripts/
  windows/   *.ps1
  linux/     *.sh
  macos/     *.sh
```

| 脚本 | 作用 |
|------|------|
| `dev` | 首次/日常启动：自动建 venv、装依赖，拉起 API `:8000` + Web `:5173` |
| `restart` | 结束占用 8000/5173 的进程后重新启动前后端 |
| `stop` | 仅停止前后端（按端口杀进程） |
| `build` | 前端生产打包 → `apps/web/dist` |
| `install-allure` | 安装项目内 Allure CLI（`tools/allure`，需 Java 8+） |

### Windows（PowerShell）

```powershell
.\scripts\windows\dev.ps1
.\scripts\windows\restart.ps1
.\scripts\windows\stop.ps1
.\scripts\windows\build.ps1
.\scripts\windows\install-allure.ps1
```

### Linux

```bash
chmod +x scripts/linux/*.sh   # 首次
./scripts/linux/dev.sh
./scripts/linux/restart.sh
./scripts/linux/stop.sh
./scripts/linux/build.sh
./scripts/linux/install-allure.sh
```

### macOS

```bash
chmod +x scripts/macos/*.sh   # 首次
./scripts/macos/dev.sh
./scripts/macos/restart.sh
./scripts/macos/stop.sh
./scripts/macos/build.sh
./scripts/macos/install-allure.sh
```

开发地址：http://localhost:5173 · API：http://127.0.0.1:8000 · 健康检查：`/api/health`  
Linux/macOS 的 `restart` 会把日志写到仓库根目录 `.run/`（已 gitignore）。

## 快速开始（手动）

### 1. 后端

```powershell
cd apps/server
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m playwright install chromium
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

> Windows 说明：若 `playwright install` 下载 headless-shell 较慢，只要 `chromium-*/chrome-win64/chrome.exe` 已就绪即可。Runner 会回退使用完整 Chromium + `--headless=new`，并通过独立子进程执行，避免 uvicorn 事件循环限制。

### 2. 前端（开发）

```powershell
cd apps/web
npm install
npm run dev
```

浏览器打开：http://localhost:5173

### 3. 前端打包与预览

```powershell
# 方式 A：脚本（Windows）
.\scripts\windows\build.ps1
# Linux: ./scripts/linux/build.sh
# macOS: ./scripts/macos/build.sh

# 方式 B：手动
cd apps/web
npm run build          # 产出 dist/
npm run preview        # 本地预览打包结果（默认 :4173）
```

生产环境仍需单独启动后端（建议去掉 `--reload`）：

```powershell
cd apps/server
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

将 `dist` 交给任意静态服务器，并把 `/api`、`/artifacts`、`/ws` 反向代理到 `127.0.0.1:8000`（开发时由 Vite `proxy` 完成）。

### 4. 手动重启（不走脚本）

```powershell
# 停掉占用端口的进程
Get-NetTCPConnection -LocalPort 8000,5173 -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }

# 再分别启动后端 / 前端（见上文），或：
.\scripts\windows\restart.ps1
```

### 5. Allure CLI（生成 HTML 报告）

运行结束后会自动写入 `artifacts/run-{id}/allure-results/`。在运行详情页点击 **Allure 报告**，或调用 API / mcp-allure 时，才会执行 `allure generate` 产出 HTML。

**依赖**：本机需已安装 **Java 8+**（`java -version`）与 Node（用于安装 CLI）。

推荐安装到项目内 `tools/allure`（无需 scoop/choco）：

```powershell
# Windows
.\scripts\windows\install-allure.ps1

# Linux
./scripts/linux/install-allure.sh

# macOS
./scripts/macos/install-allure.sh
```

也可用全局：`npm i -g allure-commandline@2.25.0`，或见 https://docs.qameta.io/allure/#_installing_a_commandline

安装后若 API 已在跑，重启一次后端再点报告。报告地址示例：`http://127.0.0.1:8000/artifacts/run-1/allure-report/index.html`。

### 6. MCP（给模型调用）

#### mcp-playwright（执行）

```powershell
cd mcp-playwright
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
```

常用工具：`playwright_list_projects`、`playwright_list_cases`、`playwright_run_cases`、`playwright_get_run`、`playwright_cancel_run` 等。详见 [`mcp-playwright/README.md`](mcp-playwright/README.md)。

#### mcp-allure（报告）

```powershell
cd mcp-allure
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
```

常用工具：`allure_list_runs`、`allure_get_summary`、`allure_generate_report`、`allure_get_report_url`、`allure_get_failed_cases`。

#### Cursor 一并配置

示例见 [`mcp-playwright/mcp.json.example`](mcp-playwright/mcp.json.example)（含 playwright + allure）。环境变量 `TDASHBOARD_API` 默认 `http://127.0.0.1:8000`。

典型 Agent 流程：`playwright_run_cases` → 轮询 `playwright_get_run` → `allure_generate_report` / `allure_get_summary`。

## 功能（MVP）

- 项目 / 用例 CRUD
- 可视化步骤编排（导航、点击、填写、断言等）
- 创建任务并立即执行（本机 Chromium）
- 运行详情：逐步结果、失败截图、WebSocket 实时日志、Allure 报告入口
- 运行历史与基础分析（通过率、失败类型、慢用例）
- 首次启动自动写入 Demo 项目
- Allure results 自动落盘 + 按需 HTML
- mcp-playwright / mcp-allure 供 Agent 调用

## API（Allure）

| Method | Path | 说明 |
|--------|------|------|
| GET | `/api/runs/{id}/allure` | 报告状态 + summary |
| POST | `/api/runs/{id}/allure/generate` | 生成 HTML |
| GET | `/api/runs/{id}/allure/failed-cases` | 失败用例列表 |

## 目录

```
apps/web            Vue 前端（打包输出 apps/web/dist）
apps/server         FastAPI 后端
mcp-playwright/     MCP server（Playwright 执行）
mcp-allure/         MCP server（Allure 报告）
scripts/windows/    Windows 脚本（*.ps1）
scripts/linux/      Linux 脚本（*.sh）
scripts/macos/      macOS 脚本（*.sh）
shared/             步骤 JSON Schema
artifacts/          运行产物（截图、allure-results、allure-report）
data/               SQLite 数据库
data/logs/          后端滚动日志（tdashboard.log / tdashboard-worker.log）
.run/               Linux/macOS restart 日志与 pid（本地）
```

## 日志

### 后端

- 控制台（stderr）+ 文件：`data/logs/tdashboard.log`（API）、`data/logs/tdashboard-worker.log`（Playwright 子进程）
- 级别：环境变量 `TDASHBOARD_LOG_LEVEL`（默认 `INFO`，可设 `DEBUG`）
- 关键路径已打点：HTTP 请求、任务入队、运行起停/取消、用例结果、Allure 生成、WebSocket 订阅

### 前端

- 开发模式会输出 boot / 路由 / API 调试信息到浏览器控制台
- 强制打开详细日志：`localStorage.setItem('TDASHBOARD_DEBUG','1')` 后刷新
