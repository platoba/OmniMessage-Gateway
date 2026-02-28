"""
Tests for Message Scheduler
"""

import asyncio
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from gateway.scheduler import MessageScheduler, ScheduleEntry


@pytest.fixture
def scheduler():
    return MessageScheduler(poll_interval=0.1)


@pytest.fixture
def mock_send_fn():
    return AsyncMock(return_value={"success": True})


class TestScheduleEntry:
    def test_create_entry(self):
        entry = ScheduleEntry(
            "e1", {"text": "Hello"}, datetime.utcnow() + timedelta(hours=1)
        )
        assert entry.status == "pending"
        assert entry.run_count == 0
        assert entry.recurring is False

    def test_is_due_future(self):
        entry = ScheduleEntry(
            "e1", {"text": "Hello"}, datetime.utcnow() + timedelta(hours=1)
        )
        assert entry.is_due() is False

    def test_is_due_past(self):
        entry = ScheduleEntry(
            "e1", {"text": "Hello"}, datetime.utcnow() - timedelta(seconds=1)
        )
        assert entry.is_due() is True

    def test_advance_one_shot(self):
        entry = ScheduleEntry(
            "e1", {"text": "Hello"}, datetime.utcnow()
        )
        entry.advance()
        assert entry.status == "completed"
        assert entry.run_count == 1
        assert entry.last_run_at is not None

    def test_advance_recurring(self):
        entry = ScheduleEntry(
            "e1", {"text": "Hello"}, datetime.utcnow(),
            recurring=True, interval_seconds=60
        )
        original_at = entry.scheduled_at
        entry.advance()
        assert entry.status == "pending"  # 仍然 pending
        assert entry.run_count == 1
        assert entry.scheduled_at > original_at

    def test_advance_recurring_max_runs(self):
        entry = ScheduleEntry(
            "e1", {"text": "Hello"}, datetime.utcnow(),
            recurring=True, interval_seconds=60, max_runs=2
        )
        entry.advance()
        assert entry.status == "pending"
        entry.advance()
        assert entry.status == "completed"

    def test_to_dict(self):
        entry = ScheduleEntry(
            "e1", {"text": "Hello"}, datetime(2026, 1, 1)
        )
        d = entry.to_dict()
        assert d["id"] == "e1"
        assert d["status"] == "pending"
        assert "scheduled_at" in d
        assert d["message_data"] == {"text": "Hello"}


