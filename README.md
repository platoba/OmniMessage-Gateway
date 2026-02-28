# OmniMessage Gateway

[![CI](https://github.com/platoba/OmniMessage-Gateway/actions/workflows/ci.yml/badge.svg)](https://github.com/platoba/OmniMessage-Gateway/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

🔗 **Unified multi-channel messaging gateway — One API, All Platforms.**

Send messages to Telegram, WhatsApp, Discord, Slack, Email, and custom webhooks through a single REST API. Features rule-based routing, retry with exponential backoff, dead letter queue, Jinja2 templates, and middleware pipeline.

## Features

| Feature | Description |
|---------|-------------|
| 📱 **6 Channels** | Telegram, WhatsApp, Discord, Slack, Email, Webhook |
| 🔀 **Smart Routing** | Rule-based routing with priority and transforms |
| 🔄 **Auto Retry** | Exponential backoff retry mechanism |
| 💀 **Dead Letter Queue** | Failed messages stored for inspection/retry |
| 📝 **Templates** | Jinja2 templates (file + memory) |
| 🔌 **Middleware** | Pre-processing pipeline for message transforms |
| 📊 **Stats** | Real-time send/error/DLQ statistics |
| 🔐 **Auth** | API key authentication |
| 🐳 **Docker** | Docker Compose with Redis |

## Quick Start

```bash
git clone https://github.com/platoba/OmniMessage-Gateway.git
cd OmniMessage-Gateway

# Setup
cp .env.example .env
# Edit .env with your channel credentials

# Install & run
pip install -r requirements.txt
uvicorn gateway.api:app --host 0.0.0.0 --port 8900 --reload
```

## API Reference

### Send Message
```bash
curl -X POST http://localhost:8900/send \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "channel": "telegram",
    "target": "123456789",
    "text": "Hello from OmniMessage! 🚀"
  }'
```

### Broadcast
```bash
curl -X POST http://localhost:8900/broadcast \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "targets": [
      {"channel": "telegram", "target": "123456789"},
      {"channel": "discord", "target": "https://discord.com/api/webhooks/xxx"},
      {"channel": "slack", "target": "https://hooks.slack.com/xxx"},
      {"channel": "email", "target": "user@example.com"}
    ],
    "text": "Hello everyone! 📢"
  }'
```

### Send with Template
```bash
# Register a template
curl -X POST http://localhost:8900/templates \
  -H "X-API-Key: your-key" \
  -d '{"name": "order_confirm", "template": "🛒 Order #{{ order_id }} confirmed! Total: ${{ total }}"}'

# Send using template
curl -X POST http://localhost:8900/send \
  -H "X-API-Key: your-key" \
  -d '{
    "channel": "telegram",
    "target": "123456789",
    "template": "order_confirm",
    "template_vars": {"order_id": "ORD-001", "total": "49.99"}
  }'
```

### Health Check
```bash
curl http://localhost:8900/health
```

### Dead Letter Queue
```bash
# View failed messages
curl http://localhost:8900/dlq -H "X-API-Key: your-key"

# Retry a dead letter
curl -X POST http://localhost:8900/dlq/0/retry -H "X-API-Key: your-key"

# Clear DLQ
curl -X DELETE http://localhost:8900/dlq -H "X-API-Key: your-key"
```

### Stats
```bash
curl http://localhost:8900/stats -H "X-API-Key: your-key"
```

## Supported Channels

| Channel | Method | Required Config |
|---------|--------|----------------|
| 📱 Telegram | Bot API | `TELEGRAM_TOKEN` |
| 💬 WhatsApp | Meta Cloud API | `WHATSAPP_TOKEN` + `WHATSAPP_PHONE_ID` |
| 🎮 Discord | Webhook | `DISCORD_WEBHOOK` |
| 💼 Slack | Incoming Webhook | `SLACK_WEBHOOK` |
| 📧 Email | SMTP | `SMTP_HOST` + `SMTP_USER` + `SMTP_PASS` |
| 🔗 Webhook | HTTP POST | Target URL per message |

## Architecture

```
gateway/
├── __init__.py          # Package + version
├── api.py               # FastAPI REST endpoints
├── config.py            # Configuration management (env → dataclass)
├── core.py              # Gateway engine (channels + routing + templates)
├── models.py            # Unified message models
├── router.py            # Routing engine + retry + DLQ
├── templates.py         # Jinja2 template engine
└── channels/
    ├── __init__.py      # BaseChannel ABC
    ├── telegram.py      # Telegram Bot API
    ├── whatsapp.py      # WhatsApp Cloud API
    ├── discord.py       # Discord Webhook
    ├── slack.py         # Slack Webhook
    ├── email.py         # SMTP
    └── webhook.py       # Generic HTTP webhook
```

## Docker Deployment

```bash
# Build and run with Redis
docker compose up -d

# View logs
docker compose logs -f gateway

# Stop
docker compose down
```

## Development

```bash
# Install dev dependencies
make dev

# Run tests
make test

# Run tests with coverage
make test-cov

# Lint
make lint

# Run dev server
make run
```

## Testing

80+ tests covering:
- **Models** — Message, SendResult, ChannelType serialization
- **Config** — Environment variable parsing, defaults
- **Router** — Routing rules, retry mechanism, DLQ, middleware
- **Templates** — Memory/file templates, Jinja2 rendering
- **Channels** — All 6 channel implementations
- **API** — All REST endpoints, auth, error handling

## License

MIT

## Related Projects

- [MultiAffiliateTGBot](https://github.com/platoba/MultiAffiliateTGBot) — Affiliate marketing bot
- [AI-Listing-Writer](https://github.com/platoba/AI-Listing-Writer) — AI listing generator
- [SocialMedia-AutoBot](https://github.com/platoba/SocialMedia-AutoBot) — Social media automation
- [Shopify-Scout](https://github.com/platoba/Shopify-Scout) — Shopify product scout
