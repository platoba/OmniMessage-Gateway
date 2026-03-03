"""
Tests for Health Monitor
"""

from datetime import datetime, timedelta

import pytest

from gateway.health_monitor import (
    ChannelHealth,
    ChannelState,
    FailoverRule,
    HealthMonitor,
    HealthProbe,
    SLATarget,
)

# ── Fixtures ─────────────────────────────────────────────

@pytest.fixture
def monitor():
    return HealthMonitor(
        failure_threshold=3,
        recovery_threshold=2,
        circuit_timeout_seconds=5.0,
    )


@pytest.fixture
def probe_ok():
    return HealthProbe(channel="telegram", success=True, latency_ms=120.0)


@pytest.fixture
def probe_fail():
    return HealthProbe(channel="telegram", success=False, latency_ms=0, error="Connection timeout")


# ── Registration ─────────────────────────────────────────

def test_register_channel(monitor):
    monitor.register_channel("telegram")
    health = monitor.get_health("telegram")
    assert health is not None
    assert health.state == ChannelState.HEALTHY
    assert health.total_probes == 0


def test_register_channel_idempotent(monitor):
    monitor.register_channel("telegram")
    monitor.register_channel("telegram")
    assert len(monitor.get_all_health()) == 1


def test_register_probe_function(monitor):
    monitor.register_probe("telegram", lambda: True)
    assert "telegram" in monitor._probe_functions
    assert monitor.get_health("telegram") is not None


# ── Probe Recording ─────────────────────────────────────

def test_record_success_probe(monitor, probe_ok):
    state = monitor.record_probe(probe_ok)
    assert state == ChannelState.HEALTHY
    health = monitor.get_health("telegram")
    assert health.total_probes == 1
    assert health.total_successes == 1
    assert health.consecutive_successes == 1


def test_record_failure_probe(monitor, probe_fail):
    state = monitor.record_probe(probe_fail)
    assert state == ChannelState.HEALTHY  # 1 failure not enough
    health = monitor.get_health("telegram")
    assert health.total_failures == 1
    assert health.consecutive_failures == 1
    assert health.last_error == "Connection timeout"


def test_consecutive_failures_reset_on_success(monitor, probe_ok, probe_fail):
    monitor.record_probe(probe_fail)
    monitor.record_probe(probe_fail)
    monitor.record_probe(probe_ok)
    health = monitor.get_health("telegram")
    assert health.consecutive_failures == 0
    assert health.consecutive_successes == 1


def test_uptime_calculation(monitor, probe_ok, probe_fail):
    monitor.record_probe(probe_ok)
    monitor.record_probe(probe_ok)
    monitor.record_probe(probe_fail)
    health = monitor.get_health("telegram")
    assert abs(health.uptime_percent - 66.667) < 0.01


# ── State Transitions ───────────────────────────────────

def test_healthy_to_degraded(monitor, probe_fail):
    # 2 consecutive failures -> degraded
    monitor.record_probe(probe_fail)
    state = monitor.record_probe(probe_fail)
    assert state == ChannelState.DEGRADED


def test_degraded_to_circuit_open(monitor, probe_fail):
    # 3 failures -> circuit open (threshold=3)
    for _ in range(3):
        state = monitor.record_probe(probe_fail)
    assert state == ChannelState.CIRCUIT_OPEN


def test_circuit_open_stays_during_timeout(monitor, probe_fail, probe_ok):
    for _ in range(3):
        monitor.record_probe(probe_fail)

    # Circuit is open, success within timeout doesn't help
    state = monitor.record_probe(probe_ok)
    # Within timeout, stays open
    assert state == ChannelState.CIRCUIT_OPEN


def test_circuit_open_to_recovering_after_timeout(monitor, probe_fail):
    for _ in range(3):
        monitor.record_probe(probe_fail)

    health = monitor.get_health("telegram")
    # Simulate timeout elapsed
    health.circuit_opened_at = datetime.utcnow() - timedelta(seconds=10)

    success_probe = HealthProbe(channel="telegram", success=True, latency_ms=100)
    state = monitor.record_probe(success_probe)
    assert state == ChannelState.RECOVERING


