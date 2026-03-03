"""
Priority Queue System for OmniMessage Gateway
优先级队列系统 - 支持紧急消息优先发送、队列管理、统计分析
"""

import asyncio
import heapq
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Any, Dict, List, Optional
from uuid import uuid4


class Priority(IntEnum):
    """消息优先级"""
    CRITICAL = 0  # 最高优先级（数字越小优先级越高）
    HIGH = 1
    NORMAL = 2
    LOW = 3
    BULK = 4  # 批量消息


@dataclass(order=True)
class PriorityMessage:
    """优先级消息"""
    priority: int
    timestamp: float = field(compare=True)  # 同优先级按时间排序
    message_id: str = field(default_factory=lambda: str(uuid4()), compare=False)
    channel: str = field(default="", compare=False)
    target: str = field(default="", compare=False)
    content: str = field(default="", compare=False)
    metadata: Dict[str, Any] = field(default_factory=dict, compare=False)
    retry_count: int = field(default=0, compare=False)
    max_retries: int = field(default=3, compare=False)


class PriorityQueueManager:
    """优先级队列管理器"""

    def __init__(self, max_size: int = 10000):
        self._queue: List[PriorityMessage] = []
        self._max_size = max_size
        self._lock = asyncio.Lock()
        self._not_empty = asyncio.Condition(self._lock)
        self._stats = {
            "enqueued": 0,
            "dequeued": 0,
            "dropped": 0,
            "by_priority": {p.name: 0 for p in Priority},
        }
        self._size_by_priority = {p: 0 for p in Priority}

    async def enqueue(
        self,
        channel: str,
        target: str,
        content: str,
        priority: Priority = Priority.NORMAL,
        metadata: Optional[Dict[str, Any]] = None,
        max_retries: int = 3,
    ) -> Optional[str]:
        """入队消息"""
        async with self._lock:
            if len(self._queue) >= self._max_size:
                # 队列满，丢弃最低优先级消息
                if self._queue and self._queue[-1].priority >= priority:
                    dropped = heapq.heappop(self._queue)
                    self._stats["dropped"] += 1
                    self._size_by_priority[Priority(dropped.priority)] -= 1
                else:
                    self._stats["dropped"] += 1
                    return None

            msg = PriorityMessage(
                priority=priority,
                timestamp=time.time(),
                channel=channel,
                target=target,
                content=content,
                metadata=metadata or {},
                max_retries=max_retries,
            )

            heapq.heappush(self._queue, msg)
            self._stats["enqueued"] += 1
            self._stats["by_priority"][Priority(priority).name] += 1
            self._size_by_priority[Priority(priority)] += 1

            self._not_empty.notify()
            return msg.message_id

    async def dequeue(self, timeout: Optional[float] = None) -> Optional[PriorityMessage]:
        """出队消息（阻塞直到有消息或超时）"""
        async with self._not_empty:
            while not self._queue:
                try:
                    await asyncio.wait_for(self._not_empty.wait(), timeout=timeout)
                except asyncio.TimeoutError:
                    return None

            msg = heapq.heappop(self._queue)
            self._stats["dequeued"] += 1
            self._size_by_priority[Priority(msg.priority)] -= 1
            return msg

    async def dequeue_nowait(self) -> Optional[PriorityMessage]:
        """非阻塞出队"""
        async with self._lock:
            if not self._queue:
                return None
            msg = heapq.heappop(self._queue)
            self._stats["dequeued"] += 1
            self._size_by_priority[Priority(msg.priority)] -= 1
            return msg

    async def requeue(self, msg: PriorityMessage) -> bool:
        """重新入队（用于重试）"""
        if msg.retry_count >= msg.max_retries:
            return False

        msg.retry_count += 1
        msg.timestamp = time.time()  # 更新时间戳

        async with self._lock:
            if len(self._queue) >= self._max_size:
                return False
            heapq.heappush(self._queue, msg)
            self._size_by_priority[Priority(msg.priority)] += 1
            self._not_empty.notify()
            return True

    async def peek(self) -> Optional[PriorityMessage]:
        """查看队首消息（不出队）"""
        async with self._lock:
            return self._queue[0] if self._queue else None

    async def size(self) -> int:
        """队列大小"""
        async with self._lock:
            return len(self._queue)

    async def is_empty(self) -> bool:
        """队列是否为空"""
        async with self._lock:
            return len(self._queue) == 0

    async def clear(self):
        """清空队列"""
        async with self._lock:
            self._queue.clear()
            self._size_by_priority = {p: 0 for p in Priority}

    async def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        async with self._lock:
            return {
                "queue_size": len(self._queue),
                "max_size": self._max_size,
                "utilization": len(self._queue) / self._max_size,
                "enqueued_total": self._stats["enqueued"],
                "dequeued_total": self._stats["dequeued"],
                "dropped_total": self._stats["dropped"],
                "by_priority": dict(self._stats["by_priority"]),
                "current_by_priority": {
                    p.name: self._size_by_priority[p] for p in Priority
                },
            }

    async def get_messages_by_priority(self, priority: Priority, limit: int = 10) -> List[Dict[str, Any]]:
        """获取指定优先级的消息列表"""
        async with self._lock:
            messages = [
                {
                    "message_id": msg.message_id,
                    "channel": msg.channel,
                    "target": msg.target,
                    "content": msg.content[:100],  # 截断内容
                    "priority": Priority(msg.priority).name,
                    "timestamp": datetime.fromtimestamp(msg.timestamp).isoformat(),
                    "retry_count": msg.retry_count,
                }
                for msg in self._queue
                if msg.priority == priority
            ][:limit]
            return messages


class PriorityQueueWorker:
    """优先级队列工作器 - 从队列中取消息并发送"""

    def __init__(
        self,
        queue_manager: PriorityQueueManager,
        send_callback,
        worker_count: int = 3,
    ):
        self._queue = queue_manager
        self._send_callback = send_callback
        self._worker_count = worker_count
        self._workers: List[asyncio.Task] = []
        self._running = False
        self._stats = {
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
            "retried": 0,
        }

    async def start(self):
        """启动工作器"""
        if self._running:
            return

        self._running = True
        self._workers = [
            asyncio.create_task(self._worker(i))
            for i in range(self._worker_count)
        ]

    async def stop(self):
        """停止工作器"""
        self._running = False
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    async def _worker(self, worker_id: int):
        """工作器协程"""
        while self._running:
            try:
                msg = await self._queue.dequeue(timeout=1.0)
                if not msg:
                    continue

                self._stats["processed"] += 1

                # 调用发送回调
                try:
                    await self._send_callback(
                        channel=msg.channel,
                        target=msg.target,
                        content=msg.content,
                        metadata=msg.metadata,
                    )
                    self._stats["succeeded"] += 1
                except Exception:
                    # 发送失败，尝试重新入队
                    if await self._queue.requeue(msg):
                        self._stats["retried"] += 1
                    else:
                        self._stats["failed"] += 1

            except asyncio.CancelledError:
                break
            except Exception:
                pass

    def get_stats(self) -> Dict[str, Any]:
        """获取工作器统计"""
        return {
            "worker_count": self._worker_count,
            "running": self._running,
            "processed": self._stats["processed"],
            "succeeded": self._stats["succeeded"],
            "failed": self._stats["failed"],
            "retried": self._stats["retried"],
            "success_rate": (
                self._stats["succeeded"] / self._stats["processed"]
                if self._stats["processed"] > 0
                else 0
            ),
        }
