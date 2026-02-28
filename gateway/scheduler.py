"""
Message Scheduler - 定时消息调度器
支持: 延时发送 / 定时发送 / 周期发送
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger("omni.scheduler")


class ScheduleEntry:
    """调度条目"""

    def __init__(
        self,
        entry_id: str,
        message_data: Dict[str, Any],
        scheduled_at: datetime,
        recurring: bool = False,
        interval_seconds: int = 0,
        max_runs: int = 0,
    ):
        self.id = entry_id
        self.message_data = message_data
        self.scheduled_at = scheduled_at
        self.recurring = recurring
        self.interval_seconds = interval_seconds
        self.max_runs = max_runs
        self.run_count = 0
        self.status = "pending"
        self.created_at = datetime.utcnow()
        self.last_run_at: Optional[datetime] = None
        self.last_result: Optional[str] = None

    def is_due(self) -> bool:
        return self.status == "pending" and datetime.utcnow() >= self.scheduled_at

    def advance(self) -> None:
        """推进到下一次执行"""
        self.run_count += 1
        self.last_run_at = datetime.utcnow()
        if self.recurring and (self.max_runs == 0 or self.run_count < self.max_runs):
            self.scheduled_at += timedelta(seconds=self.interval_seconds)
        else:
            self.status = "completed"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "message_data": self.message_data,
            "scheduled_at": self.scheduled_at.isoformat(),
            "recurring": self.recurring,
            "interval_seconds": self.interval_seconds,
            "max_runs": self.max_runs,
            "run_count": self.run_count,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "last_result": self.last_result,
        }


class MessageScheduler:
    """
    消息调度器
    - schedule_at: 指定时间发送
    - schedule_delay: 延时N秒发送
    - schedule_recurring: 周期性发送
    - 后台worker自动执行
    """

    def __init__(
        self,
        send_fn: Optional[Callable[..., Coroutine]] = None,
        poll_interval: float = 5.0,
    ):
        self.entries: Dict[str, ScheduleEntry] = {}
        self._send_fn = send_fn
        self._poll_interval = poll_interval
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._callbacks: List[Callable] = []

    def schedule_at(
        self,
        message_data: Dict[str, Any],
        at: datetime,
        entry_id: str = None,
    ) -> str:
        """在指定时间发送"""
        entry_id = entry_id or str(uuid.uuid4())
        entry = ScheduleEntry(entry_id, message_data, at)
        self.entries[entry_id] = entry
        logger.info(f"Scheduled message {entry_id} at {at.isoformat()}")
        return entry_id

    def schedule_delay(
        self,
        message_data: Dict[str, Any],
        delay_seconds: int,
        entry_id: str = None,
    ) -> str:
        """延时发送"""
        at = datetime.utcnow() + timedelta(seconds=delay_seconds)
        return self.schedule_at(message_data, at, entry_id)

    def schedule_recurring(
        self,
        message_data: Dict[str, Any],
        interval_seconds: int,
        start_at: Optional[datetime] = None,
        max_runs: int = 0,
        entry_id: str = None,
    ) -> str:
        """周期性发送"""
        entry_id = entry_id or str(uuid.uuid4())
        at = start_at or datetime.utcnow()
        entry = ScheduleEntry(
            entry_id, message_data, at,
            recurring=True,
            interval_seconds=interval_seconds,
            max_runs=max_runs,
        )
        self.entries[entry_id] = entry
        logger.info(f"Scheduled recurring {entry_id} every {interval_seconds}s")
        return entry_id

    def cancel(self, entry_id: str) -> bool:
        """取消调度"""
        if entry_id in self.entries:
            self.entries[entry_id].status = "cancelled"
            return True
        return False

    def get_entry(self, entry_id: str) -> Optional[Dict[str, Any]]:
        entry = self.entries.get(entry_id)
        return entry.to_dict() if entry else None

    def list_entries(self, status: str = None) -> List[Dict[str, Any]]:
        """列出调度条目"""
        entries = self.entries.values()
        if status:
            entries = [e for e in entries if e.status == status]
        return [e.to_dict() for e in sorted(entries, key=lambda x: x.scheduled_at)]

    def get_due(self) -> List[ScheduleEntry]:
        """获取到期的消息"""
        return [e for e in self.entries.values() if e.is_due()]

    async def _execute_entry(self, entry: ScheduleEntry) -> None:
        """执行单条调度"""
        try:
            if self._send_fn:
                result = await self._send_fn(entry.message_data)
                entry.last_result = json.dumps(result) if isinstance(result, dict) else str(result)
            else:
                entry.last_result = "no_send_fn"

            entry.advance()
            logger.info(f"Executed scheduled {entry.id} (run #{entry.run_count})")

            for cb in self._callbacks:
                try:
                    cb(entry)
                except Exception as e:
                    logger.error(f"Callback error: {e}")

        except Exception as e:
            entry.last_result = f"error: {e}"
            entry.advance()
            logger.error(f"Scheduled {entry.id} failed: {e}")

    async def process_due(self) -> int:
        """处理所有到期消息"""
        due = self.get_due()
        if not due:
            return 0

        tasks = [self._execute_entry(e) for e in due]
        await asyncio.gather(*tasks, return_exceptions=True)
        return len(due)

    async def _worker(self) -> None:
        """后台 worker"""
        logger.info(f"Scheduler worker started (poll={self._poll_interval}s)")
        while self._running:
            try:
                processed = await self.process_due()
                if processed > 0:
                    logger.info(f"Processed {processed} scheduled messages")
            except Exception as e:
                logger.error(f"Scheduler worker error: {e}")
            await asyncio.sleep(self._poll_interval)

    async def start(self) -> None:
        """启动调度器"""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._worker())
        logger.info("Scheduler started")

    async def stop(self) -> None:
        """停止调度器"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Scheduler stopped")

    def on_execute(self, callback: Callable) -> None:
        """注册执行回调"""
        self._callbacks.append(callback)

    @property
    def stats(self) -> Dict[str, Any]:
        status_counts: Dict[str, int] = {}
        for e in self.entries.values():
            status_counts[e.status] = status_counts.get(e.status, 0) + 1
        return {
            "total": len(self.entries),
            "by_status": status_counts,
            "running": self._running,
            "poll_interval": self._poll_interval,
        }
