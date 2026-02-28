"""
OmniMessage CLI - 命令行消息发送工具
omni send / omni broadcast / omni stats / omni templates / omni schedule
"""

import argparse
import asyncio
import csv
import json
import os
import sys
from typing import Any, Dict, List, Optional

from gateway.config import GatewayConfig
from gateway.core import Gateway
from gateway.models import ChannelType, Message, MessagePriority
from gateway.store import MessageStore
from gateway.scheduler import MessageScheduler
from gateway.analytics import AnalyticsExporter, AnalyticsCollector


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="omni",
        description="OmniMessage Gateway CLI - One tool, all platforms",
    )
    parser.add_argument("--config", "-c", help="Config file (JSON)")
    parser.add_argument("--db", default="omni_messages.db", help="SQLite database path")

    sub = parser.add_subparsers(dest="command", help="Available commands")

    # ── send ──────────────────────────────────────────────
    p_send = sub.add_parser("send", help="Send a message")
    p_send.add_argument("channel", choices=["telegram", "whatsapp", "discord", "slack", "email", "webhook"])
    p_send.add_argument("target", help="Target (chat_id, phone, email, webhook_url)")
    p_send.add_argument("text", help="Message text")
    p_send.add_argument("--template", help="Template name")
    p_send.add_argument("--vars", help="Template variables (JSON string)")
    p_send.add_argument("--priority", type=int, default=5, choices=[0, 5, 8, 10])
    p_send.add_argument("--subject", help="Email subject")
    p_send.add_argument("--parse-mode", help="Telegram parse mode")

    # ── broadcast ─────────────────────────────────────────
    p_bc = sub.add_parser("broadcast", help="Broadcast to multiple channels")
    p_bc.add_argument("text", help="Message text")
    p_bc.add_argument("--targets", required=True, help='Targets JSON: [{"channel":"telegram","target":"123"}]')
    p_bc.add_argument("--template", help="Template name")

    # ── batch ─────────────────────────────────────────────
    p_batch = sub.add_parser("batch", help="Batch send from CSV/JSON file")
    p_batch.add_argument("file", help="CSV or JSON file path")
    p_batch.add_argument("--dry-run", action="store_true", help="Preview without sending")
    p_batch.add_argument("--delay", type=float, default=0.1, help="Delay between sends (seconds)")

    # ── stats ─────────────────────────────────────────────
    p_stats = sub.add_parser("stats", help="Show message statistics")
    p_stats.add_argument("--hours", type=int, default=24, help="Time window (hours)")
    p_stats.add_argument("--format", choices=["text", "json", "csv"], default="text")

    # ── history ───────────────────────────────────────────
    p_hist = sub.add_parser("history", help="Query message history")
    p_hist.add_argument("--channel", help="Filter by channel")
    p_hist.add_argument("--status", help="Filter by status")
    p_hist.add_argument("--target", help="Filter by target")
    p_hist.add_argument("--limit", type=int, default=20)
    p_hist.add_argument("--format", choices=["text", "json"], default="text")

    # ── templates ─────────────────────────────────────────
    p_tmpl = sub.add_parser("templates", help="Manage templates")
    tmpl_sub = p_tmpl.add_subparsers(dest="tmpl_action")
    tmpl_sub.add_parser("list", help="List templates")
    p_add = tmpl_sub.add_parser("add", help="Register template")
    p_add.add_argument("name", help="Template name")
    p_add.add_argument("template_str", help="Template string (Jinja2)")
    p_rm = tmpl_sub.add_parser("remove", help="Remove template")
    p_rm.add_argument("name", help="Template name")
    p_test = tmpl_sub.add_parser("test", help="Test render template")
    p_test.add_argument("name", help="Template name")
    p_test.add_argument("--vars", help="Variables (JSON)")

    # ── schedule ──────────────────────────────────────────
    p_sched = sub.add_parser("schedule", help="Schedule messages")
    sched_sub = p_sched.add_subparsers(dest="sched_action")
    p_s_add = sched_sub.add_parser("add", help="Schedule a message")
    p_s_add.add_argument("channel", help="Target channel")
    p_s_add.add_argument("target", help="Target address")
    p_s_add.add_argument("text", help="Message text")
    p_s_add.add_argument("--at", help="Send at (ISO 8601)")
    p_s_add.add_argument("--delay", type=int, help="Delay in seconds")
    p_s_list = sched_sub.add_parser("list", help="List scheduled messages")
    p_s_list.add_argument("--status", help="Filter by status")
    p_s_cancel = sched_sub.add_parser("cancel", help="Cancel a scheduled message")
    p_s_cancel.add_argument("entry_id", help="Schedule entry ID")

    # ── channels ──────────────────────────────────────────
    sub.add_parser("channels", help="List available channels")

    # ── version ───────────────────────────────────────────
    sub.add_parser("version", help="Show version")

    return parser


