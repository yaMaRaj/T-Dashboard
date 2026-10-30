"""进程内 Run 事件总线：把 runner/worker 事件扇出到 WebSocket 订阅者。

API 的 ws 路由 subscribe(run_id) 拿到 Queue；
runner 里 event_hub.publish(run_id, event) 写入所有订阅队列。
队列满时丢弃最旧一条再塞新事件，避免慢消费者堵死生产者。
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any


class EventHub:
    """按 run_id 维护一组 asyncio.Queue 订阅者。"""

    def __init__(self) -> None:
        # run_id → 该 run 的所有前端连接对应的队列
        self._subscribers: dict[int, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def subscribe(self, run_id: int) -> asyncio.Queue[dict[str, Any]]:
        """新建容量 200 的队列并登记到该 run；返回队列供 WS 协程 get。"""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=200)
        async with self._lock:
            self._subscribers[run_id].add(queue)
        return queue

    async def unsubscribe(self, run_id: int, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """WS 断开时移除队列；若该 run 已无订阅者则删掉 key。"""
        async with self._lock:
            subs = self._subscribers.get(run_id)
            if not subs:
                return
            subs.discard(queue)
            if not subs:
                self._subscribers.pop(run_id, None)

    async def publish(self, run_id: int, event: dict[str, Any]) -> None:
        """向该 run 的所有订阅者 put_nowait；满则丢最旧再试一次。"""
        async with self._lock:
            # 拷贝 list，避免持锁期间 put 阻塞其它协程过久
            subscribers = list(self._subscribers.get(run_id, set()))
        for queue in subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # 慢消费者：扔掉一条旧消息腾位置
                try:
                    _ = queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    # 仍然满则放弃本条，优先保证执行端不阻塞
                    pass


event_hub = EventHub()
