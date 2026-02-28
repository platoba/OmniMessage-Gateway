"""
Telegram 渠道 - Bot API
"""

from typing import Any, Optional

import httpx

from gateway.channels import BaseChannel
from gateway.config import TelegramConfig
from gateway.models import ChannelType, Message, SendResult


class TelegramChannel(BaseChannel):
    channel_type = ChannelType.TELEGRAM

    def __init__(self, config: Optional[TelegramConfig] = None):
        super().__init__(config)
        self.token = ""
        self.parse_mode = "Markdown"
        self.disable_preview = True
        self.base_url = "https://api.telegram.org"
        if config:
            self.configure(config)

    def configure(self, config: TelegramConfig) -> None:
        self.config = config
        self.token = config.token
        self.parse_mode = config.parse_mode
        self.disable_preview = config.disable_preview
        self._enabled = bool(self.token)

    async def send(self, message: Message) -> SendResult:
        if not self._enabled:
            return SendResult(
                success=False,
                message_id=message.id,
                channel=self.channel_type,
                error="Telegram not configured: missing token",
            )

        payload = {
            "chat_id": message.target,
            "text": message.content,
            "parse_mode": message.metadata.get("parse_mode", self.parse_mode),
            "disable_web_page_preview": self.disable_preview,
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{self.base_url}/bot{self.token}/sendMessage",
                    json=payload,
                )
                data = resp.json()
                return SendResult(
                    success=data.get("ok", False),
                    message_id=message.id,
                    channel=self.channel_type,
                    response=data,
                )
        except Exception as e:
            return SendResult(
                success=False,
                message_id=message.id,
                channel=self.channel_type,
                error=str(e),
            )

    async def validate(self) -> bool:
        if not self.token:
            return False
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.base_url}/bot{self.token}/getMe")
                return resp.json().get("ok", False)
        except Exception:
            return False
