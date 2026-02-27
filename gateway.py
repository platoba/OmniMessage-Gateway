"""
OmniMessage Gateway - 统一多渠道消息网关
支持 Telegram / WhatsApp / Discord / Slack / WeChat / Email
统一API接口，一次集成，全渠道触达
"""

import os
import time
import json
import hmac
import hashlib
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from threading import Thread

# ── 配置 ──────────────────────────────────────────────────
PORT = int(os.environ.get("PORT", 8900))
API_KEY = os.environ.get("OMNI_API_KEY", "change-me")

# 各渠道配置
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "")
SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK", "")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_ID = os.environ.get("WHATSAPP_PHONE_ID", "")
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "")


# ── 渠道发送器 ────────────────────────────────────────────
class Channels:

    @staticmethod
    def telegram(chat_id, text, **kwargs):
        if not TELEGRAM_TOKEN:
            return {"ok": False, "error": "TELEGRAM_TOKEN not configured"}
        r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text,
                  "parse_mode": kwargs.get("parse_mode", "Markdown"),
                  "disable_web_page_preview": True}, timeout=15)
        return r.json()

    @staticmethod
    def discord(webhook_url, text, **kwargs):
        url = webhook_url or DISCORD_WEBHOOK
        if not url:
            return {"ok": False, "error": "DISCORD_WEBHOOK not configured"}
        r = requests.post(url, json={
            "content": text,
            "username": kwargs.get("username", "OmniMessage"),
        }, timeout=15)
        return {"ok": r.status_code == 204, "status": r.status_code}

    @staticmethod
    def slack(webhook_url, text, **kwargs):
        url = webhook_url or SLACK_WEBHOOK
        if not url:
            return {"ok": False, "error": "SLACK_WEBHOOK not configured"}
        r = requests.post(url, json={"text": text}, timeout=15)
        return {"ok": r.text == "ok", "response": r.text}

    @staticmethod
    def whatsapp(phone, text, **kwargs):
        if not WHATSAPP_TOKEN:
            return {"ok": False, "error": "WHATSAPP_TOKEN not configured"}
        r = requests.post(
            f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_ID}/messages",
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}",
                     "Content-Type": "application/json"},
            json={"messaging_product": "whatsapp", "to": phone,
                  "type": "text", "text": {"body": text}}, timeout=15)
        return r.json()

    @staticmethod
    def email(to, text, **kwargs):
        if not SMTP_HOST:
            return {"ok": False, "error": "SMTP not configured"}
        import smtplib
        from email.mime.text import MIMEText
        subject = kwargs.get("subject", "OmniMessage Notification")
        msg = MIMEText(text)
        msg["Subject"] = subject
        msg["From"] = SMTP_FROM or SMTP_USER
        msg["To"] = to
        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
                s.starttls()
                s.login(SMTP_USER, SMTP_PASS)
                s.send_message(msg)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}


CHANNEL_MAP = {
    "telegram": Channels.telegram,
    "discord": Channels.discord,
    "slack": Channels.slack,
    "whatsapp": Channels.whatsapp,
    "email": Channels.email,
}


# ── 统一发送 ──────────────────────────────────────────────
def send_message(channel, target, text, **kwargs):
    handler = CHANNEL_MAP.get(channel)
    if not handler:
        return {"ok": False, "error": f"Unknown channel: {channel}. Use: {list(CHANNEL_MAP.keys())}"}
    try:
        return handler(target, text, **kwargs)
    except Exception as e:
        return {"ok": False, "error": str(e)}


def broadcast(targets, text, **kwargs):
    """广播到多个渠道"""
    results = {}
    for t in targets:
        ch = t.get("channel")
        to = t.get("target")
        results[f"{ch}:{to}"] = send_message(ch, to, text, **kwargs)
    return results


# ── HTTP API ──────────────────────────────────────────────
stats = {"total": 0, "by_channel": {}, "errors": 0}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # 静默日志

    def _auth(self):
        key = self.headers.get("X-API-Key", "")
        if key != API_KEY:
            self._respond(401, {"error": "Invalid API key"})
            return False
        return True

    def _respond(self, code, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def do_GET(self):
        if self.path == "/health":
            channels = {ch: bool(globals().get(f"{ch.upper()}_TOKEN") or
                                 globals().get(f"{ch.upper()}_WEBHOOK") or
                                 (ch == "email" and SMTP_HOST))
                       for ch in CHANNEL_MAP}
            self._respond(200, {"status": "ok", "channels": channels, "stats": stats})
        elif self.path == "/channels":
            self._respond(200, {"channels": list(CHANNEL_MAP.keys())})
        else:
            self._respond(404, {"error": "Not found"})

    def do_POST(self):
        if not self._auth():
            return

        body = self._read_body()

        if self.path == "/send":
            channel = body.get("channel")
            target = body.get("target")
            text = body.get("text", body.get("message", ""))

            if not channel or not target or not text:
                self._respond(400, {"error": "Required: channel, target, text"})
                return

            result = send_message(channel, target, text,
                                  subject=body.get("subject"),
                                  parse_mode=body.get("parse_mode"),
                                  username=body.get("username"))

            stats["total"] += 1
            stats["by_channel"][channel] = stats["by_channel"].get(channel, 0) + 1
            if not result.get("ok"):
                stats["errors"] += 1

            self._respond(200, result)

        elif self.path == "/broadcast":
            targets = body.get("targets", [])
            text = body.get("text", body.get("message", ""))

            if not targets or not text:
                self._respond(400, {"error": "Required: targets[], text"})
                return

            results = broadcast(targets, text, subject=body.get("subject"))
            stats["total"] += len(targets)
            self._respond(200, {"results": results})

        else:
            self._respond(404, {"error": "Not found. Use /send or /broadcast"})


def main():
    active = [ch for ch in CHANNEL_MAP
              if globals().get(f"{ch.upper()}_TOKEN") or
                 globals().get(f"{ch.upper()}_WEBHOOK") or
                 (ch == "email" and SMTP_HOST)]

    print(f"\n{'='*50}")
    print(f"  OmniMessage Gateway v1.0")
    print(f"  Port: {PORT}")
    print(f"  Active channels: {', '.join(active) if active else 'none'}")
    print(f"{'='*50}")
    print(f"\n  POST /send     — 单发")
    print(f"  POST /broadcast — 广播")
    print(f"  GET  /health   — 健康检查")
    print(f"\n🚀 启动中...\n")

    server = HTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 已停止")
        server.server_close()


if __name__ == "__main__":
    main()
