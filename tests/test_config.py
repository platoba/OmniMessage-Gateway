"""
Tests for gateway.config - Configuration management
"""

import os
import pytest
from unittest.mock import patch

from gateway.config import (
    DiscordConfig,
    EmailConfig,
    GatewayConfig,
    RedisConfig,
    SlackConfig,
    TelegramConfig,
    WebhookConfig,
    WhatsAppConfig,
)


class TestTelegramConfig:
    def test_defaults(self):
        cfg = TelegramConfig()
        assert cfg.token == ""
        assert cfg.parse_mode == "Markdown"
        assert cfg.disable_preview is True

    def test_from_env(self):
        with patch.dict(os.environ, {"TELEGRAM_TOKEN": "bot123:abc", "TELEGRAM_PARSE_MODE": "HTML"}):
            cfg = TelegramConfig.from_env()
            assert cfg.token == "bot123:abc"
            assert cfg.parse_mode == "HTML"


class TestWhatsAppConfig:
    def test_defaults(self):
        cfg = WhatsAppConfig()
        assert cfg.token == ""
        assert cfg.phone_id == ""
        assert cfg.api_version == "v19.0"

    def test_from_env(self):
        with patch.dict(os.environ, {"WHATSAPP_TOKEN": "wa-tok", "WHATSAPP_PHONE_ID": "123"}):
            cfg = WhatsAppConfig.from_env()
            assert cfg.token == "wa-tok"
            assert cfg.phone_id == "123"


class TestDiscordConfig:
    def test_from_env(self):
        with patch.dict(os.environ, {"DISCORD_WEBHOOK": "https://discord.com/api/webhooks/xxx"}):
            cfg = DiscordConfig.from_env()
            assert cfg.webhook_url == "https://discord.com/api/webhooks/xxx"


class TestSlackConfig:
    def test_from_env(self):
        with patch.dict(os.environ, {"SLACK_WEBHOOK": "https://hooks.slack.com/xxx"}):
            cfg = SlackConfig.from_env()
            assert cfg.webhook_url == "https://hooks.slack.com/xxx"


class TestEmailConfig:
    def test_defaults(self):
        cfg = EmailConfig()
        assert cfg.smtp_port == 587
        assert cfg.use_tls is True

    def test_from_env(self):
        env = {
            "SMTP_HOST": "smtp.gmail.com",
            "SMTP_PORT": "465",
            "SMTP_USER": "user@gmail.com",
            "SMTP_PASS": "secret",
            "SMTP_FROM": "noreply@example.com",
            "SMTP_USE_TLS": "false",
        }
        with patch.dict(os.environ, env):
            cfg = EmailConfig.from_env()
            assert cfg.smtp_host == "smtp.gmail.com"
            assert cfg.smtp_port == 465
            assert cfg.smtp_user == "user@gmail.com"
            assert cfg.smtp_pass == "secret"
            assert cfg.smtp_from == "noreply@example.com"
            assert cfg.use_tls is False


class TestWebhookConfig:
    def test_defaults(self):
        cfg = WebhookConfig()
        assert cfg.secret == ""
        assert cfg.timeout == 30


class TestRedisConfig:
    def test_defaults(self):
        cfg = RedisConfig()
        assert cfg.url == "redis://localhost:6379/0"
        assert cfg.dlq_key == "omni:dlq"


class TestGatewayConfig:
    def test_defaults(self):
        cfg = GatewayConfig()
        assert cfg.api_key == "change-me"
        assert cfg.port == 8900
        assert cfg.max_retries == 3
        assert cfg.retry_delay == 1.0

    def test_from_env(self):
        env = {
            "OMNI_API_KEY": "my-secret-key",
            "OMNI_PORT": "9000",
            "OMNI_MAX_RETRIES": "5",
            "OMNI_DEBUG": "true",
        }
        with patch.dict(os.environ, env):
            cfg = GatewayConfig.from_env()
            assert cfg.api_key == "my-secret-key"
            assert cfg.port == 9000
            assert cfg.max_retries == 5
            assert cfg.debug is True

    def test_sub_configs_initialized(self):
        cfg = GatewayConfig()
        assert isinstance(cfg.telegram, TelegramConfig)
        assert isinstance(cfg.whatsapp, WhatsAppConfig)
        assert isinstance(cfg.discord, DiscordConfig)
        assert isinstance(cfg.slack, SlackConfig)
        assert isinstance(cfg.email, EmailConfig)
        assert isinstance(cfg.webhook, WebhookConfig)
        assert isinstance(cfg.redis, RedisConfig)