async def cmd_send(args, gateway: Gateway, store: MessageStore) -> None:
    """发送消息"""
    metadata: Dict[str, Any] = {}
    if args.subject:
        metadata["subject"] = args.subject
    if args.parse_mode:
        metadata["parse_mode"] = args.parse_mode

    template_vars = {}
    if args.vars:
        template_vars = json.loads(args.vars)

    msg = Message(
        from_channel=ChannelType.WEBHOOK,
        to_channel=ChannelType(args.channel),
        content=args.text,
        target=args.target,
        template=args.template,
        template_vars=template_vars,
        metadata=metadata,
        priority=MessagePriority(args.priority),
    )

    store.save_message(msg.to_dict())
    store.log_event(msg.id, "created", args.channel)

    result = await gateway.send(msg)

    if result.success:
        store.update_status(msg.id, "sent")
        store.log_event(msg.id, "sent", args.channel)
        print(f"✅ Sent via {args.channel} → {args.target}")
        print(f"   Message ID: {msg.id}")
    else:
        store.update_status(msg.id, "failed", result.error)
        store.log_event(msg.id, "failed", args.channel, result.error)
        print(f"❌ Failed: {result.error}")
        sys.exit(1)


async def cmd_broadcast(args, gateway: Gateway, store: MessageStore) -> None:
    """广播"""
    targets = json.loads(args.targets)
    text = args.text
    success = 0
    failed = 0

    for t in targets:
        ch = t.get("channel", "")
        target = t.get("target", "")
        try:
            msg = Message(
                from_channel=ChannelType.WEBHOOK,
                to_channel=ChannelType(ch),
                content=text,
                target=target,
                template=args.template,
            )
            store.save_message(msg.to_dict())
            result = await gateway.send(msg)
            if result.success:
                store.update_status(msg.id, "sent")
                success += 1
            else:
                store.update_status(msg.id, "failed", result.error)
                failed += 1
        except Exception as e:
            failed += 1
            print(f"  ❌ {ch}:{target} - {e}")

    print(f"\n📊 Broadcast: {success} sent, {failed} failed")


async def cmd_batch(args, gateway: Gateway, store: MessageStore) -> None:
    """批量发送"""
    file_path = args.file
    records: List[Dict] = []

    if file_path.endswith(".json"):
        with open(file_path) as f:
            records = json.load(f)
    elif file_path.endswith(".csv"):
        with open(file_path) as f:
            reader = csv.DictReader(f)
            records = list(reader)
    else:
        print("❌ Unsupported file format. Use .csv or .json")
        sys.exit(1)

    print(f"📋 Loaded {len(records)} messages")
    if args.dry_run:
        for i, r in enumerate(records[:5]):
            print(f"  [{i+1}] {r.get('channel')} → {r.get('target')}: {r.get('text', '')[:50]}...")
        if len(records) > 5:
            print(f"  ... and {len(records) - 5} more")
        print("\n🔍 Dry run complete. Remove --dry-run to send.")
        return

    success = 0
    failed = 0
    for i, r in enumerate(records):
        try:
            msg = Message(
                from_channel=ChannelType.WEBHOOK,
                to_channel=ChannelType(r["channel"]),
                content=r.get("text", r.get("message", "")),
                target=r["target"],
            )
            store.save_message(msg.to_dict())
            result = await gateway.send(msg)
            if result.success:
                store.update_status(msg.id, "sent")
                success += 1
            else:
                store.update_status(msg.id, "failed", result.error)
                failed += 1
        except Exception as e:
            failed += 1

        if args.delay > 0 and i < len(records) - 1:
            await asyncio.sleep(args.delay)

        if (i + 1) % 10 == 0:
            print(f"  Progress: {i + 1}/{len(records)}")

    print(f"\n📊 Batch: {success} sent, {failed} failed (total: {len(records)})")


def cmd_stats(args, store: MessageStore) -> None:
    """统计"""
    stats = store.get_stats(hours=args.hours)

    if args.format == "json":
        print(json.dumps(stats, indent=2))
    elif args.format == "csv":
        print("status,count")
        for s, c in stats.get("by_status", {}).items():
            print(f"{s},{c}")
    else:
        print(f"\n📊 Message Statistics (last {args.hours}h)")
        print("─" * 40)
        print(f"  Total:        {stats['total']}")
        print(f"  Success Rate: {stats['success_rate']}%")
        print()
        print("  By Status:")
        for s, c in stats.get("by_status", {}).items():
            print(f"    {s}: {c}")
        print()
        print("  By Channel:")
        for ch, c in stats.get("by_channel", {}).items():
            print(f"    {ch}: {c}")


