"""
FastAPI 应用 - Webhook 接收端点 + REST API
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from gateway import __version__
from gateway.core import Gateway
from gateway.config import GatewayConfig
from gateway.models import ChannelType, Message, MessagePriority

logger = logging.getLogger("omni.api")

# ── Pydantic Models ──────────────────────────────────────

class SendRequest(BaseModel):
    channel: str = Field(..., description="Target channel: telegram/whatsapp/discord/slack/email/webhook")
    target: str = Field(..., description="Target address (chat_id, phone, email, url)")
    text: str = Field("", description="Message text")
    message: str = Field("", description="Alias for text")
    template: Optional[str] = Field(None, description="Template name")
    template_vars: Dict[str, Any] = Field(default_factory=dict, description="Template variables")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Extra metadata")
    priority: int = Field(5, description="Priority (0=low, 5=normal, 8=high, 10=critical)")
    subject: Optional[str] = Field(None, description="Email subject")
    parse_mode: Optional[str] = Field(None, description="Telegram parse mode")
    username: Optional[str] = Field(None, description="Discord webhook username")


class BroadcastRequest(BaseModel):
    targets: List[Dict[str, str]] = Field(..., description="List of {channel, target}")
    text: str = Field("", description="Message text")
    message: str = Field("", description="Alias for text")
    template: Optional[str] = Field(None, description="Template name")
    template_vars: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TemplateRegisterRequest(BaseModel):
    name: str
    template: str


class WebhookPayload(BaseModel):
    """通用 Webhook 接收模型"""
    event: str = "message"
    data: Dict[str, Any] = Field(default_factory=dict)


# ── App Factory ──────────────────────────────────────────

def create_app(config: Optional[GatewayConfig] = None) -> FastAPI:
    """创建 FastAPI 应用"""
    config = config or GatewayConfig.from_env()
    gateway = Gateway(config)

    app = FastAPI(
        title="OmniMessage Gateway",
        version=__version__,
        description="统一多渠道消息网关 - One API, All Platforms",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 挂载 gateway 实例
    app.state.gateway = gateway
    app.state.config = config

    # ── Auth 依赖 ────────────────────────────────────────

    def verify_api_key(x_api_key: str = Header(None)):
        if x_api_key != config.api_key:
            raise HTTPException(status_code=401, detail="Invalid API key")

    # ── Health & Info ────────────────────────────────────

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "version": __version__,
            "channels": {
                ch.value: gateway.channels[ch].enabled
                for ch in gateway.channels
            },
            "stats": gateway.stats,
        }

    @app.get("/channels")
    async def list_channels():
        return {
            "channels": [
                {
                    "name": ch.value,
                    "enabled": gateway.channels[ch].enabled,
                }
                for ch in gateway.channels
            ]
        }

    # ── Send ─────────────────────────────────────────────

    @app.post("/send")
    async def send_message(req: SendRequest, x_api_key: str = Header(None)):
        verify_api_key(x_api_key)

        text = req.text or req.message
        if not text and not req.template:
            raise HTTPException(status_code=400, detail="Required: text or template")

        try:
            channel_type = ChannelType(req.channel)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown channel: {req.channel}. Available: {[c.value for c in ChannelType]}",
            )

        metadata = req.metadata.copy()
        if req.subject:
            metadata["subject"] = req.subject
        if req.parse_mode:
            metadata["parse_mode"] = req.parse_mode
        if req.username:
            metadata["username"] = req.username

        msg = Message(
            from_channel=ChannelType.WEBHOOK,
            to_channel=channel_type,
            content=text,
            target=req.target,
            template=req.template,
            template_vars=req.template_vars,
            metadata=metadata,
            priority=MessagePriority(req.priority),
        )

        result = await gateway.send(msg)
        return result.to_dict()

    # ── Broadcast ────────────────────────────────────────

    @app.post("/broadcast")
    async def broadcast(req: BroadcastRequest, x_api_key: str = Header(None)):
        verify_api_key(x_api_key)

        text = req.text or req.message
        if not text and not req.template:
            raise HTTPException(status_code=400, detail="Required: text or template")

        results = []
        for t in req.targets:
            try:
                channel_type = ChannelType(t.get("channel", ""))
            except ValueError:
                results.append({
                    "success": False,
                    "error": f"Unknown channel: {t.get('channel')}",
                    "target": t.get("target"),
                })
                continue

            msg = Message(
                from_channel=ChannelType.WEBHOOK,
                to_channel=channel_type,
                content=text,
                target=t.get("target", ""),
                template=req.template,
                template_vars=req.template_vars,
                metadata=req.metadata,
            )
            result = await gateway.send(msg)
            results.append(result.to_dict())

        return {"results": results}

    # ── Webhook 接收 ─────────────────────────────────────

    @app.post("/webhook/{channel}")
    async def receive_webhook(channel: str, request: Request):
        """接收来自各渠道的 Webhook 回调"""
        try:
            body = await request.json()
        except Exception:
            body = {}

        logger.info(f"Webhook received from {channel}: {body}")

        return {
            "status": "received",
            "channel": channel,
            "event": body.get("event", "unknown"),
        }

    @app.post("/webhook")
    async def receive_generic_webhook(payload: WebhookPayload):
        """通用 Webhook 接收"""
        logger.info(f"Generic webhook: {payload.event}")
        return {"status": "received", "event": payload.event}

    # ── 模板管理 ─────────────────────────────────────────

    @app.get("/templates")
    async def list_templates(x_api_key: str = Header(None)):
        verify_api_key(x_api_key)
        return gateway.template_engine.list_templates()

    @app.post("/templates")
    async def register_template(req: TemplateRegisterRequest, x_api_key: str = Header(None)):
        verify_api_key(x_api_key)
        gateway.template_engine.register(req.name, req.template)
        return {"status": "registered", "name": req.name}

    @app.delete("/templates/{name}")
    async def delete_template(name: str, x_api_key: str = Header(None)):
        verify_api_key(x_api_key)
        removed = gateway.template_engine.unregister(name)
        if not removed:
            raise HTTPException(status_code=404, detail=f"Template not found: {name}")
        return {"status": "removed", "name": name}

    # ── 死信队列 ─────────────────────────────────────────

    @app.get("/dlq")
    async def get_dead_letters(x_api_key: str = Header(None), limit: int = 100):
        verify_api_key(x_api_key)
        return {
            "count": len(gateway.router.dead_letter_queue),
            "messages": gateway.router.get_dead_letters(limit),
        }

    @app.post("/dlq/{index}/retry")
    async def retry_dead_letter(index: int, x_api_key: str = Header(None)):
        verify_api_key(x_api_key)
        result = await gateway.router.retry_dead_letter(index)
        if result is None:
            raise HTTPException(status_code=404, detail="Dead letter not found")
        return result.to_dict()

    @app.delete("/dlq")
    async def clear_dead_letters(x_api_key: str = Header(None)):
        verify_api_key(x_api_key)
        count = gateway.router.clear_dead_letters()
        return {"cleared": count}

    # ── Stats ────────────────────────────────────────────

    @app.get("/stats")
    async def get_stats(x_api_key: str = Header(None)):
        verify_api_key(x_api_key)
        return gateway.stats

    return app


# ── 默认 app 实例 (用于 uvicorn 直接启动) ──────────────

app = create_app()