def test_recovering_to_healthy(monitor, probe_fail):
    # Set up recovering state
    monitor.register_channel("telegram")
    health = monitor.get_health("telegram")
    health.state = ChannelState.RECOVERING
    health.consecutive_successes = 0

    # Need recovery_threshold=2 successes
    probe1 = HealthProbe(channel="telegram", success=True, latency_ms=100)
    monitor.record_probe(probe1)
    probe2 = HealthProbe(channel="telegram", success=True, latency_ms=100)
    state = monitor.record_probe(probe2)
    assert state == ChannelState.HEALTHY


def test_recovering_failure_reopens_circuit(monitor, probe_fail):
    monitor.register_channel("telegram")
    health = monitor.get_health("telegram")
    health.state = ChannelState.RECOVERING
    health.consecutive_successes = 1

    state = monitor.record_probe(probe_fail)
    assert state == ChannelState.CIRCUIT_OPEN


def test_degraded_recovery(monitor, probe_ok, probe_fail):
    monitor.record_probe(probe_fail)
    monitor.record_probe(probe_fail)
    assert monitor.get_state("telegram") == ChannelState.DEGRADED

    # Recovery threshold=2 successes
    monitor.record_probe(probe_ok)
    state = monitor.record_probe(probe_ok)
    assert state == ChannelState.HEALTHY


# ── Availability ─────────────────────────────────────────

def test_is_available_healthy(monitor, probe_ok):
    monitor.record_probe(probe_ok)
    assert monitor.is_available("telegram") is True


def test_is_available_degraded(monitor, probe_fail):
    monitor.record_probe(probe_fail)
    monitor.record_probe(probe_fail)
    assert monitor.is_available("telegram") is True  # degraded still available


def test_is_available_circuit_open(monitor, probe_fail):
    for _ in range(3):
        monitor.record_probe(probe_fail)
    assert monitor.is_available("telegram") is False


def test_is_available_unknown_channel(monitor):
    assert monitor.is_available("unknown") is True


# ── Failover ─────────────────────────────────────────────

def test_no_failover_when_healthy(monitor, probe_ok):
    monitor.record_probe(probe_ok)
    monitor.add_failover_rule(FailoverRule(
        source_channel="telegram", target_channel="email",
    ))
    assert monitor.get_failover("telegram") is None


def test_failover_when_circuit_open(monitor, probe_fail):
    for _ in range(3):
        monitor.record_probe(probe_fail)

    # Register email as healthy
    monitor.record_probe(HealthProbe(channel="email", success=True, latency_ms=50))

    monitor.add_failover_rule(FailoverRule(
        source_channel="telegram", target_channel="email",
    ))

    assert monitor.get_failover("telegram") == "email"


def test_failover_skips_unavailable_target(monitor, probe_fail):
    # Both telegram and email are down
    for _ in range(3):
        monitor.record_probe(probe_fail)
        monitor.record_probe(HealthProbe(channel="email", success=False, latency_ms=0, error="down"))

    # Slack is up
    monitor.record_probe(HealthProbe(channel="slack", success=True, latency_ms=50))

    monitor.add_failover_rule(FailoverRule(
        source_channel="telegram", target_channel="email", priority=10,
    ))
    monitor.add_failover_rule(FailoverRule(
        source_channel="telegram", target_channel="slack", priority=5,
    ))

    assert monitor.get_failover("telegram") == "slack"


def test_failover_chain(monitor):
    monitor.register_channel("telegram")
    monitor.register_channel("email")
    monitor.register_channel("slack")

    monitor.add_failover_rule(FailoverRule(
        source_channel="telegram", target_channel="email",
    ))
    monitor.add_failover_rule(FailoverRule(
        source_channel="email", target_channel="slack",
    ))

    chain = monitor.get_failover_chain("telegram")
    assert chain == ["email", "slack"]


def test_failover_chain_no_cycles(monitor):
    monitor.register_channel("a")
    monitor.register_channel("b")
    monitor.add_failover_rule(FailoverRule(source_channel="a", target_channel="b"))
    monitor.add_failover_rule(FailoverRule(source_channel="b", target_channel="a"))
    chain = monitor.get_failover_chain("a")
    assert chain == ["b"]  # No cycle back to a


def test_disabled_failover_rule(monitor, probe_fail):
    for _ in range(3):
        monitor.record_probe(probe_fail)
    monitor.record_probe(HealthProbe(channel="email", success=True, latency_ms=50))
    monitor.add_failover_rule(FailoverRule(
        source_channel="telegram", target_channel="email", enabled=False,
    ))
    assert monitor.get_failover("telegram") is None


