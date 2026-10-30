"""T-Dashboard FastAPI 入口。

启动顺序（lifespan）：
  1. setup_logging（模块 import 时已调用）
  2. init_db → 建表 + SQLite 列迁移
  3. seed_demo_if_empty → 保证内置 Demo 项目存在
  4. recover_stale_runs → 把上次进程残留的 running/pending 标 cancelled
  5. job_queue.start → 开始串行消费 Run

关闭：job_queue.stop。

路由：/api/* 业务；/artifacts 静态产物；/ws/runs/{id} 在 ws 模块。
"""

from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import analytics, cases, projects, runs, tasks, ws
from app.config import ARTIFACTS_DIR, CORS_ORIGINS
from app.db.session import init_db
from app.logging_setup import get_logger, setup_logging
from app.services.queue import job_queue
from app.services.seed import recover_stale_runs, seed_demo_if_empty

# 进程级日志：必须在其它业务 import 副作用之前就绪
setup_logging(process="api")
log = get_logger("api")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """应用生命周期：启动初始化 → yield 服务请求 → 关闭队列。"""
    log.info("startup begin")
    await init_db()
    log.info("database ready")
    await seed_demo_if_empty()
    # 重启后若库里还有「半截」Run，会永远卡在 UI；这里统一改成 cancelled
    recovered = await recover_stale_runs()
    if recovered:
        log.warning("recovered %s stale run(s) → cancelled", recovered)
    await job_queue.start()
    log.info("job queue started")
    yield
    log.info("shutdown begin")
    await job_queue.stop()
    log.info("shutdown complete")


app = FastAPI(title="T-Dashboard", version="0.1.0", lifespan=lifespan)

# 允许本地 Vite 开发源跨域访问 API
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """记录每个业务请求的方法、路径、状态码与耗时。

    跳过：/artifacts（静态文件量大）、/api/health（前端轮询噪音）。
    未捕获异常：打 exception 后继续向上抛，交给 FastAPI 错误处理。
    """
    path = request.url.path
    if path.startswith("/artifacts") or path == "/api/health":
        return await call_next(request)

    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        ms = (time.perf_counter() - started) * 1000
        log.exception(
            "request failed %s %s (%.1fms)",
            request.method,
            path,
            ms,
        )
        raise
    ms = (time.perf_counter() - started) * 1000
    # 4xx/5xx 用 warning，便于扫日志时突出失败请求
    level = log.warning if response.status_code >= 400 else log.info
    level(
        "%s %s → %s (%.1fms)",
        request.method,
        path,
        response.status_code,
        ms,
    )
    return response


# 注册各业务路由模块
app.include_router(projects.router)
app.include_router(cases.router)
app.include_router(tasks.router)
app.include_router(runs.router)
app.include_router(analytics.router)
app.include_router(ws.router)

# 运行产物目录：截图、录像、allure-report 等通过 HTTP 直接读文件
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/artifacts", StaticFiles(directory=str(ARTIFACTS_DIR)), name="artifacts")


@app.get("/api/health")
async def health() -> dict:
    """探活：进程能响应即返回 ok（不做 DB/浏览器探测）。"""
    return {"status": "ok"}


@app.get("/api/playwright/status")
async def playwright_status() -> dict:
    """探测本机是否已有可用 Chromium，供前端顶栏提示安装指引。"""
    from app.services.step_runner_sync import _chromium_executable

    exe = _chromium_executable()
    if exe:
        log.debug("playwright chromium ready: %s", exe)
        return {"installed": True, "message": f"Chromium ready: {exe}"}
    log.warning("playwright chromium executable not found")
    return {
        "installed": False,
        "message": "Chromium executable not found",
        "hint": "Run: cd apps/server && .\\.venv\\Scripts\\python.exe -m playwright install chromium",
    }
