"""
Tests for gateway.core - Gateway core engine
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from gateway.config import GatewayConfig
from gateway.core import Gateway
from gateway.models import ChannelType, Message, MessagePriority, SendResult


@pytest.fixture
def gateway():
    return Gateway(GatewayConfig())


class TestGatewayInit:
    def test_creates_all_channels(self, gateway):
        assert ChannelType.TELEGRAM in gateway.channels
        assert ChannelType.WHATSAPP in gateway.channels
        assert ChannelType.DISCORD in gateway.channels
        assert ChannelType.SLACK in gateway.channels
        assert ChannelType.EMAIL in gateway.channels
        assert ChannelType.WEBHOOK in gateway.channels

    def test_webhook_always_active(self, gateway):
        actives = gateway.get_active_channels()
        assert "webhook" in actives

    def test_stats(self, gateway):
        s = gateway.stats
        assert s["version"] == "2.0.0"
        assert "active_channels" in s
        assert "routing" in s
        assert "templates" in s


class TestGatewaySend:
    @pytest.mark.asyncio
    async def test_send_to_webhook(self, gateway):
        msg = Message(
            from_channel=ChannelType.WEBHOOK,
            to_channel=ChannelType.WEBHOOK,
            content="test",
            target="https://httpbin.org/post",
        )

        with patch("gateway.channels.webhook.httpx.AsyncClient") as MockClient:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = "{}"

            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            result = await gateway.send(msg)
            assert result.success is True

    @pytest.mark.asyncio
    async def test_send_with_template(self, gateway):
        gateway.register_template("notify", "🔔 {{ title }}: {{ body }}")

        msg = Message(
            from_channel=ChannelType.WEBHOOK,
            to_channel=ChannelType.WEBHOOK,
            content="",
            target="https://example.com/hook",
            template="notify",
            template_vars={"title": "Alert", "body": "Server down"},
        )

        with patch("gateway.channels.webhook.httpx.AsyncClient") as MockClient:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = "{}"

            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            result = await gateway.send(msg)
            assert result.success is True
            # Check template was rendered
            call_args = mock_client.post.call_args
            assert "Alert" in str(call_args)

    @pytest.mark.asyncio
    async def test_send_with_bad_template(self, gateway):
        msg = Message(
            from_channel=ChannelType.WEBHOOK,
            to_channel=ChannelType.WEBHOOK,
            content="",
            target="https://example.com/hook",
            template="nonexistent_template",
        )
        result = await gateway.send(msg)
        assert result.success is False
        assert "Template" in result.error


class TestGatewayBroadcast:
    @pytest.mark.asyncio
    async def test_broadcast(self, gateway):
        with patch("gateway.channels.webhook.httpx.AsyncClient") as MockClient:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = "{}"

            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            results = await gateway.broadcast(
                content="broadcast test",
                channels=[ChannelType.WEBHOOK],
                targets={"webhook": "https://example.com/hook"},
            )
            assert len(results) == 1
            assert results[0].success is True

    @pytest.mark.asyncio
    async def test_broadcast_skips_missing_targets(self, gateway):
        results = await gateway.broadcast(
            content="test",
            channels=[ChannelType.TELEGRAM, ChannelType.DISCORD],
            targets={},  # No targets
        )
        assert len(results) == 0


class TestGatewayCustomChannel:
    def test_register_custom_channel(self, gateway):
        mock_channel = MagicMock()
        mock_channel.channel_type = ChannelType.TELEGRAM
        mock_channel.enabled = True

        gateway.register_channel(mock_channel)
        assert gateway.channels[ChannelType.TELEGRAM] is mock_channel


class TestGatewayRouting:
    def test_add_rule(self, gateway):
        from gateway.router import RoutingRule

        rule = RoutingRule(
            name="test_rule",
            condition=lambda m: True,
            target_channel=ChannelType.WEBHOOK,
        )
        gateway.add_rule(rule)
        assert len(gateway.router.rules) >= 1