# ── SLA ──────────────────────────────────────────────────

def test_sla_compliant(monitor, probe_ok):
    for _ in range(10):
        monitor.record_probe(probe_ok)

    monitor.set_sla_target(SLATarget(
        channel="telegram", uptime_target=99.0, max_latency_ms=500,
    ))

    result = monitor.check_sla("telegram")
    assert result["compliant"] is True
    assert result["violations"] == []


def test_sla_uptime_violation(monitor, probe_ok, probe_fail):
    for _ in range(5):
        monitor.record_probe(probe_ok)
    for _ in range(5):
        monitor.record_probe(probe_fail)

    monitor.set_sla_target(SLATarget(
        channel="telegram", uptime_target=99.0,
    ))

    result = monitor.check_sla("telegram")
    assert result["compliant"] is False
    violations = result["violations"]
    assert any(v["metric"] == "uptime" for v in violations)


def test_sla_error_rate_violation(monitor, probe_ok, probe_fail):
    for _ in range(8):
        monitor.record_probe(probe_ok)
    for _ in range(2):
        monitor.record_probe(probe_fail)

    monitor.set_sla_target(SLATarget(
        channel="telegram", max_error_rate=1.0,
    ))

    result = monitor.check_sla("telegram")
    assert result["compliant"] is False
    violations = result["violations"]
    assert any(v["metric"] == "error_rate" for v in violations)


def test_sla_no_target(monitor, probe_ok):
    monitor.record_probe(probe_ok)
    result = monitor.check_sla("telegram")
    assert result["compliant"] is True
    assert result["sla_defined"] is False


def test_check_all_sla(monitor, probe_ok):
    for _ in range(10):
        monitor.record_probe(probe_ok)
        monitor.record_probe(HealthProbe(channel="email", success=True, latency_ms=50))

    monitor.set_sla_target(SLATarget(channel="telegram", uptime_target=99.0))
    monitor.set_sla_target(SLATarget(channel="email", uptime_target=99.0))

    result = monitor.check_all_sla()
    assert result["summary"]["total_channels"] == 2
    assert result["summary"]["compliant"] == 2


# ── Latency Stats ────────────────────────────────────────

def test_latency_average(monitor):
    for lat in [100, 200, 300]:
        monitor.record_probe(HealthProbe(channel="telegram", success=True, latency_ms=lat))

    health = monitor.get_health("telegram")
    assert abs(health.avg_latency_ms - 200.0) < 0.01


def test_latency_p95(monitor):
    for i in range(100):
        monitor.record_probe(HealthProbe(
            channel="telegram", success=True, latency_ms=float(i * 10),
        ))

    health = monitor.get_health("telegram")
    assert health.p95_latency_ms > 0


# ── Alert Callbacks ──────────────────────────────────────

def test_alert_callback_on_state_change(monitor, probe_fail):
    alerts = []
    monitor.add_alert_callback(lambda ch, old, new: alerts.append((ch, old.value, new.value)))

    monitor.record_probe(probe_fail)
    monitor.record_probe(probe_fail)
    # healthy -> degraded triggers alert
    assert len(alerts) == 1
    assert alerts[0] == ("telegram", "healthy", "degraded")


def test_no_alert_when_state_same(monitor, probe_ok):
    alerts = []
    monitor.add_alert_callback(lambda ch, old, new: alerts.append((ch, old.value, new.value)))

    monitor.record_probe(probe_ok)
    monitor.record_probe(probe_ok)
    assert len(alerts) == 0


def test_alert_callback_error_handled(monitor, probe_fail):
    def bad_callback(ch, old, new):
        raise ValueError("callback error")

    monitor.add_alert_callback(bad_callback)
    # Should not raise
    monitor.record_probe(probe_fail)
    monitor.record_probe(probe_fail)


# ── Probe History ────────────────────────────────────────

def test_probe_history(monitor, probe_ok):
    for _ in range(5):
        monitor.record_probe(probe_ok)

    history = monitor.get_probe_history("telegram")
    assert len(history) == 5
    assert all(h["success"] for h in history)


def test_probe_history_limit(monitor, probe_ok):
    for _ in range(10):
        monitor.record_probe(probe_ok)

    history = monitor.get_probe_history("telegram", limit=3)
    assert len(history) == 3


