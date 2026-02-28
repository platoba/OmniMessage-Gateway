"""
Slack 渠道 - Incoming Webhook
"""

from typing import Any, Optional

import httpx

from gateway.channels import BaseChannel
from gateway.config import SlackConfig
from gateway.models import ChannelType, Message, SendResult


class SlackChannel(BaseChannel):
    channel_type = ChannelType.SLACK

    def __init__(self, config: Optional[SlackConfig] = None):
        super().__init__(config)
        self.webhook_url = ""
        if config:
            self.configure(config)

    def configure(self, config: SlackConfig) -> None:
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
                error="Slack not configured: missing webhook URL",
            )

        payload: dict[str, Any] = {"text": message.content}

        # 支持 blocks
        if message.metadata.get("blocks"):
            payload["blocks"] = message.metadata["blocks"]

        # 支持指定 channel
        if message.metadata.get("channel"):
            payload["channel"] = message.metadata["channel"]

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(url, json=payload)
                success = resp.text == "ok"
                return SendResult(
                    success=success,
                    message_id=message.id,
                    channel=self.channel_type,
                    response={"text": resp.text, "status_code": resp.status_code},
                    error=None if success else resp.text,
                )
        except Exception as e:
            return SendResult(
                success=False,
                message_id=message.id,
                channel=self.channel_type,
                error=str(e),
            )

    async def validate(self) -> bool:
        return bool(self.webhook_url)
