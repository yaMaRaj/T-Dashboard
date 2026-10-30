"""统一日志初始化（API 进程与 worker 子进程共用）。

输出：
  - stderr：方便本机跑 uvicorn 时直接看
  - 滚动文件：data/logs/tdashboard.log 或 tdashboard-worker.log（单文件约 5MB，保留 5 份）

环境变量 TDASHBOARD_LOG_LEVEL：DEBUG / INFO / WARNING / ERROR，默认 INFO。
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from app.config import LOG_DIR

# 防止 uvicorn --reload 或重复 import 时挂两套 handler
_CONFIGURED = False


def setup_logging(*, process: str = "api") -> None:
    """配置 root logger。同一进程内多次调用只会生效一次。

    process=\"worker\" 时写 worker 专用日志文件，避免与 API 日志互相冲刷难查。
    """
    global _CONFIGURED
    # 已配置则直接返回（幂等）
    if _CONFIGURED:
        return
    _CONFIGURED = True

    # 读环境变量；非法名字时 getattr 回落到 INFO
    level_name = (os.environ.get("TDASHBOARD_LOG_LEVEL") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    # 确保日志目录存在
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    # 按进程类型选择文件名
    log_file = LOG_DIR / ("tdashboard-worker.log" if process == "worker" else "tdashboard.log")

    # 统一格式：时间 | 级别 | logger 名 | 消息
    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(level)
    # 清掉可能已有的默认 handler，避免重复打印
    root.handlers.clear()

    # —— 控制台 handler ——
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(level)
    console.setFormatter(fmt)
    root.addHandler(console)

    # —— 文件 handler（按大小滚动）——
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    # 压低第三方库噪音，突出业务日志
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("watchfiles").setLevel(logging.WARNING)

    # 首条业务日志：确认级别与落盘路径
    logging.getLogger("tdashboard").info(
        "logging ready process=%s level=%s file=%s", process, level_name, log_file
    )


def get_logger(name: str) -> logging.Logger:
    """返回 ``tdashboard.<name>`` 命名空间下的 logger，便于按模块过滤。"""
    # 已带前缀则不再拼，避免 tdashboard.tdashboard.xxx
    if not name.startswith("tdashboard"):
        name = f"tdashboard.{name}"
    return logging.getLogger(name)
