"""
Tests for gateway.channels - All channel implementations
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from gateway.channels import BaseChannel
from gateway.channels.telegram import TelegramChannel
from gateway.channels.whatsapp import WhatsAppChannel
from gateway.channels.discord import DiscordChannel
from gateway.channels.slack import SlackChannel
from gateway.channels.email import EmailChannel
from gateway.channels.webhook import WebhookChannel
from gateway.config import (
    DiscordConfig,
    EmailConfig,
    SlackConfig,
    TelegramConfig,
    WebhookConfig,
    WhatsAppConfig,
)
from gateway.models import ChannelType, Message, SendResult


def make_message(channel, target="test-target", content="Hello"):
    return Message(
        from_channel=ChannelType.WEBHOOK,
        to_channel=channel,
        content=content,
        target=target,
    )


# ── Telegram ─────────────────────────────────────────────

class TestTelegramChannel:
    def test_disabled_without_token(self):
        ch = TelegramChannel(TelegramConfig(token=""))
        assert ch.enabled is False

    def test_enabled_with_token(self):
        ch = TelegramChannel(TelegramConfig(token="bot123:abc"))
        assert ch.enabled is True

    @pytest.mark.asyncio
    async def test_send_disabled(self):
        ch = TelegramChannel(TelegramConfig(token=""))
        msg = make_message(ChannelType.TELEGRAM)
        result = await ch.send(msg)
        assert result.success is False
        assert "not configured" in result.error

    @pytest.mark.asyncio
    async def test_send_success(self):
        ch = TelegramChannel(TelegramConfig(token="bot123:abc"))
        msg = make_message(ChannelType.TELEGRAM, target="12345")

        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True, "result": {"message_id": 1}}

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            result = await ch.send(msg)
            assert result.success is True

    @pytest.mark.asyncio
    async def test_send_exception(self):
        ch = TelegramChannel(TelegramConfig(token="bot123:abc"))
        msg = make_message(ChannelType.TELEGRAM)

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.side_effect = ConnectionError("timeout")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            result = await ch.send(msg)
            assert result.success is False
            assert "timeout" in result.error


# ── WhatsApp ─────────────────────────────────────────────

class TestWhatsAppChannel:
    def test_disabled_without_config(self):
        ch = WhatsAppChannel(WhatsAppConfig(token="", phone_id=""))
        assert ch.enabled is False

    def test_enabled_with_config(self):
        ch = WhatsAppChannel(WhatsAppConfig(token="tok", phone_id="123"))
        assert ch.enabled is True

    @pytest.mark.asyncio
    async def test_send_disabled(self):
        ch = WhatsAppChannel(WhatsAppConfig())
        msg = make_message(ChannelType.WHATSAPP)
        result = await ch.send(msg)
        assert result.success is False


# ── Discord ──────────────────────────────────────────────

class TestDiscordChannel:
    def test_disabled_without_webhook(self):
        ch = DiscordChannel(DiscordConfig(webhook_url=""))
        assert ch.enabled is False

    def test_enabled_with_webhook(self):
        ch = DiscordChannel(DiscordConfig(webhook_url="https://discord.com/api/webhooks/xxx"))
        assert ch.enabled is True

    @pytest.mark.asyncio
    async def test_send_disabled(self):
        ch = DiscordChannel(DiscordConfig(webhook_url=""))
        msg = make_message(ChannelType.DISCORD)
        result = await ch.send(msg)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_send_success(self):
        ch = DiscordChannel(DiscordConfig(webhook_url="https://discord.com/api/webhooks/xxx"))
        msg = make_message(ChannelType.DISCORD)

        mock_response = MagicMock()
        mock_response.status_code = 204

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            result = await ch.send(msg)
            assert result.success is True


# ── Slack ────────────────────────────────────────────────

class TestSlackChannel:
    def test_disabled_without_webhook(self):
        ch = SlackChannel(SlackConfig(webhook_url=""))
        assert ch.enabled is False

    @pytest.mark.asyncio
    async def test_send_disabled(self):
        ch = SlackChannel(SlackConfig(webhook_url=""))
        msg = make_message(ChannelType.SLACK)
        result = await ch.send(msg)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_send_success(self):
        ch = SlackChannel(SlackConfig(webhook_url="https://hooks.slack.com/xxx"))
        msg = make_message(ChannelType.SLACK)

        mock_response = MagicMock()
        mock_response.text = "ok"
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            result = await ch.send(msg)
            assert result.success is True


# ── Email ────────────────────────────────────────────────

class TestEmailChannel:
    def test_disabled_without_smtp(self):
        ch = EmailChannel(EmailConfig())
        assert ch.enabled is False

    def test_enabled_with_smtp(self):
        ch = EmailChannel(EmailConfig(smtp_host="smtp.gmail.com", smtp_user="user@gmail.com"))
        assert ch.enabled is True

    @pytest.mark.asyncio
    async def test_send_disabled(self):
        ch = EmailChannel(EmailConfig())
        msg = make_message(ChannelType.EMAIL, target="user@example.com")
        result = await ch.send(msg)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_send_success(self):
        ch = EmailChannel(
            EmailConfig(
                smtp_host="smtp.test.com",
                smtp_port=587,
                smtp_user="test@test.com",
                smtp_pass="pass",
            )
        )
        msg = make_message(ChannelType.EMAIL, target="dest@test.com")

        with patch("smtplib.SMTP") as MockSMTP:
            mock_server = MagicMock()
            MockSMTP.return_value.__enter__ = MagicMock(return_value=mock_server)
            MockSMTP.return_value.__exit__ = MagicMock(return_value=False)

            result = await ch.send(msg)
            assert result.success is True


# ── Webhook ──────────────────────────────────────────────

class TestWebhookChannel:
    def test_always_enabled(self):
        ch = WebhookChannel(WebhookConfig())
        assert ch.enabled is True

    @pytest.mark.asyncio
    async def test_send_no_target(self):
        ch = WebhookChannel(WebhookConfig())
        msg = make_message(ChannelType.WEBHOOK, target="")
        result = await ch.send(msg)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_send_success(self):
        ch = WebhookChannel(WebhookConfig())
        msg = make_message(ChannelType.WEBHOOK, target="https://example.com/hook")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"ok": true}'

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            result = await ch.send(msg)
            assert result.success is True

    def test_hmac_signature(self):
        ch = WebhookChannel(WebhookConfig(secret="my-secret"))
        sig = ch._sign_payload('{"test": true}')
        assert sig  # non-empty
        assert len(sig) == 64  # SHA256 hex

    def test_no_signature_without_secret(self):
        ch = WebhookChannel(WebhookConfig(secret=""))
        sig = ch._sign_payload('{"test": true}')
        assert sig == ""
