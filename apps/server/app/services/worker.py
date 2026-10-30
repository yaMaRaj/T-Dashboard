"""Playwright 工作子进程入口。

由 RunExecutor 通过 ``python -m app.services.worker <job> <result> [events]`` 拉起。
与 uvicorn 进程隔离，避免 Windows 上 asyncio 事件循环无法 spawn Chromium。

数据流：
  读 job.json → 调用 execute_cases_sync → 写 result.json
  执行过程中通过 on_event 追加 events.jsonl，供 API 推给前端 WebSocket。
日志文件：data/logs/tdashboard-worker.log
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    """子进程主函数。返回进程退出码：0 成功，2 参数错误。"""
    # 尽早初始化日志，这样后续 import / 崩溃也能落盘
    from app.logging_setup import get_logger, setup_logging

    setup_logging(process="worker")
    log = get_logger("worker")

    # —— 参数校验：至少要有 job 路径和 result 路径 ——
    if len(sys.argv) < 3:
        log.error("Usage: python -m app.services.worker <job.json> <result.json> [events.jsonl]")
        print("Usage: python -m app.services.worker <job.json> <result.json> [events.jsonl]")
        return 2

    # argv[1]=任务描述，argv[2]=结果输出，argv[3] 可选=事件流文件
    job_path = Path(sys.argv[1])
    result_path = Path(sys.argv[2])
    # 未传 events 时，默认与 result 同目录、后缀改为 .events.jsonl
    events_path = Path(sys.argv[3]) if len(sys.argv) > 3 else result_path.with_suffix(".events.jsonl")

    log.info("worker start job=%s result=%s events=%s", job_path, result_path, events_path)

    # 读取任务 JSON（含 cases、browser、cancel_file 等）
    job = json.loads(job_path.read_text(encoding="utf-8"))
    run_id = int(job.get("run_id", 0))
    log.info(
        "run_id=%s cases=%s headless=%s browser=%s",
        run_id,
        len(job.get("cases") or []),
        job.get("headless", True),
        job.get("browser", "chromium"),
    )

    # 清空（或创建）事件文件，避免读到上一次残留
    events_path.write_text("", encoding="utf-8")

    def on_event(event: dict) -> None:
        """把一条事件以 JSONL 追加写入；API 侧轮询此文件并 publish 到 WebSocket。"""
        with events_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")

    # 延迟导入：保证 logging 已就绪，且缩短「参数错误」时的启动成本
    from app.services.step_runner_sync import execute_cases_sync, finish_keep_alive_browser

    # 取消约定：父进程写 cancel_file；执行循环里 should_cancel() 检查文件是否存在
    cancel_file = Path(job.get("cancel_file") or "")

    def should_cancel() -> bool:
        # 未配置 cancel_file 时永远不取消
        return cancel_file.exists() if cancel_file else False

    headless = bool(job.get("headless", True))
    # 有头模式默认跑完后保持浏览器，方便人工接管；可用 job 字段覆盖
    keep_browser_open = bool(job.get("keep_browser_open", not headless))

    # —— 真正执行全部用例 ——
    try:
        outcome = execute_cases_sync(
            browser_name=job.get("browser", "chromium"),
            headless=headless,
            timeout_ms=int(job.get("timeout_ms", 30000)),
            base_url=job.get("base_url", ""),
            cases=job.get("cases", []),
            run_id=run_id,
            should_cancel=should_cancel,
            on_event=on_event,
            capture_screenshots=bool(job.get("capture_screenshots", False)),
            record_video=bool(job.get("record_video", False)),
            keep_browser_open=keep_browser_open,
        )
    except Exception:
        # 未捕获异常：记日志后重新抛出，让进程非 0 退出，父进程据此写失败摘要
        log.exception("run_id=%s execute_cases_sync crashed", run_id)
        raise

    # 先落盘结果：父进程看到 result.json 即可把 Run 标为终态；
    # 若 keep_browser_open，浏览器可能还开着，但 UI 已能看结果。
    result_path.write_text(json.dumps(outcome, ensure_ascii=False), encoding="utf-8")
    log.info(
        "run_id=%s result written status_summary passed=%s failed=%s cancelled=%s keep_open=%s",
        run_id,
        outcome.get("passed"),
        outcome.get("failed"),
        outcome.get("cancelled"),
        outcome.get("keep_browser_open"),
    )
    # 通知 UI：自动化阶段结束
    on_event(
        {
            "type": "log",
            "run_id": run_id,
            "level": "info",
            "message": "结果已写入，自动化阶段结束。",
        }
    )

    # 有头 keep-alive：阻塞直到用户关掉浏览器窗口（或 cancel）
    if outcome.get("keep_browser_open"):
        log.info("run_id=%s waiting for headed browser close", run_id)
        finish_keep_alive_browser()
        log.info("run_id=%s browser closed, worker exit", run_id)

    return 0


if __name__ == "__main__":
    # 把 main 的返回值作为进程退出码
    raise SystemExit(main())
