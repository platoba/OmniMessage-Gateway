"""
Tests for gateway.api - FastAPI REST endpoints
"""

import os
import pytest
from unittest.mock import AsyncMock, patch

# Set env before import
os.environ["OMNI_API_KEY"] = "test-api-key"

from httpx import AsyncClient, ASGITransport
from gateway.api import create_app
from gateway.config import GatewayConfig
from gateway.models import ChannelType, SendResult


@pytest.fixture
def config():
    return GatewayConfig(api_key="test-api-key")


@pytest.fixture
def app(config):
    return create_app(config)


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def auth_headers():
    return {"X-API-Key": "test-api-key"}


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "channels" in data
        assert "version" in data

    @pytest.mark.asyncio
    async def test_channels_list(self, client):
        resp = await client.get("/channels")
        assert resp.status_code == 200
        data = resp.json()
        assert "channels" in data
        names = [ch["name"] for ch in data["channels"]]
        assert "telegram" in names
        assert "webhook" in names


class TestAuthMiddleware:
    @pytest.mark.asyncio
    async def test_send_without_key(self, client):
        resp = await client.post("/send", json={"channel": "telegram", "target": "123", "text": "hi"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_send_with_wrong_key(self, client):
        resp = await client.post(
            "/send",
            json={"channel": "telegram", "target": "123", "text": "hi"},
            headers={"X-API-Key": "wrong"},
        )
        assert resp.status_code == 401


class TestSendEndpoint:
    @pytest.mark.asyncio
    async def test_send_missing_fields(self, client, auth_headers):
        resp = await client.post("/send", json={"channel": "telegram"}, headers=auth_headers)
        assert resp.status_code == 422  # Pydantic validation

    @pytest.mark.asyncio
    async def test_send_invalid_channel(self, client, auth_headers):
        resp = await client.post(
            "/send",
            json={"channel": "fax", "target": "123", "text": "hello"},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert "Unknown channel" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_send_no_text_or_template(self, client, auth_headers):
        resp = await client.post(
            "/send",
            json={"channel": "telegram", "target": "123"},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_send_to_webhook(self, client, auth_headers):
        """Webhook channel is always enabled, so we can test a real send path"""
        with patch("gateway.channels.webhook.httpx.AsyncClient") as MockClient:
            from unittest.mock import MagicMock

            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.text = '{"received": true}'

            mock_client_instance = AsyncMock()
            mock_client_instance.post.return_value = mock_response
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client_instance

            resp = await client.post(
                "/send",
                json={
                    "channel": "webhook",
                    "target": "https://httpbin.org/post",
                    "text": "Test webhook",
                },
                headers=auth_headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True


class TestBroadcastEndpoint:
    @pytest.mark.asyncio
    async def test_broadcast_missing_targets(self, client, auth_headers):
        resp = await client.post(
            "/broadcast",
            json={"text": "hello"},
            headers=auth_headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_broadcast_invalid_channel(self, client, auth_headers):
        resp = await client.post(
            "/broadcast",
            json={
                "targets": [{"channel": "pigeon", "target": "nest"}],
                "text": "coo coo",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"][0]["success"] is False


class TestTemplateEndpoints:
    @pytest.mark.asyncio
    async def test_list_templates(self, client, auth_headers):
        resp = await client.get("/templates", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "memory" in data

    @pytest.mark.asyncio
    async def test_register_and_delete_template(self, client, auth_headers):
        # Register
        resp = await client.post(
            "/templates",
            json={"name": "test_tmpl", "template": "Hello {{ name }}!"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "registered"

        # Verify listed
        resp = await client.get("/templates", headers=auth_headers)
        assert "test_tmpl" in resp.json()["memory"]

        # Delete
        resp = await client.delete("/templates/test_tmpl", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["status"] == "removed"

    @pytest.mark.asyncio
    async def test_delete_nonexistent_template(self, client, auth_headers):
        resp = await client.delete("/templates/nope", headers=auth_headers)
        assert resp.status_code == 404


class TestDLQEndpoints:
    @pytest.mark.asyncio
    async def test_get_dlq(self, client, auth_headers):
        resp = await client.get("/dlq", headers=auth_headers)
        assert resp.status_code == 200
        assert "count" in resp.json()

    @pytest.mark.asyncio
    async def test_clear_dlq(self, client, auth_headers):
        resp = await client.delete("/dlq", headers=auth_headers)
        assert resp.status_code == 200
        assert "cleared" in resp.json()


class TestStatsEndpoint:
    @pytest.mark.asyncio
    async def test_stats(self, client, auth_headers):
        resp = await client.get("/stats", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "active_channels" in data
        assert "routing" in data
        assert "templates" in data


class TestWebhookReceiver:
    @pytest.mark.asyncio
    async def test_receive_channel_webhook(self, client):
        resp = await client.post(
            "/webhook/telegram",
            json={"event": "message", "data": {"text": "hello"}},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "received"
        assert resp.json()["channel"] == "telegram"

    @pytest.mark.asyncio
    async def test_receive_generic_webhook(self, client):
        resp = await client.post(
            "/webhook",
            json={"event": "payment_received", "data": {"amount": 100}},
        )
        assert resp.status_code == 200
        assert resp.json()["event"] == "payment_received"
