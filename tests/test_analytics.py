"""
Tests for Analytics Engine
"""

import pytest
import time

from gateway.analytics import AnalyticsCollector, AnalyticsExporter


@pytest.fixture
def collector():
    return AnalyticsCollector()


@pytest.fixture
def populated_collector():
    """预填充数据的收集器"""
    c = AnalyticsCollector()
    for _ in range(7):
        c.record_sent("telegram", latency_ms=50.0, target="user1")
    for _ in range(3):
        c.record_sent("discord", latency_ms=120.0, target="user2")
    for _ in range(2):
        c.record_failed("telegram", error="Connection timeout")
    c.record_failed("discord", error="429 rate limited")
    c.record_failed("email", error="Auth failed 401")
    c.record_retry("telegram")
    c.record_retry("telegram")
    return c


class TestAnalyticsCollector:
    def test_record_sent(self, collector):
        collector.record_sent("telegram", latency_ms=100.0)
        assert collector._total_sent == 1
        assert collector._channel_sent["telegram"] == 1

    def test_record_failed(self, collector):
        collector.record_failed("telegram", error="timeout")
        assert collector._total_failed == 1
        assert collector._channel_failed["telegram"] == 1

    def test_record_retry(self, collector):
        collector.record_retry("telegram")
        assert collector._total_retried == 1

    def test_success_rate_all(self, populated_collector):
        rate = populated_collector.get_success_rate()
        # 10 sent, 4 failed = 10/14 ≈ 71.43%
        assert 71 <= rate <= 72

    def test_success_rate_by_channel(self, populated_collector):
        tg_rate = populated_collector.get_success_rate("telegram")
        # 7 sent, 2 failed = 7/9 ≈ 77.78%
        assert 77 <= tg_rate <= 78

    def test_success_rate_empty(self, collector):
        assert collector.get_success_rate() == 0.0

    def test_latency_stats(self, populated_collector):
        lat = populated_collector.get_latency_stats()
        assert lat["avg_ms"] > 0
        assert lat["p50_ms"] > 0
        assert lat["p95_ms"] > 0
        assert lat["samples"] == 10

    def test_latency_stats_empty(self, collector):
        lat = collector.get_latency_stats()
        assert lat["avg_ms"] == 0

    def test_channel_stats(self, populated_collector):
        cs = populated_collector.get_channel_stats()
        assert "telegram" in cs
        assert "discord" in cs
        assert cs["telegram"]["sent"] == 7
        assert cs["telegram"]["failed"] == 2
        assert cs["discord"]["sent"] == 3

    def test_error_breakdown(self, populated_collector):
        errors = populated_collector.get_error_breakdown()
        assert errors["timeout"] == 2
        assert errors["rate_limited"] == 1
        assert errors["auth_error"] == 1

    def test_error_classification(self):
        c = AnalyticsCollector
        assert c._classify_error("Connection timeout") == "timeout"
        assert c._classify_error("429 Too Many Requests") == "rate_limited"
        assert c._classify_error("rate limit exceeded") == "rate_limited"
        assert c._classify_error("401 Unauthorized") == "auth_error"
        assert c._classify_error("403 Forbidden") == "auth_error"
        assert c._classify_error("404 Not Found") == "not_found"
        assert c._classify_error("Connection refused") == "connection_error"
        assert c._classify_error("500 Internal Server Error") == "server_error"
        assert c._classify_error("502 Bad Gateway") == "server_error"
        assert c._classify_error("Something weird") == "other"

    def test_trend(self, populated_collector):
        trend = populated_collector.get_trend(minutes=5)
        assert trend["period_minutes"] == 5
        assert len(trend["data"]) == 6  # minutes + 1 (includes current minute)
        # 当前分钟应该有数据
        total_sent = sum(d["sent"] for d in trend["data"])
        assert total_sent == 10

    def test_top_targets(self, populated_collector):
        top = populated_collector.get_top_targets(5)
        assert len(top) == 2
        assert top[0]["target"] == "user1"
        assert top[0]["count"] == 7

    def test_summary(self, populated_collector):
        s = populated_collector.summary
        assert s["total_sent"] == 10
        assert s["total_failed"] == 4
        assert s["total_retried"] == 2
        assert "success_rate" in s
        assert "latency" in s
        assert "by_channel" in s
        assert "errors" in s

    def test_reset(self, populated_collector):
        populated_collector.reset()
        assert populated_collector._total_sent == 0
        assert populated_collector._total_failed == 0
        assert populated_collector.get_success_rate() == 0.0

    def test_target_tracking(self, collector):
        collector.record_sent("telegram", target="user_a")
        collector.record_sent("telegram", target="user_a")
        collector.record_sent("telegram", target="user_b")
        top = collector.get_top_targets()
        assert top[0]["target"] == "user_a"
        assert top[0]["count"] == 2


class TestAnalyticsExporter:
    def test_to_json(self, populated_collector):
        result = AnalyticsExporter.to_json(populated_collector)
        import json
        data = json.loads(result)
        assert data["total_sent"] == 10

    def test_to_csv(self, populated_collector):
        result = AnalyticsExporter.to_csv(populated_collector)
        lines = result.strip().split("\n")
        assert lines[0] == "channel,sent,failed,total,success_rate"
        assert len(lines) >= 3  # header + at least telegram & discord

    def test_to_report(self, populated_collector):
        report = AnalyticsExporter.to_report(populated_collector)
        assert "OmniMessage Analytics Report" in report
        assert "Total Sent:" in report
        assert "Success Rate:" in report
        assert "Channels" in report

    def test_to_report_empty(self, collector):
        report = AnalyticsExporter.to_report(collector)
        assert "No latency data" in report
