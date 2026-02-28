"""
统一消息模型 - 所有渠道共用的消息数据结构
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


class ChannelType(str, Enum):
    """支持的渠道类型"""
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    DISCORD = "discord"
    SLACK = "slack"
    EMAIL = "email"
    WEBHOOK = "webhook"


class MessageStatus(str, Enum):
    """消息状态"""
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    RETRYING = "retrying"
    DEAD = "dead"  # 进入死信队列


class MessagePriority(int, Enum):
    """消息优先级"""
    LOW = 0
    NORMAL = 5
    HIGH = 8
    CRITICAL = 10


@dataclass
class Attachment:
    """附件模型"""
    filename: str
    content_type: str
    url: Optional[str] = None
    data: Optional[bytes] = None
    size: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "filename": self.filename,
            "content_type": self.content_type,
            "url": self.url,
            "size": self.size,
        }


@dataclass
class Message:
    """
    统一消息模型 - 核心数据结构
    所有渠道的消息都通过此模型流转
    """
    from_channel: ChannelType
    to_channel: ChannelType
    content: str
    target: str  # 目标地址 (chat_id / phone / email / webhook_url)

    # 可选字段
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    attachments: List[Attachment] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    priority: MessagePriority = MessagePriority.NORMAL
    status: MessageStatus = MessageStatus.PENDING
    template: Optional[str] = None
    template_vars: Dict[str, Any] = field(default_factory=dict)

    # 时间戳
    created_at: datetime = field(default_factory=datetime.utcnow)
    sent_at: Optional[datetime] = None

    # 重试信息
    retry_count: int = 0
    max_retries: int = 3
    last_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "from_channel": self.from_channel.value,
            "to_channel": self.to_channel.value,
            "content": self.content,
            "target": self.target,
            "attachments": [a.to_dict() for a in self.attachments],
            "metadata": self.metadata,
            "priority": self.priority.value,
            "status": self.status.value,
            "template": self.template,
            "created_at": self.created_at.isoformat(),
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "retry_count": self.retry_count,
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        attachments = [
            Attachment(**a) for a in data.get("attachments", [])
        ]
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            from_channel=ChannelType(data["from_channel"]),
            to_channel=ChannelType(data["to_channel"]),
            content=data.get("content", ""),
            target=data.get("target", ""),
            attachments=attachments,
            metadata=data.get("metadata", {}),
            priority=MessagePriority(data.get("priority", 5)),
            status=MessageStatus(data.get("status", "pending")),
            template=data.get("template"),
            template_vars=data.get("template_vars", {}),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 3),
            last_error=data.get("last_error"),
        )


@dataclass
class SendResult:
    """发送结果"""
    success: bool
    message_id: str
    channel: ChannelType
    response: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    retry_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "message_id": self.message_id,
            "channel": self.channel.value,
            "response": self.response,
            "error": self.error,
            "retry_count": self.retry_count,
        }
