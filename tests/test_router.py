"""
Tests for gateway.router - Routing engine, retry, dead letter queue
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from gateway.models import (
    ChannelType,
    Message,
    MessagePriority,
    MessageStatus,
    SendResult,
)
from gateway.router import DeadLetterEntry, RoutingEngine, RoutingRule


def make_message(channel=ChannelType.TELEGRAM, content="test", target="123"):
    return Message(
        from_channel=ChannelType.WEBHOOK,
        to_channel=channel,
        content=content,
        target=target,
    )


def make_success_result(msg):
    return SendResult(success=True, message_id=msg.id, channel=msg.to_channel)


def make_failure_result(msg, error="fail"):
    return SendResult(success=False, message_id=msg.id, channel=msg.to_channel, error=error)


class TestRoutingRules:
    def test_add_rule(self):
        engine = RoutingEngine()
        rule = RoutingRule(
            name="test",
            condition=lambda m: True,
            target_channel=ChannelType.TELEGRAM,
        )
        engine.add_rule(rule)
        assert len(engine.rules) == 1

    def test_rules_sorted_by_priority(self):
        engine = RoutingEngine()
        engine.add_rule(RoutingRule("low", lambda m: True, ChannelType.TELEGRAM, priority=1))
        engine.add_rule(RoutingRule("high", lambda m: True, ChannelType.DISCORD, priority=10))
        engine.add_rule(RoutingRule("mid", lambda m: True, ChannelType.SLACK, priority=5))
        assert engine.rules[0].name == "high"
        assert engine.rules[1].name == "mid"
        assert engine.rules[2].name == "low"

    def test_match_rule(self):
        engine = RoutingEngine()
        engine.add_rule(
            RoutingRule(
                "tg_only",
                condition=lambda m: "telegram" in m.content.lower(),
                target_channel=ChannelType.TELEGRAM,
            )
        )
        msg = make_message(content="send to telegram")
        assert engine.match_rule(msg) is not None

        msg2 = make_message(content="send to discord")
        assert engine.match_rule(msg2) is None

    def test_match_all_rules(self):
        engine = RoutingEngine()
        engine.add_rule(RoutingRule("all", lambda m: True, ChannelType.TELEGRAM))
        engine.add_rule(RoutingRule("also_all", lambda m: True, ChannelType.DISCORD))
        msg = make_message()
        matches = engine.match_all_rules(msg)
        assert len(matches) == 2

    def test_remove_rule(self):
        engine = RoutingEngine()
        engine.add_rule(RoutingRule("to_remove", lambda m: True, ChannelType.TELEGRAM))
        assert engine.remove_rule("to_remove") is True
        assert engine.remove_rule("nonexistent") is False
        assert len(engine.rules) == 0

    def test_disabled_rule_not_matched(self):
        engine = RoutingEngine()
        engine.add_rule(
            RoutingRule("disabled", lambda m: True, ChannelType.TELEGRAM, enabled=False)
        )
        msg = make_message()
        assert engine.match_rule(msg) is None

    def test_rule_with_exception_in_condition(self):
        def bad_condition(m):
            raise ValueError("oops")

        engine = RoutingEngine()
        engine.add_rule(RoutingRule("bad", bad_condition, ChannelType.TELEGRAM))
        msg = make_message()
        assert engine.match_rule(msg) is None


class TestRoutingEngine:
    @pytest.mark.asyncio
    async def test_route_success(self):
        engine = RoutingEngine()
        mock_channel = AsyncMock()
        msg = make_message()
        mock_channel.send.return_value = make_success_result(msg)
        engine.register_channel(ChannelType.TELEGRAM, mock_channel)

        result = await engine.route(msg)
        assert result.success is True
        mock_channel.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_route_no_handler(self):
        engine = RoutingEngine()
        msg = make_message(channel=ChannelType.DISCORD)
        result = await engine.route(msg)
        assert result.success is False
        assert "No handler" in result.error

    @pytest.mark.asyncio
    async def test_route_with_rule_transform(self):
        engine = RoutingEngine()
        mock_channel = AsyncMock()
        msg = make_message(channel=ChannelType.TELEGRAM, content="original")
        mock_channel.send.return_value = make_success_result(msg)
        engine.register_channel(ChannelType.DISCORD, mock_channel)

        def transform(m):
            m.content = "transformed"
            return m

        engine.add_rule(
            RoutingRule(
                "redirect",
                condition=lambda m: True,
                target_channel=ChannelType.DISCORD,
                transform=transform,
            )
        )

        result = await engine.route(msg)
        assert result.success is True
        call_msg = mock_channel.send.call_args[0][0]
        assert call_msg.content == "transformed"


class TestRetryMechanism:
    @pytest.mark.asyncio
    async def test_retry_then_succeed(self):
        engine = RoutingEngine(max_retries=2, retry_delay=0.01)
        mock_channel = AsyncMock()
        msg = make_message()

        # Fail first, succeed second
        mock_channel.send.side_effect = [
            make_failure_result(msg, "timeout"),
            make_success_result(msg),
        ]
        engine.register_channel(ChannelType.TELEGRAM, mock_channel)

        result = await engine.route(msg)
        assert result.success is True
        assert result.retry_count == 1
        assert mock_channel.send.await_count == 2

    @pytest.mark.asyncio
    async def test_all_retries_fail_goes_to_dlq(self):
        engine = RoutingEngine(max_retries=1, retry_delay=0.01)
        mock_channel = AsyncMock()
        msg = make_message()

        mock_channel.send.return_value = make_failure_result(msg, "permanent error")
        engine.register_channel(ChannelType.TELEGRAM, mock_channel)

        result = await engine.route(msg)
        assert result.success is False
        assert len(engine.dead_letter_queue) == 1
        assert "permanent error" in result.error

    @pytest.mark.asyncio
    async def test_exception_triggers_retry(self):
        engine = RoutingEngine(max_retries=1, retry_delay=0.01)
        mock_channel = AsyncMock()
        msg = make_message()

        mock_channel.send.side_effect = [
            ConnectionError("network down"),
            make_success_result(msg),
        ]
        engine.register_channel(ChannelType.TELEGRAM, mock_channel)

        result = await engine.route(msg)
        assert result.success is True


class TestDeadLetterQueue:
    @pytest.mark.asyncio
    async def test_get_dead_letters(self):
        engine = RoutingEngine(max_retries=0, retry_delay=0.01)
        mock_channel = AsyncMock()
        msg = make_message()
        mock_channel.send.return_value = make_failure_result(msg)
        engine.register_channel(ChannelType.TELEGRAM, mock_channel)

        await engine.route(msg)
        dls = engine.get_dead_letters()
        assert len(dls) == 1
        assert dls[0]["error"] == "fail"

    @pytest.mark.asyncio
    async def test_clear_dead_letters(self):
        engine = RoutingEngine(max_retries=0, retry_delay=0.01)
        mock_channel = AsyncMock()
        msg = make_message()
        mock_channel.send.return_value = make_failure_result(msg)
        engine.register_channel(ChannelType.TELEGRAM, mock_channel)

        await engine.route(msg)
        count = engine.clear_dead_letters()
        assert count == 1
        assert len(engine.dead_letter_queue) == 0

    @pytest.mark.asyncio
    async def test_retry_dead_letter(self):
        engine = RoutingEngine(max_retries=0, retry_delay=0.01)
        mock_channel = AsyncMock()
        msg = make_message()
        msg.max_retries = 0  # Override message-level retries too

        # First call fails, DLQ retry succeeds
        mock_channel.send.side_effect = [
            make_failure_result(msg),
            make_success_result(msg),
        ]
        engine.register_channel(ChannelType.TELEGRAM, mock_channel)

        await engine.route(msg)
        assert len(engine.dead_letter_queue) == 1

        result = await engine.retry_dead_letter(0)
        assert result.success is True
        assert len(engine.dead_letter_queue) == 0

    @pytest.mark.asyncio
    async def test_retry_invalid_index(self):
        engine = RoutingEngine()
        result = await engine.retry_dead_letter(999)
        assert result is None


class TestMiddleware:
    @pytest.mark.asyncio
    async def test_sync_middleware(self):
        engine = RoutingEngine()
        mock_channel = AsyncMock()
        msg = make_message(content="original")
        mock_channel.send.return_value = make_success_result(msg)
        engine.register_channel(ChannelType.TELEGRAM, mock_channel)

        def add_prefix(m):
            m.content = "[PREFIXED] " + m.content
            return m

        engine.add_middleware(add_prefix)
        await engine.route(msg)

        call_msg = mock_channel.send.call_args[0][0]
        assert call_msg.content.startswith("[PREFIXED]")

    @pytest.mark.asyncio
    async def test_async_middleware(self):
        engine = RoutingEngine()
        mock_channel = AsyncMock()
        msg = make_message(content="data")
        mock_channel.send.return_value = make_success_result(msg)
        engine.register_channel(ChannelType.TELEGRAM, mock_channel)

        async def async_transform(m):
            m.metadata["processed"] = True
            return m

        engine.add_middleware(async_transform)
        await engine.route(msg)

        call_msg = mock_channel.send.call_args[0][0]
        assert call_msg.metadata.get("processed") is True


class TestStats:
    @pytest.mark.asyncio
    async def test_stats_tracking(self):
        engine = RoutingEngine(max_retries=0, retry_delay=0.01)
        mock_channel = AsyncMock()
        msg = make_message()
        mock_channel.send.return_value = make_success_result(msg)
        engine.register_channel(ChannelType.TELEGRAM, mock_channel)

        await engine.route(msg)
        await engine.route(msg)

        s = engine.stats
        assert s["total"] == 2
        assert s["sent"] == 2
        assert s["errors"] == 0

    @pytest.mark.asyncio
    async def test_stats_with_errors(self):
        engine = RoutingEngine(max_retries=0, retry_delay=0.01)
        mock_channel = AsyncMock()
        msg = make_message()
        mock_channel.send.return_value = make_failure_result(msg)
        engine.register_channel(ChannelType.TELEGRAM, mock_channel)

        await engine.route(msg)
        s = engine.stats
        assert s["errors"] == 1
        assert s["dead_letters"] == 1
