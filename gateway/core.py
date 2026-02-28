"""
Gateway Core - 网关核心引擎
整合所有组件: 渠道管理 + 路由引擎 + 模板引擎
"""

import logging
from typing import Any, Dict, List, Optional

from gateway.config import GatewayConfig
from gateway.models import (
    ChannelType,
    Message,
    MessagePriority,
    SendResult,
)
from gateway.router import RoutingEngine, RoutingRule
from gateway.templates import TemplateEngine
from gateway.channels import BaseChannel
from gateway.channels.telegram import TelegramChannel
from gateway.channels.whatsapp import WhatsAppChannel
from gateway.channels.discord import DiscordChannel
from gateway.channels.slack import SlackChannel
from gateway.channels.email import EmailChannel
from gateway.channels.webhook import WebhookChannel

logger = logging.getLogger("omni.core")


class Gateway:
    """
    OmniMessage Gateway 核心
    统一管理所有渠道、路由和模板
    """

    def __init__(self, config: Optional[GatewayConfig] = None):
        self.config = config or GatewayConfig.from_env()
        self.channels: Dict[ChannelType, BaseChannel] = {}
        self.router = RoutingEngine(
            max_retries=self.config.max_retries,
            retry_delay=self.config.retry_delay,
        )
        self.template_engine = TemplateEngine(self.config.template_dir)
        self._setup_channels()

    def _setup_channels(self) -> None:
        """初始化所有渠道"""
        channel_map = {
            ChannelType.TELEGRAM: (TelegramChannel, self.config.telegram),
            ChannelType.WHATSAPP: (WhatsAppChannel, self.config.whatsapp),
            ChannelType.DISCORD: (DiscordChannel, self.config.discord),
            ChannelType.SLACK: (SlackChannel, self.config.slack),
            ChannelType.EMAIL: (EmailChannel, self.config.email),
            ChannelType.WEBHOOK: (WebhookChannel, self.config.webhook),
        }

        for ch_type, (ch_class, ch_config) in channel_map.items():
            channel = ch_class(ch_config)
            self.channels[ch_type] = channel
            self.router.register_channel(ch_type, channel)

            status = "enabled" if channel.enabled else "disabled"
            logger.info(f"Channel {ch_type.value}: {status}")

    def register_channel(self, channel: BaseChannel) -> None:
        """注册自定义渠道"""
        self.channels[channel.channel_type] = channel
        self.router.register_channel(channel.channel_type, channel)

    def add_rule(self, rule: RoutingRule) -> None:
        """添加路由规则"""
        self.router.add_rule(rule)

    def register_template(self, name: str, template_str: str) -> None:
        """注册消息模板"""
        self.template_engine.register(name, template_str)

    async def send(self, message: Message) -> SendResult:
        """
        发送消息 (核心方法)
        1. 渲染模板 (如果指定)
        2. 路由到目标渠道
        """
        # 模板渲染
        if message.template:
            try:
                message.content = self.template_engine.render(
                    message.template, message.template_vars
                )
            except Exception as e:
                logger.error(f"Template render failed: {e}")
                return SendResult(
                    success=False,
                    message_id=message.id,
                    channel=message.to_channel,
                    error=f"Template render failed: {e}",
                )

        return await self.router.route(message)

    async def broadcast(
        self,
        content: str,
        channels: List[ChannelType],
        targets: Dict[str, str],
        metadata: Optional[Dict[str, Any]] = None,
        priority: MessagePriority = MessagePriority.NORMAL,
    ) -> List[SendResult]:
        """广播到多个渠道"""
        results = []
        for ch in channels:
            target = targets.get(ch.value, "")
            if not target:
                continue

            msg = Message(
                from_channel=ChannelType.WEBHOOK,
                to_channel=ch,
                content=content,
                target=target,
                metadata=metadata or {},
                priority=priority,
            )
            result = await self.send(msg)
            results.append(result)

        return results

    def get_active_channels(self) -> List[str]:
        """获取已启用的渠道"""
        return [
            ch_type.value
            for ch_type, ch in self.channels.items()
            if ch.enabled
        ]

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "version": "2.0.0",
            "active_channels": self.get_active_channels(),
            "routing": self.router.stats,
            "templates": self.template_engine.list_templates(),
        }
