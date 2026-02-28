"""
Tests for SQLite Message Store
"""

import os
import pytest
import tempfile
from datetime import datetime, timedelta

from gateway.store import MessageStore


@pytest.fixture
def store():
    """创建临时数据库"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    s = MessageStore(path)
    yield s
    s.close()
    os.unlink(path)


@pytest.fixture
def sample_message():
    return {
        "id": "test-msg-001",
        "from_channel": "webhook",
        "to_channel": "telegram",
        "content": "Hello World",
        "target": "123456",
        "template": None,
        "template_vars": {},
        "metadata": {"parse_mode": "Markdown"},
        "priority": 5,
        "status": "pending",
        "retry_count": 0,
        "max_retries": 3,
        "last_error": None,
        "created_at": datetime.utcnow().isoformat(),
        "sent_at": None,
    }


class TestMessageStore:
    def test_save_and_get(self, store, sample_message):
        store.save_message(sample_message)
        msg = store.get_message("test-msg-001")
        assert msg is not None
        assert msg["id"] == "test-msg-001"
        assert msg["content"] == "Hello World"
        assert msg["to_channel"] == "telegram"

    def test_get_nonexistent(self, store):
        assert store.get_message("nonexistent") is None

    def test_update_status(self, store, sample_message):
        store.save_message(sample_message)
        store.update_status("test-msg-001", "sent")
        msg = store.get_message("test-msg-001")
        assert msg["status"] == "sent"
        assert msg["sent_at"] is not None

    def test_update_status_with_error(self, store, sample_message):
        store.save_message(sample_message)
        store.update_status("test-msg-001", "failed", "Connection timeout")
        msg = store.get_message("test-msg-001")
        assert msg["status"] == "failed"
        assert msg["last_error"] == "Connection timeout"

    def test_log_and_get_events(self, store, sample_message):
        store.save_message(sample_message)
        store.log_event("test-msg-001", "created", "telegram")
        store.log_event("test-msg-001", "sending", "telegram")
        store.log_event("test-msg-001", "sent", "telegram")
        events = store.get_events("test-msg-001")
        assert len(events) == 3
        assert events[0]["event"] == "created"
        assert events[2]["event"] == "sent"

    def test_query_by_channel(self, store):
        for i in range(5):
            store.save_message({
                "id": f"msg-tg-{i}",
                "from_channel": "webhook",
                "to_channel": "telegram",
                "content": f"TG {i}",
                "target": "123",
                "created_at": datetime.utcnow().isoformat(),
            })
        for i in range(3):
            store.save_message({
                "id": f"msg-dc-{i}",
                "from_channel": "webhook",
                "to_channel": "discord",
                "content": f"DC {i}",
                "target": "456",
                "created_at": datetime.utcnow().isoformat(),
            })

        tg = store.query_messages(channel="telegram")
        assert len(tg) == 5
        dc = store.query_messages(channel="discord")
        assert len(dc) == 3

    def test_query_by_status(self, store, sample_message):
        store.save_message(sample_message)
        store.update_status("test-msg-001", "sent")
        sent = store.query_messages(status="sent")
        assert len(sent) == 1
        pending = store.query_messages(status="pending")
        assert len(pending) == 0

    def test_query_by_target(self, store, sample_message):
        store.save_message(sample_message)
        results = store.query_messages(target="123456")
        assert len(results) == 1
        results = store.query_messages(target="999999")
        assert len(results) == 0

    def test_query_limit_offset(self, store):
        for i in range(10):
            store.save_message({
                "id": f"msg-{i}",
                "from_channel": "webhook",
                "to_channel": "telegram",
                "content": f"Msg {i}",
                "target": "123",
                "created_at": datetime.utcnow().isoformat(),
            })
        page1 = store.query_messages(limit=5)
        assert len(page1) == 5
        page2 = store.query_messages(limit=5, offset=5)
        assert len(page2) == 5
        assert page1[0]["id"] != page2[0]["id"]

    def test_count_messages(self, store):
        for i in range(7):
            ch = "telegram" if i < 4 else "discord"
            store.save_message({
                "id": f"msg-{i}",
                "from_channel": "webhook",
                "to_channel": ch,
                "content": f"Msg {i}",
                "target": "123",
                "created_at": datetime.utcnow().isoformat(),
            })
        assert store.count_messages() == 7
        assert store.count_messages(channel="telegram") == 4
        assert store.count_messages(channel="discord") == 3

    def test_get_stats(self, store):
        for i in range(5):
            store.save_message({
                "id": f"msg-{i}",
                "from_channel": "webhook",
                "to_channel": "telegram",
                "content": f"Msg {i}",
                "target": "123",
                "status": "sent" if i < 3 else "failed",
                "created_at": datetime.utcnow().isoformat(),
            })
        stats = store.get_stats(hours=1)
        assert stats["total"] == 5
        assert stats["by_status"]["sent"] == 3
        assert stats["by_status"]["failed"] == 2
        assert stats["success_rate"] == 60.0

    def test_upsert_message(self, store, sample_message):
        store.save_message(sample_message)
        sample_message["content"] = "Updated"
        store.save_message(sample_message)
        msg = store.get_message("test-msg-001")
        assert msg["content"] == "Updated"


class TestScheduledMessages:
    def test_save_and_get_scheduled(self, store):
        store.save_scheduled("sched-1", {"channel": "telegram", "text": "Hi"}, "2026-01-01T00:00:00")
        scheduled = store.get_scheduled()
        assert len(scheduled) == 1
        assert scheduled[0]["id"] == "sched-1"

    def test_get_due_scheduled(self, store):
        past = (datetime.utcnow() - timedelta(minutes=5)).isoformat()
        future = (datetime.utcnow() + timedelta(hours=1)).isoformat()
        store.save_scheduled("sched-past", {"text": "Past"}, past)
        store.save_scheduled("sched-future", {"text": "Future"}, future)
        due = store.get_due_scheduled()
        assert len(due) == 1
        assert due[0]["id"] == "sched-past"

    def test_mark_scheduled_done(self, store):
        store.save_scheduled("sched-1", {"text": "Hi"}, datetime.utcnow().isoformat())
        store.mark_scheduled_done("sched-1", "success")
        scheduled = store.get_scheduled(status="executed")
        assert len(scheduled) == 1
        assert scheduled[0]["result"] == "success"

    def test_delete_scheduled(self, store):
        store.save_scheduled("sched-1", {"text": "Hi"}, datetime.utcnow().isoformat())
        assert store.delete_scheduled("sched-1") is True
        assert store.delete_scheduled("sched-1") is False
        assert len(store.get_scheduled()) == 0

    def test_filter_scheduled_by_status(self, store):
        store.save_scheduled("s1", {"text": "1"}, datetime.utcnow().isoformat())
        store.save_scheduled("s2", {"text": "2"}, datetime.utcnow().isoformat())
        store.mark_scheduled_done("s1")
        pending = store.get_scheduled(status="pending")
        assert len(pending) == 1
        executed = store.get_scheduled(status="executed")
        assert len(executed) == 1
