# OmniMessage Gateway

🔗 Unified multi-channel messaging gateway. One API, all platforms.

## Supported Channels

| Channel | Method | Auth |
|---------|--------|------|
| 📱 Telegram | Bot API | Bot Token |
| 💬 WhatsApp | Cloud API | Access Token |
| 🎮 Discord | Webhook | Webhook URL |
| 💼 Slack | Webhook | Webhook URL |
| 📧 Email | SMTP | SMTP credentials |

## Quick Start

```bash
git clone https://github.com/platoba/OmniMessage-Gateway.git
cd OmniMessage-Gateway
cp .env.example .env
pip install requests
python gateway.py
```

## API

### Send Message
```bash
curl -X POST http://localhost:8900/send \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{"channel": "telegram", "target": "123456", "text": "Hello!"}'
```

### Broadcast
```bash
curl -X POST http://localhost:8900/broadcast \
  -H "X-API-Key: your-key" \
  -d '{"targets": [
    {"channel": "telegram", "target": "123456"},
    {"channel": "discord", "target": "webhook_url"},
    {"channel": "slack", "target": "webhook_url"}
  ], "text": "Hello everyone!"}'
```

### Health Check
```bash
curl http://localhost:8900/health
```

## Deploy

```bash
docker build -t omni-gateway .
docker run -d -p 8900:8900 --env-file .env omni-gateway
```

## License

MIT

## 🔗 Related

- [MultiAffiliateTGBot](https://github.com/platoba/MultiAffiliateTGBot) - Affiliate bot
- [AI-Listing-Writer](https://github.com/platoba/AI-Listing-Writer) - AI listing generator
- [SocialMedia-AutoBot](https://github.com/platoba/SocialMedia-AutoBot) - Social media automation
