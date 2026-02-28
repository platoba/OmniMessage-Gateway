"""
配置管理 - 集中管理所有环境变量和配置项
"""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TelegramConfig:
    token: str = ""
    parse_mode: str = "Markdown"
    disable_preview: bool = True

    @classmethod
    def from_env(cls) -> "TelegramConfig":
        return cls(
            token=os.environ.get("TELEGRAM_TOKEN", ""),
            parse_mode=os.environ.get("TELEGRAM_PARSE_MODE", "Markdown"),
            disable_preview=os.environ.get("TELEGRAM_DISABLE_PREVIEW", "true").lower() == "true",
        )


@dataclass
class WhatsAppConfig:
    token: str = ""
    phone_id: str = ""
    api_version: str = "v19.0"

    @classmethod
    def from_env(cls) -> "WhatsAppConfig":
        return cls(
            token=os.environ.get("WHATSAPP_TOKEN", ""),
            phone_id=os.environ.get("WHATSAPP_PHONE_ID", ""),
            api_version=os.environ.get("WHATSAPP_API_VERSION", "v19.0"),
        )


@dataclass
class DiscordConfig:
    webhook_url: str = ""

    @classmethod
    def from_env(cls) -> "DiscordConfig":
        return cls(webhook_url=os.environ.get("DISCORD_WEBHOOK", ""))


@dataclass
class SlackConfig:
    webhook_url: str = ""

    @classmethod
    def from_env(cls) -> "SlackConfig":
        return cls(webhook_url=os.environ.get("SLACK_WEBHOOK", ""))


@dataclass
class EmailConfig:
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_from: str = ""
    use_tls: bool = True

    @classmethod
    def from_env(cls) -> "EmailConfig":
        return cls(
            smtp_host=os.environ.get("SMTP_HOST", ""),
            smtp_port=int(os.environ.get("SMTP_PORT", "587")),
            smtp_user=os.environ.get("SMTP_USER", ""),
            smtp_pass=os.environ.get("SMTP_PASS", ""),
            smtp_from=os.environ.get("SMTP_FROM", ""),
            use_tls=os.environ.get("SMTP_USE_TLS", "true").lower() == "true",
        )


@dataclass
class WebhookConfig:
    secret: str = ""
    timeout: int = 30

    @classmethod
    def from_env(cls) -> "WebhookConfig":
        return cls(
            secret=os.environ.get("WEBHOOK_SECRET", ""),
            timeout=int(os.environ.get("WEBHOOK_TIMEOUT", "30")),
        )


@dataclass
class RedisConfig:
    url: str = "redis://localhost:6379/0"
    dlq_key: str = "omni:dlq"
    stats_key: str = "omni:stats"

    @classmethod
    def from_env(cls) -> "RedisConfig":
        return cls(
            url=os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
            dlq_key=os.environ.get("REDIS_DLQ_KEY", "omni:dlq"),
            stats_key=os.environ.get("REDIS_STATS_KEY", "omni:stats"),
        )


@dataclass
class GatewayConfig:
    """主配置 - 聚合所有子配置"""

    api_key: str = "change-me"
    host: str = "0.0.0.0"
    port: int = 8900
    debug: bool = False
    max_retries: int = 3
    retry_delay: float = 1.0
    template_dir: str = "templates"

    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    whatsapp: WhatsAppConfig = field(default_factory=WhatsAppConfig)
    discord: DiscordConfig = field(default_factory=DiscordConfig)
    slack: SlackConfig = field(default_factory=SlackConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    webhook: WebhookConfig = field(default_factory=WebhookConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)

    @classmethod
    def from_env(cls) -> "GatewayConfig":
        return cls(
            api_key=os.environ.get("OMNI_API_KEY", "change-me"),
            host=os.environ.get("OMNI_HOST", "0.0.0.0"),
            port=int(os.environ.get("OMNI_PORT", "8900")),
            debug=os.environ.get("OMNI_DEBUG", "false").lower() == "true",
            max_retries=int(os.environ.get("OMNI_MAX_RETRIES", "3")),
            retry_delay=float(os.environ.get("OMNI_RETRY_DELAY", "1.0")),
            template_dir=os.environ.get("OMNI_TEMPLATE_DIR", "templates"),
            telegram=TelegramConfig.from_env(),
            whatsapp=WhatsAppConfig.from_env(),
            discord=DiscordConfig.from_env(),
            slack=SlackConfig.from_env(),
            email=EmailConfig.from_env(),
            webhook=WebhookConfig.from_env(),
            redis=RedisConfig.from_env(),
        )