class TestMessageScheduler:
    def test_schedule_at(self, scheduler):
        at = datetime.utcnow() + timedelta(hours=1)
        entry_id = scheduler.schedule_at({"text": "Hi"}, at)
        assert entry_id in scheduler.entries
        assert scheduler.entries[entry_id].scheduled_at == at

    def test_schedule_delay(self, scheduler):
        entry_id = scheduler.schedule_delay({"text": "Hi"}, 300)
        entry = scheduler.entries[entry_id]
        # 应该在约5分钟后
        diff = (entry.scheduled_at - datetime.utcnow()).total_seconds()
        assert 290 < diff < 310

    def test_schedule_recurring(self, scheduler):
        entry_id = scheduler.schedule_recurring(
            {"text": "Hi"}, interval_seconds=60, max_runs=5
        )
        entry = scheduler.entries[entry_id]
        assert entry.recurring is True
        assert entry.interval_seconds == 60
        assert entry.max_runs == 5

    def test_cancel(self, scheduler):
        entry_id = scheduler.schedule_delay({"text": "Hi"}, 300)
        assert scheduler.cancel(entry_id) is True
        assert scheduler.entries[entry_id].status == "cancelled"

    def test_cancel_nonexistent(self, scheduler):
        assert scheduler.cancel("nonexistent") is False

    def test_get_entry(self, scheduler):
        entry_id = scheduler.schedule_delay({"text": "Hi"}, 300)
        entry = scheduler.get_entry(entry_id)
        assert entry is not None
        assert entry["id"] == entry_id

    def test_get_nonexistent_entry(self, scheduler):
        assert scheduler.get_entry("nope") is None

    def test_list_entries(self, scheduler):
        scheduler.schedule_delay({"text": "1"}, 100)
        scheduler.schedule_delay({"text": "2"}, 200)
        scheduler.schedule_delay({"text": "3"}, 300)
        entries = scheduler.list_entries()
        assert len(entries) == 3

    def test_list_entries_by_status(self, scheduler):
        id1 = scheduler.schedule_delay({"text": "1"}, 100)
        scheduler.schedule_delay({"text": "2"}, 200)
        scheduler.cancel(id1)
        pending = scheduler.list_entries(status="pending")
        assert len(pending) == 1
        cancelled = scheduler.list_entries(status="cancelled")
        assert len(cancelled) == 1

    def test_get_due(self, scheduler):
        scheduler.schedule_at({"text": "past"}, datetime.utcnow() - timedelta(seconds=1))
        scheduler.schedule_at({"text": "future"}, datetime.utcnow() + timedelta(hours=1))
        due = scheduler.get_due()
        assert len(due) == 1
        assert due[0].message_data["text"] == "past"

    @pytest.mark.asyncio
    async def test_process_due(self, mock_send_fn):
        scheduler = MessageScheduler(send_fn=mock_send_fn)
        scheduler.schedule_at({"text": "now"}, datetime.utcnow() - timedelta(seconds=1))
        processed = await scheduler.process_due()
        assert processed == 1
        mock_send_fn.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_due_empty(self, scheduler):
        processed = await scheduler.process_due()
        assert processed == 0

    @pytest.mark.asyncio
    async def test_process_recurring(self, mock_send_fn):
        scheduler = MessageScheduler(send_fn=mock_send_fn)
        entry_id = scheduler.schedule_recurring(
            {"text": "repeat"}, interval_seconds=3600,
            start_at=datetime.utcnow() - timedelta(seconds=1),
        )
        await scheduler.process_due()
        entry = scheduler.entries[entry_id]
        assert entry.run_count == 1
        assert entry.status == "pending"  # 仍然 pending (下次执行)

    @pytest.mark.asyncio
    async def test_execute_with_callback(self, mock_send_fn):
        scheduler = MessageScheduler(send_fn=mock_send_fn)
        callback = MagicMock()
        scheduler.on_execute(callback)
        scheduler.schedule_at({"text": "cb"}, datetime.utcnow() - timedelta(seconds=1))
        await scheduler.process_due()
        callback.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_error_handling(self):
        async def failing_send(data):
            raise ValueError("Send error")

        scheduler = MessageScheduler(send_fn=failing_send)
        entry_id = scheduler.schedule_at(
            {"text": "fail"}, datetime.utcnow() - timedelta(seconds=1)
        )
        await scheduler.process_due()
        entry = scheduler.entries[entry_id]
        assert "error" in entry.last_result

    @pytest.mark.asyncio
    async def test_start_stop(self, scheduler):
        await scheduler.start()
        assert scheduler._running is True
        await scheduler.stop()
        assert scheduler._running is False

    def test_stats(self, scheduler):
        scheduler.schedule_delay({"text": "1"}, 100)
        id2 = scheduler.schedule_delay({"text": "2"}, 200)
        scheduler.cancel(id2)
        stats = scheduler.stats
        assert stats["total"] == 2
        assert stats["by_status"]["pending"] == 1
        assert stats["by_status"]["cancelled"] == 1

    def test_custom_entry_id(self, scheduler):
        entry_id = scheduler.schedule_at(
            {"text": "Hi"}, datetime.utcnow(), entry_id="custom-id"
        )
        assert entry_id == "custom-id"
        assert "custom-id" in scheduler.entries

    def test_no_send_fn(self, scheduler):
        """没有 send_fn 时也不崩溃"""
        entry_id = scheduler.schedule_at(
            {"text": "Hi"}, datetime.utcnow() - timedelta(seconds=1)
        )
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(scheduler.process_due())
        finally:
            loop.close()
        entry = scheduler.entries[entry_id]
        assert entry.last_result == "no_send_fn"
