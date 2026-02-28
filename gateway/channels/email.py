"""
Email 渠道 - SMTP
"""

import asyncio
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from typing import Any, Optional

from gateway.channels import BaseChannel
from gateway.config import EmailConfig
from gateway.models import ChannelType, Message, SendResult


class EmailChannel(BaseChannel):
    channel_type = ChannelType.EMAIL

    def __init__(self, config: Optional[EmailConfig] = None):
        super().__init__(config)
        self.smtp_host = ""
        self.smtp_port = 587
        self.smtp_user = ""
        self.smtp_pass = ""
        self.smtp_from = ""
        self.use_tls = True
        if config:
            self.configure(config)

    def configure(self, config: EmailConfig) -> None:
        self.config = config
        self.smtp_host = config.smtp_host
        self.smtp_port = config.smtp_port
        self.smtp_user = config.smtp_user
        self.smtp_pass = config.smtp_pass
        self.smtp_from = config.smtp_from or config.smtp_user
        self.use_tls = config.use_tls
        self._enabled = bool(self.smtp_host and self.smtp_user)

    def _send_sync(self, message: Message) -> SendResult:
        """同步发送邮件"""
        subject = message.metadata.get("subject", "OmniMessage Notification")
        html = message.metadata.get("html", False)

        msg = MIMEMultipart() if message.attachments else None

        if message.attachments:
            # 多部分邮件
            assert msg is not None
            msg["Subject"] = subject
            msg["From"] = self.smtp_from
            msg["To"] = message.target
            msg.attach(MIMEText(message.content, "html" if html else "plain"))

            for att in message.attachments:
                if att.data:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(att.data)
                    encoders.encode_base64(part)
                    part.add_header(
                        "Content-Disposition",
                        f"attachment; filename={att.filename}",
                    )
                    msg.attach(part)
        else:
            # 简单文本邮件
            msg = MIMEText(message.content, "html" if html else "plain")
            msg["Subject"] = subject
            msg["From"] = self.smtp_from
            msg["To"] = message.target

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                if self.use_tls:
                    server.starttls()
                if self.smtp_user and self.smtp_pass:
                    server.login(self.smtp_user, self.smtp_pass)
                server.send_message(msg)
            return SendResult(
                success=True,
                message_id=message.id,
                channel=self.channel_type,
            )
        except Exception as e:
            return SendResult(
                success=False,
                message_id=message.id,
                channel=self.channel_type,
                error=str(e),
            )

    async def send(self, message: Message) -> SendResult:
        if not self._enabled:
            return SendResult(
                success=False,
                message_id=message.id,
                channel=self.channel_type,
                error="Email not configured: missing SMTP settings",
            )

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._send_sync, message)

    async def validate(self) -> bool:
        return bool(self.smtp_host and self.smtp_user)
