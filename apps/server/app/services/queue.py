"""进程内任务队列：同一时刻只跑一个 Playwright Run。

API 创建 Run 后调用 enqueue(run_id)；后台 _loop 协程串行调用 RunExecutor.execute。
串行是为了避免多浏览器抢资源，也简化取消与日志归属。
"""

from __future__ import annotations

import asyncio

from app.logging_setup import get_logger
from app.services.runner import run_executor

log = get_logger("queue")


class JobQueue:
    """基于 asyncio.Queue 的 FIFO 执行器包装。"""

    def __init__(self) -> None:
        # 队列元素是 run_id（int）
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        # 消费协程句柄；None 表示尚未 start
        self._worker: asyncio.Task | None = None

    async def start(self) -> None:
        """应用启动时调用：若尚未有消费任务则创建 _loop。"""
        if self._worker is None:
            # create_task 把死循环丢到事件循环里跑，不阻塞 lifespan
            self._worker = asyncio.create_task(self._loop())
            log.info("queue worker task created")

    async def stop(self) -> None:
        """应用关闭时调用：取消消费任务并等待其结束。"""
        if self._worker:
            # 向 _loop 发 CancelledError
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                # 正常取消路径，忽略
                pass
            self._worker = None
            log.info("queue worker stopped")

    async def enqueue(self, run_id: int) -> None:
        """把 run_id 放入队列尾部，等待 _loop 取出执行。"""
        await self._queue.put(run_id)
        log.info("enqueued run_id=%s queue_size≈%s", run_id, self._queue.qsize())

    async def _loop(self) -> None:
        """永久循环：取一个 run → execute → 标记 task_done → 再取下一个。"""
        while True:
            # 队列空时在此挂起，直到 enqueue
            run_id = await self._queue.get()
            log.info("dequeue run_id=%s", run_id)
            try:
                # 同步等待整次运行结束（含 worker 子进程）
                await run_executor.execute(run_id)
                log.info("finished run_id=%s", run_id)
            except Exception:
                # 单次失败不影响后续任务；异常已打堆栈
                log.exception("run_id=%s failed in queue", run_id)
            finally:
                # 与 Queue.join 配合；当前未用 join，但保持语义完整
                self._queue.task_done()


# 模块级单例，供 API / lifespan 直接 import
job_queue = JobQueue()
