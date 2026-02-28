"""
Discord 渠道 - Webhook API
"""

from typing import Any, Optional

import httpx

from gateway.channels import BaseChannel
from gateway.config import DiscordConfig
from gateway.models import ChannelType, Message, SendResult


class DiscordChannel(BaseChannel):
    channel_type = ChannelType.DISCORD

    def __init__(self, config: Optional[DiscordConfig] = None):
        super().__init__(config)
        self.webhook_url = ""
        if config:
            self.configure(config)

    def configure(self, config: DiscordConfig) -> None:
        self.config = config
        self.webhook_url = config.webhook_url
        self._enabled = bool(self.webhook_url)

    async def send(self, message: Message) -> SendResult:
        url = message.metadata.get("webhook_url") or self.webhook_url
        if not url:
            return SendResult(
                success=False,
                message_id=message.id,
                channel=self.channel_type,
                error="Discord not configured: missing webhook URL",
            )

        payload = {
            "content": message.content,
            "username": message.metadata.get("username", "OmniMessage"),
        }

        # 支持 embed
        if message.metadata.get("embed"):
            payload["embeds"] = [message.metadata["embed"]]

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(url, json=payload)
                success = resp.status_code in (200, 204)
                return SendResult(
                    success=success,
                    message_id=message.id,
                    channel=self.channel_type,
                    response={"status_code": resp.status_code},
                    error=None if success else f"HTTP {resp.status_code}",
                )
        except Exception as e:
            return SendResult(
                success=False,
                message_id=message.id,
                channel=self.channel_type,
                error=str(e),
            )

    async def validate(self) -> bool:
        if not self.webhook_url:
            return False
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(self.webhook_url)
                return resp.status_code == 200
        except Exception:
            return False
