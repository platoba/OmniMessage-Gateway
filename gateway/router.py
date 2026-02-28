"""
路由引擎 - 规则路由 + 优先级队列 + 重试机制 + 死信队列
"""

import asyncio
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from gateway.models import (
    ChannelType,
    Message,
    MessagePriority,
    MessageStatus,
    SendResult,
)

logger = logging.getLogger("omni.router")


@dataclass
class RoutingRule:
    """路由规则"""
    name: str
    condition: Callable[[Message], bool]
    target_channel: ChannelType
    priority: int = 0  # 规则优先级, 越大越先匹配
    transform: Optional[Callable[[Message], Message]] = None
    enabled: bool = True

    def matches(self, message: Message) -> bool:
        if not self.enabled:
            return False
        try:
            return self.condition(message)
        except Exception:
            return False


@dataclass
class DeadLetterEntry:
    """死信队列条目"""
    message: Message
    error: str
    failed_at: datetime = field(default_factory=datetime.utcnow)
    retry_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message": self.message.to_dict(),
            "error": self.error,
            "failed_at": self.failed_at.isoformat(),
            "retry_count": self.retry_count,
        }


class RoutingEngine:
    """
    路由引擎
    - 规则匹配: 按优先级匹配路由规则
    - 优先级队列: 高优先级消息先处理
    - 重试机制: 指数退避重试
    - 死信队列: 超过重试次数的消息
    """

    def __init__(self, max_retries: int = 3, retry_delay: float = 1.0):
        self.rules: List[RoutingRule] = []
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.dead_letter_queue: List[DeadLetterEntry] = []
        self._channel_handlers: Dict[ChannelType, Any] = {}
        self._stats: Dict[str, int] = defaultdict(int)
        self._middleware: List[Callable] = []

    def register_channel(self, channel_type: ChannelType, handler: Any) -> None:
        """注册渠道处理器"""
        self._channel_handlers[channel_type] = handler
        logger.info(f"Registered channel: {channel_type.value}")

    def add_rule(self, rule: RoutingRule) -> None:
        """添加路由规则 (自动按优先级排序)"""
        self.rules.append(rule)
        self.rules.sort(key=lambda r: r.priority, reverse=True)
        logger.info(f"Added routing rule: {rule.name} (priority={rule.priority})")

    def remove_rule(self, name: str) -> bool:
        """移除路由规则"""
        before = len(self.rules)
        self.rules = [r for r in self.rules if r.name != name]
        return len(self.rules) < before

    def add_middleware(self, fn: Callable) -> None:
        """添加中间件 (消息预处理)"""
        self._middleware.append(fn)

    def match_rule(self, message: Message) -> Optional[RoutingRule]:
        """按优先级匹配第一条规则"""
        for rule in self.rules:
            if rule.matches(message):
                return rule
        return None

    def match_all_rules(self, message: Message) -> List[RoutingRule]:
        """匹配所有符合条件的规则"""
        return [r for r in self.rules if r.matches(message)]

    async def _apply_middleware(self, message: Message) -> Message:
        """应用中间件链"""
        for mw in self._middleware:
            if asyncio.iscoroutinefunction(mw):
                message = await mw(message)
            else:
                message = mw(message)
        return message

    async def route(self, message: Message) -> SendResult:
        """
        路由消息 - 核心方法
        1. 应用中间件
        2. 匹配路由规则 (或使用消息自带的 to_channel)
        3. 获取渠道处理器
        4. 发送 (含重试)
        """
        self._stats["total"] += 1

        # 应用中间件
        message = await self._apply_middleware(message)

        # 匹配路由规则
        rule = self.match_rule(message)
        if rule:
            logger.info(f"Message {message.id} matched rule: {rule.name}")
            if rule.transform:
                message = rule.transform(message)
            target_channel = rule.target_channel
        else:
            target_channel = message.to_channel

        # 获取处理器
        handler = self._channel_handlers.get(target_channel)
        if not handler:
            error = f"No handler for channel: {target_channel.value}"
            logger.error(error)
            self._stats["errors"] += 1
            return SendResult(
                success=False,
                message_id=message.id,
                channel=target_channel,
                error=error,
            )

        # 带重试的发送
        return await self._send_with_retry(handler, message, target_channel)

    async def _send_with_retry(
        self, handler: Any, message: Message, channel: ChannelType
    ) -> SendResult:
        """带指数退避的重试机制"""
        max_attempts = message.max_retries or self.max_retries
        last_error = ""

        for attempt in range(max_attempts + 1):
            message.retry_count = attempt
            message.status = MessageStatus.SENDING if attempt == 0 else MessageStatus.RETRYING

            try:
                result = await handler.send(message)

                if result.success:
                    message.status = MessageStatus.SENT
                    message.sent_at = datetime.utcnow()
                    self._stats["sent"] += 1
                    self._stats[f"sent:{channel.value}"] += 1
                    result.retry_count = attempt
                    return result
                else:
                    last_error = result.error or "Unknown error"
                    logger.warning(
                        f"Send failed (attempt {attempt + 1}/{max_attempts + 1}): {last_error}"
                    )
            except Exception as e:
                last_error = str(e)
                logger.warning(
                    f"Send exception (attempt {attempt + 1}/{max_attempts + 1}): {last_error}"
                )

            # 指数退避
            if attempt < max_attempts:
                delay = self.retry_delay * (2 ** attempt)
                await asyncio.sleep(delay)

        # 所有重试失败 → 死信队列
        message.status = MessageStatus.DEAD
        message.last_error = last_error
        self._stats["dead"] += 1
        self._stats["errors"] += 1

        self.dead_letter_queue.append(
            DeadLetterEntry(
                message=message,
                error=last_error,
                retry_count=max_attempts,
            )
        )
        logger.error(f"Message {message.id} moved to DLQ after {max_attempts + 1} attempts")

        return SendResult(
            success=False,
            message_id=message.id,
            channel=channel,
            error=f"All {max_attempts + 1} attempts failed: {last_error}",
            retry_count=max_attempts,
        )

    async def broadcast(self, message: Message, channels: List[ChannelType]) -> List[SendResult]:
        """广播到多个渠道"""
        tasks = []
        for ch in channels:
            msg_copy = Message(
                from_channel=message.from_channel,
                to_channel=ch,
                content=message.content,
                target=message.metadata.get(f"target:{ch.value}", message.target),
                attachments=message.attachments,
                metadata=message.metadata,
                priority=message.priority,
                template=message.template,
                template_vars=message.template_vars,
                max_retries=message.max_retries,
            )
            tasks.append(self.route(msg_copy))

        return await asyncio.gather(*tasks)

    def get_dead_letters(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取死信队列"""
        return [dl.to_dict() for dl in self.dead_letter_queue[-limit:]]

    def clear_dead_letters(self) -> int:
        """清空死信队列"""
        count = len(self.dead_letter_queue)
        self.dead_letter_queue.clear()
        return count

    async def retry_dead_letter(self, index: int) -> Optional[SendResult]:
        """重试死信队列中的消息"""
        if 0 <= index < len(self.dead_letter_queue):
            entry = self.dead_letter_queue.pop(index)
            entry.message.status = MessageStatus.PENDING
            entry.message.retry_count = 0
            return await self.route(entry.message)
        return None

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "total": self._stats.get("total", 0),
            "sent": self._stats.get("sent", 0),
            "errors": self._stats.get("errors", 0),
            "dead_letters": len(self.dead_letter_queue),
            "rules_count": len(self.rules),
            "channels": list(self._channel_handlers.keys()),
            "by_channel": {
                k.replace("sent:", ""): v
                for k, v in self._stats.items()
                if k.startswith("sent:")
            },
        }
