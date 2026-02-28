# Changelog

## [2.0.0] - 2026-02-28

### Added
- **Modular architecture**: `gateway/` package with clean separation of concerns
- **FastAPI REST API**: `/send`, `/broadcast`, `/health`, `/channels`, `/stats`, `/templates`, `/dlq`
- **6 channel implementations**: Telegram, WhatsApp, Discord, Slack, Email, Webhook
- **Routing engine**: Rule-based routing with priority ordering and message transforms
- **Retry mechanism**: Exponential backoff with configurable max retries
- **Dead letter queue (DLQ)**: Failed messages stored for inspection and retry
- **Template engine**: Jinja2-based, supports file + memory templates
- **Middleware pipeline**: Pre-processing hooks for message transformation
- **Async throughout**: Full async/await with httpx for HTTP channels
- **Webhook receiver**: Accept callbacks from external services
- **HMAC signatures**: Webhook payload signing with SHA-256
- **Docker Compose**: Gateway + Redis, health checks, auto-restart
- **Comprehensive tests**: 80+ tests across 6 test files (models, config, router, templates, channels, API)
- **GitHub Actions CI**: Lint + test (Python 3.10/3.11/3.12) + Docker build
- **Makefile**: dev/test/lint/run/docker commands

### Changed
- Migrated from single-file `gateway.py` to modular package
- Switched from `requests` to `httpx` (async)
- Upgraded from `http.server` to FastAPI + uvicorn

## [1.0.0] - 2026-02-27

### Added
- Initial single-file implementation (`gateway.py`)
- Basic HTTP API with `/send` and `/broadcast`
- 5 channels: Telegram, Discord, Slack, WhatsApp, Email
- Simple stats tracking
- Docker support
