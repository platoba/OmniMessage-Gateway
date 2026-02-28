"""
WhatsApp 渠道 - Cloud API (Meta Business)
"""

from typing import Any, Optional

import httpx

from gateway.channels import BaseChannel
from gateway.config import WhatsAppConfig
from gateway.models import ChannelType, Message, SendResult


class WhatsAppChannel(BaseChannel):
    channel_type = ChannelType.WHATSAPP

    def __init__(self, config: Optional[WhatsAppConfig] = None):
        super().__init__(config)
        self.token = ""
        self.phone_id = ""
        self.api_version = "v19.0"
        self.base_url = "https://graph.facebook.com"
        if config:
            self.configure(config)

    def configure(self, config: WhatsAppConfig) -> None:
        self.config = config
        self.token = config.token
        self.phone_id = config.phone_id
        self.api_version = config.api_version
        self._enabled = bool(self.token and self.phone_id)

    async def send(self, message: Message) -> SendResult:
        if not self._enabled:
            return SendResult(
                success=False,
                message_id=message.id,
                channel=self.channel_type,
                error="WhatsApp not configured: missing token or phone_id",
            )

        payload = {
            "messaging_product": "whatsapp",
            "to": message.target,
            "type": "text",
            "text": {"body": message.content},
        }

        # 支持模板消息
        if message.metadata.get("wa_template"):
            payload = {
                "messaging_product": "whatsapp",
                "to": message.target,
                "type": "template",
                "template": message.metadata["wa_template"],
            }

        try:
            url = f"{self.base_url}/{self.api_version}/{self.phone_id}/messages"
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {self.token}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                data = resp.json()
                success = "messages" in data
                return SendResult(
                    success=success,
                    message_id=message.id,
                    channel=self.channel_type,
                    response=data,
                    error=None if success else data.get("error", {}).get("message", "Unknown error"),
                )
        except Exception as e:
            return SendResult(
                success=False,
                message_id=message.id,
                channel=self.channel_type,
                error=str(e),
            )

    async def validate(self) -> bool:
        return bool(self.token and self.phone_id)
