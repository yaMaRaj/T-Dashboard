"""单次 Run 的编排器：拉起 Playwright worker 子进程、转发事件、落库结果。

调用链：JobQueue._loop → RunExecutor.execute(run_id)
  → 写 job.json → Popen(worker) → 轮询 events.jsonl / result.json → 写 CaseResult + Run 状态
取消：request_cancel 写 .cancel + taskkill /T（Windows）强制杀掉浏览器进程树。
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import DATA_DIR
from app.db.session import SessionLocal
from app.logging_setup import get_logger
from app.models.entities import Case, CaseResult, Project, Run, Task
from app.services.allure_report import write_results_for_run
from app.services.events import event_hub

log = get_logger("runner")


async def _write_allure(db, run: Run) -> None:
    """尽力写入 Allure results JSON（失败只记日志，不阻断 Run 终态）。

    HTML 报告按需生成，因此这里清空 allure_report_path，避免指向过期 HTML。
    """
    try:
        # 查出本 run 下所有用例结果，交给 allure_report 写 *-result.json
        crs = list(
            (
                await db.execute(select(CaseResult).where(CaseResult.run_id == run.id))
            ).scalars().all()
        )
        path = write_results_for_run(run, crs)
        run.allure_results_path = path
        # results 重写后旧 HTML 失效
        run.allure_report_path = ""
        await db.commit()
        log.info("run_id=%s allure-results written path=%s", run.id, path)
        # 同步推一条 UI 日志
        await event_hub.publish(
            run.id,
            {
                "type": "log",
                "run_id": run.id,
                "level": "info",
                "message": f"Allure results 已写入: {path}",
            },
        )
    except Exception as exc:  # noqa: BLE001
        # 不向上抛：Allure 失败不应把已经成功的 Run 打成异常
        log.exception("run_id=%s allure-results write failed", run.id)
        await event_hub.publish(
            run.id,
            {
                "type": "log",
                "run_id": run.id,
                "level": "error",
                "message": f"写入 Allure results 失败: {exc}",
            },
        )


def _utc_now() -> datetime:
    """当前 UTC 时间，去掉 tzinfo 以兼容 SQLite 存 naive datetime。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class RunExecutor:
    """管理「正在跑的」runs：取消标志集合 + 子进程句柄映射。"""

    def __init__(self) -> None:
        # 已被用户请求取消的 run_id；execute 循环与 worker 等待都会查它
        self._cancel_flags: set[int] = set()
        # run_id → 当前 worker Popen，供 request_cancel 强杀
        self._procs: dict[int, subprocess.Popen[str]] = {}

    def request_cancel(self, run_id: int) -> None:
        """取消入口（API cancel 调用）。

        步骤：
        1. 把 run_id 放进 _cancel_flags（内存软取消）
        2. 写 cancel 文件（worker 里 should_cancel 读文件）
        3. 若子进程还活着 → _kill_process_tree 硬杀
        """
        log.warning("cancel requested run_id=%s", run_id)
        self._cancel_flags.add(run_id)
        cancel_file = DATA_DIR / "jobs" / f"run-{run_id}.cancel"
        cancel_file.parent.mkdir(parents=True, exist_ok=True)
        cancel_file.write_text("1", encoding="utf-8")
        proc = self._procs.get(run_id)
        # poll() is None 表示进程尚未退出
        if proc is not None and proc.poll() is None:
            log.info("killing worker pid=%s for run_id=%s", proc.pid, run_id)
            self._kill_process_tree(proc)
        else:
            log.info("no live worker process for run_id=%s (pending or already exited)", run_id)

    @staticmethod
    def _kill_process_tree(proc: subprocess.Popen[str]) -> None:
        """尽力杀掉 worker 及其子进程（Chromium）。

        Windows：taskkill /F /T 杀整棵进程树。
        其它平台：proc.kill()。
        最后关闭 stdout/stderr 并 wait，避免僵尸/管道阻塞。
        """
        if sys.platform == "win32":
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=10,
                )
            except Exception:  # noqa: BLE001
                # taskkill 失败时仍尝试下面的 kill
                pass
        try:
            if proc.poll() is None:
                proc.kill()
        except Exception:  # noqa: BLE001
            pass
        # 关掉管道，防止读者阻塞
        try:
            if proc.stdout:
                proc.stdout.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            if proc.stderr:
                proc.stderr.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            proc.wait(timeout=3)
        except Exception:  # noqa: BLE001
            pass

    async def execute(self, run_id: int) -> None:
        """执行一次完整 Run（由队列串行调用）。

        大阶段：
        A. 加载 Run/Task/Project/Cases，处理「启动前已取消」
        B. 标 running，写 job 文件，Popen worker
        C. 异步轮询：转发 events、提前落库 result、响应取消
        D. worker 退出后补齐落库与清理
        """
        async with SessionLocal() as db:
            # —— A1. 加载 Run，并 eager-load task.project ——
            result = await db.execute(
                select(Run)
                .where(Run.id == run_id)
                .options(selectinload(Run.task).selectinload(Task.project))
            )
            run = result.scalar_one_or_none()
            if not run:
                log.error("execute: run_id=%s not found", run_id)
                return

            task: Task = run.task
            project: Project = task.project

            # —— A2. 按 task.case_ids 顺序取出仍启用的用例 ——
            cases_result = await db.execute(
                select(Case).where(
                    Case.project_id == project.id,
                    Case.id.in_(task.case_ids or []),
                    Case.enabled.is_(True),
                )
            )
            cases = list(cases_result.scalars().all())
            case_map = {c.id: c for c in cases}
            # 保持任务里配置的顺序；已删除/禁用的 id 直接跳过
            ordered_cases = [case_map[cid] for cid in (task.case_ids or []) if cid in case_map]
            log.info(
                "execute run_id=%s task=%s project=%s cases=%s headless=%s browser=%s",
                run_id,
                task.name,
                project.name,
                [c.id for c in ordered_cases],
                task.headless,
                task.browser,
            )

            # —— A3. 入队后、启动子进程前就被取消：直接终态返回 ——
            if run_id in self._cancel_flags:
                log.warning("run_id=%s cancelled before worker start", run_id)
                run.status = "cancelled"
                run.started_at = _utc_now()
                run.finished_at = _utc_now()
                run.total = len(ordered_cases)
                run.error_summary = "Cancelled by user"
                await db.commit()
                await event_hub.publish(
                    run_id,
                    {
                        "type": "run_finished",
                        "run_id": run_id,
                        "status": "cancelled",
                        "passed": 0,
                        "failed": 0,
                        "skipped": run.total,
                        "duration_ms": 0,
                    },
                )
                self._cancel_flags.discard(run_id)
                return

            # —— B1. 标记 running 并广播 run_started ——
            run.status = "running"
            run.started_at = _utc_now()
            run.total = len(ordered_cases)
            await db.commit()

            await event_hub.publish(
                run_id,
                {"type": "run_started", "run_id": run_id, "total": run.total},
            )

            # —— B2. 准备 worker 交换文件（job / result / events / cancel）——
            jobs_dir = DATA_DIR / "jobs"
            jobs_dir.mkdir(parents=True, exist_ok=True)
            job_path = jobs_dir / f"run-{run_id}.job.json"
            result_path = jobs_dir / f"run-{run_id}.result.json"
            events_path = jobs_dir / f"run-{run_id}.events.jsonl"
            cancel_file = jobs_dir / f"run-{run_id}.cancel"
            # 清掉历史残留的 cancel，但本轮刚点了取消则保留
            if cancel_file.exists() and run_id not in self._cancel_flags:
                cancel_file.unlink()

            # —— B3. 组装传给 worker 的 job 字典 ——
            job = {
                "run_id": run_id,
                "browser": task.browser,
                "headless": task.headless,
                "timeout_ms": task.timeout_ms,
                "base_url": project.base_url,
                "capture_screenshots": bool(getattr(task, "capture_screenshots", False)),
                "record_video": bool(getattr(task, "record_video", False)),
                # 有头模式：自动化结束后保持窗口，便于人工接管
                "keep_browser_open": not bool(task.headless),
                "cancel_file": str(cancel_file),
                "cases": [
                    {
                        "id": c.id,
                        "name": c.name,
                        "mode": getattr(c, "mode", None) or "steps",
                        "steps": c.steps or [],
                        "script": getattr(c, "script", None) or "",
                    }
                    for c in ordered_cases
                ],
            }
            job_path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
            # 删掉旧 result，避免误读上一次运行
            if result_path.exists():
                result_path.unlink()
            events_path.write_text("", encoding="utf-8")
            log.debug(
                "run_id=%s job files job=%s result=%s events=%s",
                run_id,
                job_path,
                result_path,
                events_path,
            )

            # —— B4. 配置 Popen：工作目录为 apps/server，stdout/stderr 丢弃（日志走 events）——
            server_dir = Path(__file__).resolve().parents[2]
            python_exe = sys.executable
            popen_kwargs: dict = {
                "cwd": str(server_dir),
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
            if sys.platform == "win32":
                # 独立进程组，方便 taskkill /T 连带杀 Chromium
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

            def _run_worker() -> subprocess.CompletedProcess[str]:
                """在线程里阻塞等待 worker；可被 cancel 标志打断并杀进程。"""
                proc = subprocess.Popen(
                    [
                        python_exe,
                        "-m",
                        "app.services.worker",
                        str(job_path),
                        str(result_path),
                        str(events_path),
                    ],
                    **popen_kwargs,
                )
                # 登记句柄，供 request_cancel 查找
                self._procs[run_id] = proc
                log.info("run_id=%s worker spawned pid=%s", run_id, proc.pid)
                try:
                    # 每 250ms 看一次：进程是否退出 / 是否要取消
                    while proc.poll() is None:
                        if run_id in self._cancel_flags:
                            log.warning("run_id=%s cancel during worker wait", run_id)
                            RunExecutor._kill_process_tree(proc)
                            break
                        time.sleep(0.25)
                    # 再给一点时间收尸
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        RunExecutor._kill_process_tree(proc)
                        try:
                            proc.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            pass
                    # 伪装成 CompletedProcess，方便外层统一读 returncode
                    return subprocess.CompletedProcess(
                        args=[
                            python_exe,
                            "-m",
                            "app.services.worker",
                            str(job_path),
                            str(result_path),
                            str(events_path),
                        ],
                        returncode=proc.returncode if proc.returncode is not None else -1,
                        stdout="",
                        stderr="",
                    )
                finally:
                    # 无论正常/取消，都从映射里摘掉
                    self._procs.pop(run_id, None)

            # offset：已读过的 events 文件字节偏移，实现增量推送
            offset = 0
            # results_persisted：是否已经把 outcome 写入 DB（有头 keep-alive 会提前写）
            results_persisted = False
            # 把阻塞的 _run_worker 丢到线程池，避免卡住 asyncio 循环
            worker_task = asyncio.create_task(asyncio.to_thread(_run_worker))

            def _events_to_logs() -> list[dict]:
                """把 events.jsonl 转成存进 Run.logs 的精简结构（给人看的摘要）。"""
                rows: list[dict] = []
                if not events_path.exists():
                    return rows
                for raw in events_path.read_text(encoding="utf-8").splitlines():
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        ev = json.loads(raw)
                    except json.JSONDecodeError:
                        # 半行或损坏行直接跳过
                        continue
                    et = ev.get("type")
                    if et == "ping":
                        continue
                    if et == "log":
                        rows.append(
                            {
                                "type": "log",
                                "level": ev.get("level", "info"),
                                "message": ev.get("message", ""),
                            }
                        )
                    elif et == "case_started":
                        rows.append(
                            {
                                "type": et,
                                "level": "info",
                                "message": f"→ 开始用例: {ev.get('case_name', '')}",
                            }
                        )
                    elif et == "case_finished":
                        rows.append(
                            {
                                "type": et,
                                "level": "info",
                                "message": (
                                    f"← 结束用例: {ev.get('case_name', '')} "
                                    f"({ev.get('status', '')})"
                                ),
                            }
                        )
                    elif et == "run_started":
                        rows.append(
                            {
                                "type": et,
                                "level": "info",
                                "message": f"■ 运行开始，共 {ev.get('total', 0)} 条用例",
                            }
                        )
                    elif et == "run_finished":
                        rows.append(
                            {
                                "type": et,
                                "level": "info",
                                "message": f"■ 运行结束: {ev.get('status', '')}",
                            }
                        )
                    elif et == "run_error":
                        rows.append(
                            {
                                "type": et,
                                "level": "error",
                                "message": ev.get("message", ""),
                            }
                        )
                return rows

            async def _publish_cancelled() -> None:
                """向 WebSocket 订阅者广播「已取消」终态。"""
                await event_hub.publish(
                    run_id,
                    {
                        "type": "run_finished",
                        "run_id": run_id,
                        "status": "cancelled",
                        "passed": run.passed,
                        "failed": run.failed,
                        "skipped": run.skipped,
                        "duration_ms": run.duration_ms,
                    },
                )

            async def _force_cancelled_status() -> None:
                """立刻把 DB 标成 cancelled，避免 UI 卡在 cancelling。"""
                nonlocal results_persisted
                # 幂等：已是 cancelled 则不再写库
                if run.status == "cancelled":
                    return
                run.status = "cancelled"
                run.finished_at = _utc_now()
                run.logs = _events_to_logs()
                if not run.error_summary:
                    run.error_summary = "Cancelled by user"
                # 视为已落库，后续 worker 退出不再用成功路径覆盖
                results_persisted = True
                await db.commit()
                await event_hub.publish(
                    run_id,
                    {
                        "type": "log",
                        "run_id": run_id,
                        "level": "info",
                        "message": "运行已取消，已终止浏览器进程。",
                    },
                )
                await _write_allure(db, run)
                await _publish_cancelled()

            async def _persist_outcome(outcome: dict) -> None:
                """把 worker 产出的 outcome 写入 CaseResult + 更新 Run 汇总字段。"""
                nonlocal results_persisted
                # 已落库过（例如 keep-alive 提前写）：只允许取消覆盖，或刷新 logs
                if results_persisted:
                    if outcome.get("cancelled") or run_id in self._cancel_flags:
                        await _force_cancelled_status()
                    elif run.status == "cancelled":
                        run.logs = _events_to_logs()
                        await db.commit()
                    return

                results_persisted = True
                # 逐条插入用例结果行
                for payload in outcome.get("case_payloads") or []:
                    db.add(
                        CaseResult(
                            run_id=run.id,
                            case_id=payload["case_id"],
                            case_name=payload["case_name"],
                            status=payload["status"],
                            duration_ms=payload["duration_ms"],
                            error_message=payload["error_message"],
                            error_type=payload["error_type"],
                            screenshot_path=payload["screenshot_path"],
                            step_results=payload["step_results"],
                            artifacts=payload.get("artifacts") or [],
                        )
                    )

                # 汇总计数与错误摘要
                run.passed = outcome.get("passed", 0)
                run.failed = outcome.get("failed", 0)
                run.skipped = outcome.get("skipped", 0)
                run.duration_ms = outcome.get("duration_ms", 0)
                run.error_summary = outcome.get("error_summary", "")
                run.logs = _events_to_logs()

                # 终态分支：取消 / 无用例但有错误 / 按 failed 计数判定
                if outcome.get("cancelled") or run_id in self._cancel_flags:
                    run.status = "cancelled"
                    if not run.error_summary:
                        run.error_summary = "Cancelled by user"
                elif run.error_summary and not outcome.get("case_payloads"):
                    # worker 崩了：没有 case_payloads，但有 error_summary
                    run.status = "failed"
                else:
                    run.status = "failed" if run.failed else "passed"

                run.finished_at = _utc_now()
                await db.commit()
                log.info(
                    "run_id=%s persisted status=%s passed=%s failed=%s skipped=%s duration_ms=%s",
                    run_id,
                    run.status,
                    run.passed,
                    run.failed,
                    run.skipped,
                    run.duration_ms,
                )
                await _write_allure(db, run)

                # 通知前端刷新详情
                await event_hub.publish(
                    run_id,
                    {
                        "type": "run_finished",
                        "run_id": run_id,
                        "status": run.status,
                        "passed": run.passed,
                        "failed": run.failed,
                        "skipped": run.skipped,
                        "duration_ms": run.duration_ms,
                    },
                )
                # 有头 keep-alive：提醒用户关窗后进程才退
                if outcome.get("keep_browser_open") and run.status != "cancelled":
                    await event_hub.publish(
                        run_id,
                        {
                            "type": "log",
                            "run_id": run_id,
                            "level": "info",
                            "message": "结果已保存。浏览器仍保持打开，关闭窗口后后台进程才会退出。",
                        },
                    )

            # —— C. worker 仍在跑：增量推 events、提前落库、响应取消 ——
            while not worker_task.done():
                # C1. 读 events 文件新增部分 → WebSocket
                if events_path.exists():
                    data = events_path.read_text(encoding="utf-8")
                    if len(data) > offset:
                        chunk = data[offset:]
                        offset = len(data)
                        for line in chunk.splitlines():
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                await event_hub.publish(run_id, json.loads(line))
                            except json.JSONDecodeError:
                                pass
                # C2. worker 已写 result（浏览器可能还开着）→ 提前落库让 UI 出结果
                if not results_persisted and result_path.exists() and run_id not in self._cancel_flags:
                    try:
                        outcome_early = json.loads(result_path.read_text(encoding="utf-8"))
                        await _persist_outcome(outcome_early)
                    except Exception:  # noqa: BLE001
                        # 读到半文件时忽略，下一轮再试
                        pass
                # C3. 用户取消：立刻改 DB，不必等 worker 退出
                if run_id in self._cancel_flags and run.status != "cancelled":
                    await _force_cancelled_status()
                await asyncio.sleep(0.25)

            # —— D. worker 线程结束 ——
            completed = await worker_task
            log.info(
                "run_id=%s worker exited code=%s results_persisted=%s",
                run_id,
                completed.returncode,
                results_persisted,
            )

            # D1. 排空剩余 events
            if events_path.exists():
                data = events_path.read_text(encoding="utf-8")
                if len(data) > offset:
                    for line in data[offset:].splitlines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            await event_hub.publish(run_id, json.loads(line))
                        except json.JSONDecodeError:
                            pass

            cancelled = run_id in self._cancel_flags or run.status == "cancelled"
            if not results_persisted:
                # D2. 尚未落库：按「有结果 / 取消 / worker 异常退出」三种拼 outcome
                if result_path.exists() and not cancelled:
                    outcome = json.loads(result_path.read_text(encoding="utf-8"))
                elif cancelled:
                    outcome = {
                        "passed": run.passed,
                        "failed": run.failed,
                        "skipped": max(run.skipped, run.total or 0),
                        "duration_ms": run.duration_ms or 0,
                        "error_summary": "Cancelled by user",
                        "case_payloads": [],
                        "cancelled": True,
                    }
                else:
                    # 无 result 文件且非取消 → worker 异常
                    err = (completed.stderr or completed.stdout or "").strip()
                    outcome = {
                        "passed": 0,
                        "failed": 0,
                        "skipped": 0,
                        "duration_ms": 0,
                        "error_summary": err or f"exit={completed.returncode}",
                        "case_payloads": [],
                        "cancelled": False,
                    }
                    await event_hub.publish(
                        run_id,
                        {"type": "run_error", "run_id": run_id, "message": outcome["error_summary"]},
                    )
                await _persist_outcome(outcome)
            else:
                # D3. 已提前落库：若中途取消则强制 cancelled，否则刷新 logs
                if cancelled and run.status != "cancelled":
                    await _force_cancelled_status()
                else:
                    run.logs = _events_to_logs()
                    await db.commit()

            # D4. 清理取消标志与 cancel 文件
            self._cancel_flags.discard(run_id)
            if cancel_file.exists():
                try:
                    cancel_file.unlink()
                except OSError:
                    pass


# 全局单例，与 job_queue 共用
run_executor = RunExecutor()
