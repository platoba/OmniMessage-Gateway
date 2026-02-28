"""
Webhook 渠道 - 通用 HTTP 回调
"""

import hashlib
import hmac
import json
from typing import Any, Optional

import httpx

from gateway.channels import BaseChannel
from gateway.config import WebhookConfig
from gateway.models import ChannelType, Message, SendResult


class WebhookChannel(BaseChannel):
    channel_type = ChannelType.WEBHOOK

    def __init__(self, config: Optional[WebhookConfig] = None):
        super().__init__(config)
        self.secret = ""
        self.timeout = 30
        if config:
            self.configure(config)

    def configure(self, config: WebhookConfig) -> None:
        self.config = config
        self.secret = config.secret
        self.timeout = config.timeout
        self._enabled = True  # Webhook 始终可用

    def _sign_payload(self, payload: str) -> str:
        """HMAC-SHA256 签名"""
        if not self.secret:
            return ""
        return hmac.new(
            self.secret.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()

    async def send(self, message: Message) -> SendResult:
        url = message.target
        if not url:
            return SendResult(
                success=False,
                message_id=message.id,
                channel=self.channel_type,
                error="Webhook target URL is required",
            )

        payload = {
            "event": message.metadata.get("event", "message"),
            "content": message.content,
            "message_id": message.id,
            "metadata": message.metadata,
        }
        payload_str = json.dumps(payload, ensure_ascii=False)

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "OmniMessage-Gateway/2.0",
        }

        # 添加签名
        sig = self._sign_payload(payload_str)
        if sig:
            headers["X-Signature-256"] = f"sha256={sig}"

        # 自定义 headers
        extra_headers = message.metadata.get("headers", {})
        headers.update(extra_headers)

        method = message.metadata.get("method", "POST").upper()

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                if method == "GET":
                    resp = await client.get(url, headers=headers)
                else:
                    resp = await client.post(url, content=payload_str, headers=headers)

                success = 200 <= resp.status_code < 300
                return SendResult(
                    success=success,
                    message_id=message.id,
                    channel=self.channel_type,
                    response={"status_code": resp.status_code, "body": resp.text[:500]},
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
        return True  # Webhook 始终可用
