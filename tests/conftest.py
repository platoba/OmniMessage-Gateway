"""
Shared test fixtures
"""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure no real API calls
os.environ.setdefault("OMNI_API_KEY", "test-api-key")
os.environ.setdefault("TELEGRAM_TOKEN", "")
os.environ.setdefault("DISCORD_WEBHOOK", "")
os.environ.setdefault("SLACK_WEBHOOK", "")
os.environ.setdefault("WHATSAPP_TOKEN", "")
os.environ.setdefault("SMTP_HOST", "")


@pytest.fixture
def api_key():
    return "test-api-key"


@pytest.fixture
def headers(api_key):
    return {"X-API-Key": api_key, "Content-Type": "application/json"}


@pytest.fixture
def sample_message_data():
    return {
        "channel": "telegram",
        "target": "123456",
        "text": "Hello from OmniMessage!",
    }


@pytest.fixture
def sample_broadcast_data():
    return {
        "targets": [
            {"channel": "telegram", "target": "123456"},
            {"channel": "discord", "target": "https://discord.com/api/webhooks/xxx"},
        ],
        "text": "Broadcast test message",
    }
