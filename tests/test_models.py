"""
Tests for gateway.models - Message, SendResult, ChannelType, etc.
"""

import pytest
from datetime import datetime

from gateway.models import (
    Attachment,
    ChannelType,
    Message,
    MessagePriority,
    MessageStatus,
    SendResult,
)


class TestChannelType:
    def test_all_channels_exist(self):
        assert ChannelType.TELEGRAM == "telegram"
        assert ChannelType.WHATSAPP == "whatsapp"
        assert ChannelType.DISCORD == "discord"
        assert ChannelType.SLACK == "slack"
        assert ChannelType.EMAIL == "email"
        assert ChannelType.WEBHOOK == "webhook"

    def test_channel_from_string(self):
        assert ChannelType("telegram") == ChannelType.TELEGRAM
        assert ChannelType("email") == ChannelType.EMAIL

    def test_invalid_channel(self):
        with pytest.raises(ValueError):
            ChannelType("invalid")


class TestMessagePriority:
    def test_priorities(self):
        assert MessagePriority.LOW == 0
        assert MessagePriority.NORMAL == 5
        assert MessagePriority.HIGH == 8
        assert MessagePriority.CRITICAL == 10

    def test_priority_ordering(self):
        assert MessagePriority.LOW < MessagePriority.NORMAL
        assert MessagePriority.NORMAL < MessagePriority.HIGH
        assert MessagePriority.HIGH < MessagePriority.CRITICAL


class TestMessageStatus:
    def test_all_statuses(self):
        statuses = [s.value for s in MessageStatus]
        assert "pending" in statuses
        assert "sending" in statuses
        assert "sent" in statuses
        assert "delivered" in statuses
        assert "failed" in statuses
        assert "retrying" in statuses
        assert "dead" in statuses


class TestAttachment:
    def test_create_attachment(self):
        att = Attachment(filename="test.pdf", content_type="application/pdf", size=1024)
        assert att.filename == "test.pdf"
        assert att.content_type == "application/pdf"
        assert att.size == 1024
        assert att.url is None
        assert att.data is None

    def test_attachment_to_dict(self):
        att = Attachment(
            filename="report.csv",
            content_type="text/csv",
            url="https://example.com/report.csv",
            size=2048,
        )
        d = att.to_dict()
        assert d["filename"] == "report.csv"
        assert d["content_type"] == "text/csv"
        assert d["url"] == "https://example.com/report.csv"
        assert d["size"] == 2048


class TestMessage:
    def test_create_message(self):
        msg = Message(
            from_channel=ChannelType.WEBHOOK,
            to_channel=ChannelType.TELEGRAM,
            content="Hello",
            target="123456",
        )
        assert msg.content == "Hello"
        assert msg.target == "123456"
        assert msg.to_channel == ChannelType.TELEGRAM
        assert msg.status == MessageStatus.PENDING
        assert msg.priority == MessagePriority.NORMAL
        assert msg.retry_count == 0
        assert msg.id  # auto-generated UUID

    def test_message_with_template(self):
        msg = Message(
            from_channel=ChannelType.WEBHOOK,
            to_channel=ChannelType.EMAIL,
            content="",
            target="user@example.com",
            template="welcome",
            template_vars={"name": "Alice"},
        )
        assert msg.template == "welcome"
        assert msg.template_vars["name"] == "Alice"

    def test_message_with_attachments(self):
        att = Attachment(filename="file.txt", content_type="text/plain")
        msg = Message(
            from_channel=ChannelType.WEBHOOK,
            to_channel=ChannelType.EMAIL,
            content="See attachment",
            target="user@example.com",
            attachments=[att],
        )
        assert len(msg.attachments) == 1
        assert msg.attachments[0].filename == "file.txt"

    def test_message_to_dict(self):
        msg = Message(
            from_channel=ChannelType.WEBHOOK,
            to_channel=ChannelType.TELEGRAM,
            content="Test",
            target="111",
        )
        d = msg.to_dict()
        assert d["from_channel"] == "webhook"
        assert d["to_channel"] == "telegram"
        assert d["content"] == "Test"
        assert d["target"] == "111"
        assert d["status"] == "pending"
        assert d["priority"] == 5
        assert "id" in d
        assert "created_at" in d

    def test_message_from_dict(self):
        d = {
            "from_channel": "webhook",
            "to_channel": "slack",
            "content": "Round trip",
            "target": "webhook_url",
            "priority": 8,
            "status": "sent",
        }
        msg = Message.from_dict(d)
        assert msg.to_channel == ChannelType.SLACK
        assert msg.content == "Round trip"
        assert msg.priority == MessagePriority.HIGH
        assert msg.status == MessageStatus.SENT

    def test_message_roundtrip(self):
        original = Message(
            from_channel=ChannelType.WEBHOOK,
            to_channel=ChannelType.DISCORD,
            content="Roundtrip test",
            target="webhook_url",
            metadata={"username": "Bot"},
            priority=MessagePriority.HIGH,
        )
        d = original.to_dict()
        restored = Message.from_dict(d)
        assert restored.content == original.content
        assert restored.to_channel == original.to_channel
        assert restored.priority == original.priority


class TestSendResult:
    def test_success_result(self):
        r = SendResult(
            success=True,
            message_id="abc-123",
            channel=ChannelType.TELEGRAM,
            response={"ok": True, "result": {"message_id": 42}},
        )
        assert r.success is True
        assert r.error is None

    def test_failure_result(self):
        r = SendResult(
            success=False,
            message_id="abc-456",
            channel=ChannelType.WHATSAPP,
            error="Token expired",
        )
        assert r.success is False
        assert r.error == "Token expired"

    def test_result_to_dict(self):
        r = SendResult(
            success=True,
            message_id="xyz",
            channel=ChannelType.SLACK,
            retry_count=2,
        )
        d = r.to_dict()
        assert d["success"] is True
        assert d["channel"] == "slack"
        assert d["retry_count"] == 2
