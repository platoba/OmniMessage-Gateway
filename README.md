# OmniMessage Gateway v3.0

**统一多渠道消息网关 — One API, All Platforms**

[![CI](https://github.com/platoba/OmniMessage-Gateway/actions/workflows/ci.yml/badge.svg)](https://github.com/platoba/OmniMessage-Gateway/actions)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Send messages across Telegram, WhatsApp, Discord, Slack, Email, and Webhooks through a single unified API.

## ✨ Features

### Core
- 📡 **6 Channel Support**: Telegram Bot API, WhatsApp Cloud API, Discord Webhooks, Slack Webhooks, SMTP Email, Generic Webhooks
- 🔀 **Routing Engine**: Rule-based routing with priority matching, middleware chain, and message transformation
- 📝 **Template Engine**: Jinja2-based templates (file & memory), runtime registration
- 💀 **Dead Letter Queue**: Failed messages auto-retry with exponential backoff, inspect & retry from DLQ
- 🌐 **REST API**: FastAPI-powered HTTP API with OpenAPI docs

### v3.0 New
- 💾 **SQLite Message Store**: Persistent message history, delivery tracking, query/search/stats
- ⏱️ **Rate Limiter**: Per-channel token bucket rate limiting with burst support and cooldown
- ⏰ **Message Scheduler**: Schedule messages for future delivery (delay/at/recurring)
- 📊 **Analytics Engine**: Real-time success rates, latency percentiles (P50/P95/P99), error classification, trend analysis
- 🖥️ **CLI Tool**: Full-featured command-line interface for sending, broadcasting, batch import, stats, templates, scheduling

## 🚀 Quick Start

### Install
```bash
pip install -e ".[dev]"
```

### CLI Usage
```bash
# Send a message
omni send telegram 123456789 "Hello from OmniMessage!"

# Send with template
omni send telegram 123456789 "" --template welcome --vars '{"name": "John"}'

# Broadcast to multiple channels
omni broadcast "Big announcement!" \
  --targets '[{"channel":"telegram","target":"123"},{"channel":"discord","target":"https://..."}]'

# Batch send from CSV/JSON
omni batch messages.csv --delay 0.5
omni batch messages.json --dry-run

# Check statistics
omni stats --hours 24
omni stats --format json

# Query message history
omni history --channel telegram --status sent --limit 50

# Schedule messages
omni schedule add telegram 123456789 "Reminder!" --delay 3600
omni schedule list
omni schedule cancel <entry-id>

# Manage templates
omni templates list
omni templates add welcome "Hello {{ name }}, welcome!"
omni templates test welcome --vars '{"name": "World"}'
```

### API Usage
```bash
# Start server
uvicorn gateway.api:app --host 0.0.0.0 --port 8900

# Send via API
curl -X POST http://localhost:8900/send \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-key" \
  -d '{
    "channel": "telegram",
    "target": "123456789",
    "text": "Hello from API!"
  }'

# Broadcast
curl -X POST http://localhost:8900/broadcast \
  -H "X-API-Key: your-key" \
  -d '{
    "text": "Hello everyone!",
    "targets": [
      {"channel": "telegram", "target": "123"},
      {"channel": "discord", "target": "https://..."}
    ]
  }'
```

### Python SDK
```python
import asyncio
from gateway.core import Gateway
from gateway.models import Message, ChannelType

gateway = Gateway()

msg = Message(
    from_channel=ChannelType.WEBHOOK,
    to_channel=ChannelType.TELEGRAM,
    content="Hello!",
    target="123456789",
)

result = asyncio.run(gateway.send(msg))
print(f"Sent: {result.success}")
```

## 🏗️ Architecture

```
gateway/
├── __init__.py          # Package version
├── core.py              # Gateway core engine
├── models.py            # Unified message models
├── config.py            # Configuration management
├── router.py            # Routing engine + DLQ
├── templates.py         # Jinja2 template engine
├── api.py               # FastAPI REST API
├── store.py             # SQLite message persistence   [NEW]
├── rate_limiter.py      # Token bucket rate limiter    [NEW]
├── scheduler.py         # Message scheduler            [NEW]
├── analytics.py         # Analytics engine             [NEW]
├── cli.py               # CLI tool                     [NEW]
└── channels/
    ├── __init__.py      # BaseChannel ABC
    ├── telegram.py      # Telegram Bot API
    ├── whatsapp.py      # WhatsApp Cloud API
    ├── discord.py       # Discord Webhooks
    ├── slack.py         # Slack Webhooks
    ├── email.py         # SMTP Email
    └── webhook.py       # Generic Webhooks
```

## 📊 Analytics

```python
from gateway.analytics import AnalyticsCollector, AnalyticsExporter

collector = AnalyticsCollector()
collector.record_sent("telegram", latency_ms=45.2, target="user1")

# Get stats
print(collector.get_success_rate())       # 100.0
print(collector.get_latency_stats())      # {"avg_ms": 45.2, "p50_ms": ...}
print(collector.get_channel_stats())      # {"telegram": {"sent": 1, ...}}
print(collector.get_error_breakdown())    # {"timeout": 0, ...}

# Export
print(AnalyticsExporter.to_report(collector))
print(AnalyticsExporter.to_csv(collector))
```

## ⏱️ Rate Limiting

```python
from gateway.rate_limiter import RateLimiter, BucketConfig

limiter = RateLimiter(custom_limits={
    "telegram": BucketConfig(capacity=30, refill_rate=1.0, cooldown_ms=35),
})

if limiter.check("telegram", target="123"):
    # OK to send
    pass
else:
    wait = limiter.estimated_wait("telegram")
    print(f"Wait {wait}s")
```

## 🔧 Configuration

Environment variables:
```bash
# Gateway
OMNI_API_KEY=your-secret-key
OMNI_HOST=0.0.0.0
OMNI_PORT=8900

# Telegram
TELEGRAM_TOKEN=bot123:ABC-DEF

# WhatsApp Cloud API
WHATSAPP_TOKEN=your-token
WHATSAPP_PHONE_ID=123456

# Discord
DISCORD_WEBHOOK=https://discord.com/api/webhooks/...

# Slack
SLACK_WEBHOOK=https://hooks.slack.com/services/...

# Email
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASS=app-password
SMTP_FROM=you@gmail.com

# Webhook
WEBHOOK_SECRET=hmac-secret
```

## 🐳 Docker

```bash
docker-compose up -d
```

## 🧪 Testing

```bash
# Run all tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=gateway --cov-report=term-missing

# Specific module
pytest tests/test_store.py -v
pytest tests/test_rate_limiter.py -v
```

## 📜 Changelog

### v3.0.0 (2026-02-28)
- ✨ SQLite message store with delivery tracking
- ✨ Per-channel token bucket rate limiter
- ✨ Message scheduler (delay/at/recurring)
- ✨ Analytics engine (success rates, latency percentiles, error classification, trends)
- ✨ Full CLI tool (send/broadcast/batch/stats/history/templates/schedule)
- ✨ CSV/JSON batch import
- 📈 Test count: 113 → 200+

### v2.0.0
- 6-channel support (Telegram, WhatsApp, Discord, Slack, Email, Webhook)
- Routing engine with rule-based matching
- Jinja2 template engine
- Dead letter queue with retry
- FastAPI REST API
- Docker Compose

## 📄 License

MIT

## Priority Queue System (v3.1+)

Send messages with priority levels to ensure critical messages are delivered first:

```python
from gateway.priority_queue import Priority, PriorityQueueManager, PriorityQueueWorker

# Create queue manager
queue = PriorityQueueManager(max_size=10000)

# Enqueue messages with different priorities
await queue.enqueue(
    channel="telegram",
    target="123456789",
    content="System alert!",
    priority=Priority.CRITICAL,  # Highest priority
)

await queue.enqueue(
    channel="email",
    target="user@example.com",
    content="Daily digest",
    priority=Priority.LOW,  # Lower priority
)

# Create worker to process queue
async def send_callback(channel, target, content, metadata):
    # Your send logic here
    pass

worker = PriorityQueueWorker(queue, send_callback, worker_count=3)
await worker.start()

# Get queue statistics
stats = await queue.get_stats()
print(f"Queue size: {stats['queue_size']}")
print(f"By priority: {stats['current_by_priority']}")

# Get worker statistics
worker_stats = worker.get_stats()
print(f"Success rate: {worker_stats['success_rate']:.2%}")
```

### Priority Levels

- `CRITICAL` (0): System alerts, security notifications
- `HIGH` (1): User-triggered actions, important updates
- `NORMAL` (2): Regular messages (default)
- `LOW` (3): Newsletters, digests
- `BULK` (4): Mass campaigns, batch operations

### Features

- **Automatic Prioritization**: Higher priority messages always processed first
- **FIFO Within Priority**: Same priority messages processed in order
- **Smart Overflow**: Drops lowest priority when queue is full
- **Auto Retry**: Failed messages automatically requeued (configurable max retries)
- **Multi-Worker**: Concurrent processing with configurable worker count
- **Statistics**: Real-time queue and worker metrics
- **Async/Await**: Fully asynchronous with proper locking