def cmd_history(args, store: MessageStore) -> None:
    """历史查询"""
    messages = store.query_messages(
        channel=args.channel,
        status=args.status,
        target=args.target,
        limit=args.limit,
    )

    if args.format == "json":
        print(json.dumps(messages, indent=2))
    else:
        print(f"\n📋 Message History ({len(messages)} results)")
        print("─" * 60)
        for m in messages:
            status_icon = "✅" if m["status"] == "sent" else "❌" if m["status"] == "failed" else "⏳"
            content_preview = (m.get("content") or "")[:40]
            print(f"  {status_icon} [{m['to_channel']}] {m['target']}: {content_preview}")
            print(f"     ID: {m['id']} | {m['created_at']}")


def cmd_channels(gateway: Gateway) -> None:
    """列出渠道"""
    print("\n📡 Available Channels")
    print("─" * 30)
    for ch_type, channel in gateway.channels.items():
        icon = "🟢" if channel.enabled else "🔴"
        print(f"  {icon} {ch_type.value}")


def cmd_templates(args, gateway: Gateway) -> None:
    """模板管理"""
    if args.tmpl_action == "list" or args.tmpl_action is None:
        templates = gateway.template_engine.list_templates()
        print("\n📝 Templates")
        print(f"  Memory: {templates.get('memory', [])}")
        print(f"  Files:  {templates.get('files', [])}")
    elif args.tmpl_action == "add":
        gateway.template_engine.register(args.name, args.template_str)
        print(f"✅ Registered template: {args.name}")
    elif args.tmpl_action == "remove":
        if gateway.template_engine.unregister(args.name):
            print(f"✅ Removed template: {args.name}")
        else:
            print(f"❌ Template not found: {args.name}")
    elif args.tmpl_action == "test":
        variables = json.loads(args.vars) if args.vars else {}
        result = gateway.template_engine.render(args.name, variables)
        print(f"📝 Rendered:\n{result}")


def cmd_schedule(args, scheduler: MessageScheduler, store: MessageStore) -> None:
    """定时消息"""
    from datetime import datetime

    if args.sched_action == "add":
        message_data = {
            "channel": args.channel,
            "target": args.target,
            "text": args.text,
        }
        if args.at:
            at = datetime.fromisoformat(args.at)
            entry_id = scheduler.schedule_at(message_data, at)
        elif args.delay:
            entry_id = scheduler.schedule_delay(message_data, args.delay)
        else:
            print("❌ Specify --at or --delay")
            return
        store.save_scheduled(entry_id, message_data, str(at if args.at else ""))
        print(f"✅ Scheduled: {entry_id}")

    elif args.sched_action == "list":
        entries = scheduler.list_entries(status=args.status if hasattr(args, "status") else None)
        print(f"\n⏰ Scheduled Messages ({len(entries)})")
        for e in entries:
            icon = "⏳" if e["status"] == "pending" else "✅" if e["status"] == "completed" else "❌"
            print(f"  {icon} {e['id'][:12]}... → {e['scheduled_at']}")
            print(f"     {e['message_data']}")

    elif args.sched_action == "cancel":
        if scheduler.cancel(args.entry_id):
            print(f"✅ Cancelled: {args.entry_id}")
        else:
            print(f"❌ Not found: {args.entry_id}")


def main(argv: List[str] = None) -> None:
    parser = create_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return

    if args.command == "version":
        from gateway import __version__
        print(f"OmniMessage Gateway v{__version__}")
        return

    # 初始化
    config = GatewayConfig.from_env()
    gateway = Gateway(config)
    store = MessageStore(args.db)
    scheduler = MessageScheduler()

    if args.command == "channels":
        cmd_channels(gateway)
    elif args.command == "stats":
        cmd_stats(args, store)
    elif args.command == "history":
        cmd_history(args, store)
    elif args.command == "templates":
        cmd_templates(args, gateway)
    elif args.command == "schedule":
        cmd_schedule(args, scheduler, store)
    elif args.command in ("send", "broadcast", "batch"):
        loop = asyncio.new_event_loop()
        try:
            if args.command == "send":
                loop.run_until_complete(cmd_send(args, gateway, store))
            elif args.command == "broadcast":
                loop.run_until_complete(cmd_broadcast(args, gateway, store))
            elif args.command == "batch":
                loop.run_until_complete(cmd_batch(args, gateway, store))
        finally:
            loop.close()

    store.close()


if __name__ == "__main__":
    main()