def test_probe_history_since(monitor):
    old = HealthProbe(
        channel="telegram", success=True, latency_ms=100,
        timestamp=datetime.utcnow() - timedelta(hours=2),
    )
    new = HealthProbe(
        channel="telegram", success=True, latency_ms=100,
        timestamp=datetime.utcnow(),
    )
    monitor.record_probe(old)
    monitor.record_probe(new)

    since = datetime.utcnow() - timedelta(hours=1)
    history = monitor.get_probe_history("telegram", since=since)
    assert len(history) == 1


def test_probe_history_capped(monitor):
    m = HealthMonitor(probe_history_size=5)
    for i in range(10):
        m.record_probe(HealthProbe(channel="t", success=True, latency_ms=float(i)))
    history = m.get_probe_history("t")
    assert len(history) == 5


# ── Reports ──────────────────────────────────────────────

def test_text_report(monitor, probe_ok, probe_fail):
    for _ in range(5):
        monitor.record_probe(probe_ok)
    monitor.record_probe(probe_fail)

    report = monitor.generate_report("text")
    assert "TELEGRAM" in report
    assert "Health Report" in report
    assert "healthy" in report.lower() or "🟢" in report


def test_json_report(monitor, probe_ok):
    import json
    for _ in range(3):
        monitor.record_probe(probe_ok)

    report = monitor.generate_report("json")
    data = json.loads(report)
    assert "channels" in data
    assert "telegram" in data["channels"]


# ── Reset ────────────────────────────────────────────────

def test_reset_channel(monitor, probe_ok):
    for _ in range(5):
        monitor.record_probe(probe_ok)
    monitor.reset_channel("telegram")
    health = monitor.get_health("telegram")
    assert health.total_probes == 0


def test_reset_all(monitor, probe_ok):
    monitor.record_probe(probe_ok)
    monitor.record_probe(HealthProbe(channel="email", success=True, latency_ms=50))
    monitor.reset_all()
    for h in monitor.get_all_health().values():
        assert h.total_probes == 0


# ── Data Classes ─────────────────────────────────────────

def test_health_probe_to_dict(probe_ok):
    d = probe_ok.to_dict()
    assert d["channel"] == "telegram"
    assert d["success"] is True
    assert d["latency_ms"] == 120.0


def test_channel_health_to_dict():
    h = ChannelHealth(channel="test", state=ChannelState.DEGRADED, total_probes=10)
    d = h.to_dict()
    assert d["state"] == "degraded"
    assert d["total_probes"] == 10


def test_failover_rule_to_dict():
    r = FailoverRule(source_channel="a", target_channel="b", priority=5)
    d = r.to_dict()
    assert d["source"] == "a"
    assert d["target"] == "b"
    assert d["priority"] == 5


def test_sla_target_to_dict():
    s = SLATarget(channel="telegram", uptime_target=99.9)
    d = s.to_dict()
    assert d["uptime_target"] == 99.9


# ── Edge Cases ───────────────────────────────────────────

def test_get_health_unknown(monitor):
    assert monitor.get_health("nonexistent") is None


def test_get_state_unknown(monitor):
    assert monitor.get_state("nonexistent") == ChannelState.HEALTHY


def test_multiple_channels(monitor):
    monitor.record_probe(HealthProbe(channel="telegram", success=True, latency_ms=100))
    monitor.record_probe(HealthProbe(channel="email", success=True, latency_ms=200))
    monitor.record_probe(HealthProbe(channel="slack", success=False, latency_ms=0, error="err"))

    all_health = monitor.get_all_health()
    assert len(all_health) == 3
    assert all_health["telegram"].state == ChannelState.HEALTHY
    assert all_health["slack"].total_failures == 1


def test_unhealthy_to_recovering(monitor):
    monitor.register_channel("telegram")
    health = monitor.get_health("telegram")
    health.state = ChannelState.UNHEALTHY

    probe = HealthProbe(channel="telegram", success=True, latency_ms=100)
    state = monitor.record_probe(probe)
    assert state == ChannelState.RECOVERING


def test_unhealthy_stays_on_failure(monitor):
    monitor.register_channel("telegram")
    health = monitor.get_health("telegram")
    health.state = ChannelState.UNHEALTHY

    probe = HealthProbe(channel="telegram", success=False, latency_ms=0, error="err")
    state = monitor.record_probe(probe)
    assert state == ChannelState.UNHEALTHY
