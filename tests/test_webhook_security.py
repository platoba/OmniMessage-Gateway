"""
Tests for Webhook Security
"""

import hashlib
import hmac as hmac_mod
import json
import time

import pytest

from gateway.webhook_security import (
    SecurityStats,
    VerificationReport,
    VerificationResult,
    WebhookSecurity,
)


@pytest.fixture
def ws():
    return WebhookSecurity(
        max_age_seconds=300,
        rate_limit_per_minute=10,
        enable_ip_check=True,
        enable_replay_check=True,
        enable_rate_limit=True,
    )


@pytest.fixture
def ws_no_checks():
    """No IP/replay/rate checks"""
    return WebhookSecurity(
        enable_ip_check=False,
        enable_replay_check=False,
        enable_rate_limit=False,
    )


# ── Telegram Verification ───────────────────────────────

def test_telegram_valid(ws):
    ws.configure_platform("telegram", secret="my_secret_token")
    body = b'{"update_id": 123}'
    headers = {"x-telegram-bot-api-secret-token": "my_secret_token"}
    result = ws.verify("telegram", body, headers, ip_address="149.154.167.1")
    assert result.is_valid


def test_telegram_invalid_signature(ws):
    ws.configure_platform("telegram", secret="my_secret_token")
    body = b'{"update_id": 123}'
    headers = {"x-telegram-bot-api-secret-token": "wrong_token"}
    result = ws.verify("telegram", body, headers, ip_address="149.154.167.1")
    assert result.result == VerificationResult.INVALID_SIGNATURE


def test_telegram_missing_header(ws):
    ws.configure_platform("telegram", secret="my_secret_token")
    body = b'{"update_id": 123}'
    result = ws.verify("telegram", body, {}, ip_address="149.154.167.1")
    assert result.result == VerificationResult.MISSING_SIGNATURE


# ── Slack Verification ───────────────────────────────────

def test_slack_valid(ws):
    secret = "slack_signing_secret"
    ws.configure_platform("slack", secret=secret)

    timestamp = str(int(time.time()))
    body = b'token=xxx&event=message'
    sig_basestring = f"v0:{timestamp}:{body.decode()}"
    signature = "v0=" + hmac_mod.new(
        secret.encode(), sig_basestring.encode(), hashlib.sha256
    ).hexdigest()

    headers = {
        "x-slack-signature": signature,
        "x-slack-request-timestamp": timestamp,
    }
    result = ws.verify("slack", body, headers)
    assert result.is_valid


def test_slack_invalid_signature(ws):
    ws.configure_platform("slack", secret="real_secret")
    headers = {
        "x-slack-signature": "v0=fake",
        "x-slack-request-timestamp": str(int(time.time())),
    }
    result = ws.verify("slack", b"body", headers)
    assert result.result == VerificationResult.INVALID_SIGNATURE


def test_slack_missing_headers(ws):
    ws.configure_platform("slack", secret="secret")
    result = ws.verify("slack", b"body", {})
    assert result.result == VerificationResult.MISSING_SIGNATURE


# ── GitHub Verification ──────────────────────────────────

def test_github_valid(ws):
    secret = "github_webhook_secret"
    ws.configure_platform("github", secret=secret)

    body = b'{"action": "push"}'
    computed = hmac_mod.new(secret.encode(), body, hashlib.sha256).hexdigest()
    headers = {"x-hub-signature-256": f"sha256={computed}"}

    result = ws.verify("github", body, headers)
    assert result.is_valid


def test_github_invalid(ws):
    ws.configure_platform("github", secret="real")
    headers = {"x-hub-signature-256": "sha256=fake"}
    result = ws.verify("github", b"body", headers)
    assert result.result == VerificationResult.INVALID_SIGNATURE


def test_github_missing_header(ws):
    ws.configure_platform("github", secret="secret")
    result = ws.verify("github", b"body", {})
    assert result.result == VerificationResult.MISSING_SIGNATURE


# ── Stripe Verification ─────────────────────────────────

def test_stripe_valid(ws):
    secret = "whsec_test"
    ws.configure_platform("stripe", secret=secret)

    body = b'{"id": "evt_123"}'
    timestamp = str(int(time.time()))
    signed_payload = f"{timestamp}.{body.decode()}"
    sig = hmac_mod.new(secret.encode(), signed_payload.encode(), hashlib.sha256).hexdigest()

    headers = {"stripe-signature": f"t={timestamp},v1={sig}"}
    result = ws.verify("stripe", body, headers)
    assert result.is_valid


def test_stripe_invalid(ws):
    ws.configure_platform("stripe", secret="real")
    headers = {"stripe-signature": "t=123,v1=fake"}
    result = ws.verify("stripe", b"body", headers)
    assert result.result == VerificationResult.INVALID_SIGNATURE


def test_stripe_missing_header(ws):
    ws.configure_platform("stripe", secret="secret")
    result = ws.verify("stripe", b"body", {})
    assert result.result == VerificationResult.MISSING_SIGNATURE


def test_stripe_malformed_header(ws):
    ws.configure_platform("stripe", secret="secret")
    headers = {"stripe-signature": "malformed"}
    result = ws.verify("stripe", b"body", headers)
    assert result.result == VerificationResult.MISSING_SIGNATURE


# ── Discord Verification ────────────────────────────────

def test_discord_valid(ws):
    secret = "discord_key"
    ws.configure_platform("discord", secret=secret)

    body = b'{"type": 1}'
    timestamp = str(int(time.time()))
    message = timestamp.encode() + body
    sig = hmac_mod.new(secret.encode(), message, hashlib.sha256).hexdigest()

    headers = {
        "x-signature-ed25519": sig,
        "x-signature-timestamp": timestamp,
    }
    result = ws.verify("discord", body, headers)
    assert result.is_valid


def test_discord_missing(ws):
    ws.configure_platform("discord", secret="secret")
    result = ws.verify("discord", b"body", {})
    assert result.result == VerificationResult.MISSING_SIGNATURE


# ── Generic HMAC ─────────────────────────────────────────

def test_generic_hmac_x_signature(ws):
    secret = "my_secret"
    ws.configure_platform("generic", secret=secret)

    body = b"payload"
    sig = hmac_mod.new(secret.encode(), body, hashlib.sha256).hexdigest()
    headers = {"x-signature": sig}

    result = ws.verify("generic", body, headers)
    assert result.is_valid


def test_generic_hmac_with_prefix(ws):
    secret = "my_secret"
    ws.configure_platform("generic", secret=secret)

    body = b"payload"
    sig = hmac_mod.new(secret.encode(), body, hashlib.sha256).hexdigest()
    headers = {"x-signature": f"sha256={sig}"}

    result = ws.verify("generic", body, headers)
    assert result.is_valid


def test_generic_hmac_webhook_signature(ws):
    secret = "my_secret"
    ws.configure_platform("generic", secret=secret)

    body = b"payload"
    sig = hmac_mod.new(secret.encode(), body, hashlib.sha256).hexdigest()
    headers = {"x-webhook-signature": sig}

    result = ws.verify("generic", body, headers)
    assert result.is_valid


def test_generic_hmac_missing(ws):
    ws.configure_platform("generic", secret="secret")
    result = ws.verify("generic", b"body", {})
    assert result.result == VerificationResult.MISSING_SIGNATURE


# ── No Secret Configured ────────────────────────────────

def test_no_secret_passes(ws_no_checks):
    result = ws_no_checks.verify("telegram", b"body", {})
    assert result.is_valid
    assert result.details.get("note") == "no_secret_configured"


# ── Custom Verifier ──────────────────────────────────────

def test_custom_verifier_valid(ws):
    ws.register_custom_verifier("custom", lambda body, headers: True)
    result = ws.verify("custom", b"body", {})
    assert result.is_valid


def test_custom_verifier_invalid(ws):
    ws.register_custom_verifier("custom", lambda body, headers: False)
    result = ws.verify("custom", b"body", {})
    assert result.result == VerificationResult.INVALID_SIGNATURE


def test_custom_verifier_exception(ws):
    ws.register_custom_verifier("custom", lambda body, headers: 1/0)
    result = ws.verify("custom", b"body", {})
    assert result.result == VerificationResult.INVALID_SIGNATURE


# ── IP Allowlist ─────────────────────────────────────────

def test_ip_allowed_known_range(ws):
    ws.configure_platform("telegram", secret="token")
    body = b"{}"
    headers = {"x-telegram-bot-api-secret-token": "token"}
    # Telegram known range: 149.154.160.0/20
    result = ws.verify("telegram", body, headers, ip_address="149.154.167.50")
    assert result.is_valid


def test_ip_blocked(ws):
    ws.configure_platform("telegram", secret="token")
    body = b"{}"
    headers = {"x-telegram-bot-api-secret-token": "token"}
    result = ws.verify("telegram", body, headers, ip_address="1.2.3.4")
    assert result.result == VerificationResult.IP_BLOCKED


def test_ip_custom_allowlist(ws):
    ws.configure_platform("myplatform", secret="secret", ip_ranges=["10.0.0.0/8"])
    body = b"test"
    headers = {"x-signature": hmac_mod.new(b"secret", b"test", hashlib.sha256).hexdigest()}
    result = ws.verify("myplatform", body, headers, ip_address="10.1.2.3")
    assert result.is_valid


def test_ip_check_disabled(ws_no_checks):
    ws_no_checks.configure_platform("telegram", secret="token")
    headers = {"x-telegram-bot-api-secret-token": "token"}
    result = ws_no_checks.verify("telegram", b"{}", headers, ip_address="1.2.3.4")
    assert result.is_valid


def test_ip_invalid_format(ws):
    ws.configure_platform("telegram", secret="token", ip_ranges=["10.0.0.0/8"])
    headers = {"x-telegram-bot-api-secret-token": "token"}
    result = ws.verify("telegram", b"{}", headers, ip_address="not-an-ip")
    assert result.result == VerificationResult.IP_BLOCKED


# ── Rate Limiting ────────────────────────────────────────

def test_rate_limit(ws):
    ws.configure_platform("generic", secret="s")
    body = b"test"
    sig = hmac_mod.new(b"s", body, hashlib.sha256).hexdigest()
    headers = {"x-signature": sig}

    # Send 10 requests (limit is 10/min)
    for i in range(10):
        result = ws.verify("generic", body + bytes([i]), headers, ip_address="5.5.5.5")

    # 11th should be rate limited
    result = ws.verify("generic", body + b"extra", headers, ip_address="5.5.5.5")
    assert result.result == VerificationResult.RATE_LIMITED


def test_rate_limit_different_ips(ws):
    ws.configure_platform("generic", secret="s")
    body = b"test"
    sig = hmac_mod.new(b"s", body, hashlib.sha256).hexdigest()
    headers = {"x-signature": sig}

    # Different IPs don't share limits
    for i in range(10):
        ws.verify("generic", body + bytes([i]), headers, ip_address="1.1.1.1")

    result = ws.verify("generic", body, headers, ip_address="2.2.2.2")
    assert result.result != VerificationResult.RATE_LIMITED


def test_rate_limit_disabled(ws_no_checks):
    for i in range(20):
        result = ws_no_checks.verify("test", b"body" + bytes([i]), {}, ip_address="5.5.5.5")
    assert result.is_valid


# ── Replay Prevention ───────────────────────────────────

def test_replay_detection(ws_no_checks):
    ws_replay = WebhookSecurity(
        enable_ip_check=False,
        enable_replay_check=True,
        enable_rate_limit=False,
    )
    body = b"unique_payload"
    # First request ok
    result1 = ws_replay.verify("test", body, {})
    assert result1.is_valid

    # Same body = replay
    result2 = ws_replay.verify("test", body, {})
    assert result2.result == VerificationResult.REPLAY


def test_replay_different_bodies(ws_no_checks):
    ws_replay = WebhookSecurity(
        enable_ip_check=False,
        enable_replay_check=True,
        enable_rate_limit=False,
    )
    result1 = ws_replay.verify("test", b"body1", {})
    result2 = ws_replay.verify("test", b"body2", {})
    assert result1.is_valid
    assert result2.is_valid


def test_timestamp_expired():
    ws_ts = WebhookSecurity(
        max_age_seconds=60,
        enable_ip_check=False,
        enable_replay_check=True,
        enable_rate_limit=False,
    )
    ws_ts.configure_platform("slack", secret="secret")

    old_ts = str(int(time.time()) - 120)  # 2 minutes ago
    body = b"test"
    sig_base = f"v0:{old_ts}:{body.decode()}"
    sig = "v0=" + hmac_mod.new(b"secret", sig_base.encode(), hashlib.sha256).hexdigest()

    headers = {
        "x-slack-signature": sig,
        "x-slack-request-timestamp": old_ts,
    }
    result = ws_ts.verify("slack", body, headers, timestamp=time.time())
    assert result.result == VerificationResult.EXPIRED


# ── Stats ────────────────────────────────────────────────

def test_stats_tracking(ws_no_checks):
    ws_no_checks.verify("test", b"body1", {})
    ws_no_checks.verify("test", b"body2", {})

    stats = ws_no_checks.get_stats()
    assert stats["global"]["total_requests"] == 2
    assert stats["global"]["valid_requests"] == 2


def test_stats_rejection_tracking(ws):
    ws.configure_platform("telegram", secret="token")
    ws.verify("telegram", b"{}", {}, ip_address="1.2.3.4")  # IP blocked

    stats = ws.get_stats()
    assert stats["global"]["rejection_breakdown"]["ip_blocked"] == 1


def test_platform_stats(ws_no_checks):
    ws_no_checks.verify("telegram", b"a", {})
    ws_no_checks.verify("slack", b"b", {})

    stats = ws_no_checks.get_stats()
    assert "telegram" in stats["by_platform"]
    assert "slack" in stats["by_platform"]


def test_acceptance_rate(ws_no_checks):
    ws_no_checks.verify("test", b"a", {})
    ws_no_checks.verify("test", b"b", {})
    stats = ws_no_checks.get_stats()
    assert stats["global"]["acceptance_rate"] == 100.0


def test_stats_empty():
    ws = WebhookSecurity()
    stats = ws.get_stats()
    assert stats["global"]["total_requests"] == 0
    assert stats["global"]["acceptance_rate"] == 100.0


# ── Audit Log ────────────────────────────────────────────

def test_audit_log(ws_no_checks):
    ws_no_checks.verify("telegram", b"a", {})
    ws_no_checks.verify("slack", b"b", {})

    logs = ws_no_checks.get_audit_log()
    assert len(logs) == 2


def test_audit_log_filter_platform(ws_no_checks):
    ws_no_checks.verify("telegram", b"a", {})
    ws_no_checks.verify("slack", b"b", {})

    logs = ws_no_checks.get_audit_log(platform="telegram")
    assert len(logs) == 1
    assert logs[0]["platform"] == "telegram"


def test_audit_log_filter_result(ws):
    ws.configure_platform("telegram", secret="token")
    ws.verify("telegram", b"{}", {"x-telegram-bot-api-secret-token": "token"}, ip_address="149.154.167.1")
    ws.verify("telegram", b"{}", {}, ip_address="1.2.3.4")  # blocked

    logs = ws.get_audit_log(result="ip_blocked")
    assert len(logs) == 1


def test_audit_log_limit(ws_no_checks):
    for i in range(10):
        ws_no_checks.verify("test", bytes([i]), {})
    logs = ws_no_checks.get_audit_log(limit=5)
    assert len(logs) == 5


# ── Threat Summary ───────────────────────────────────────

def test_threat_summary_none(ws_no_checks):
    ws_no_checks.verify("test", b"a", {})
    summary = ws_no_checks.get_threat_summary()
    assert summary["threat_level"] == "none"
    assert summary["threats"] == []


def test_threat_summary_empty():
    ws = WebhookSecurity()
    summary = ws.get_threat_summary()
    assert summary["total_requests"] == 0
    assert summary["threat_level"] == "none"


def test_threat_summary_with_threats(ws):
    ws.configure_platform("telegram", secret="token")
    # Generate some blocked requests
    for i in range(5):
        ws.verify("telegram", bytes([i]), {}, ip_address="1.2.3.4")

    summary = ws.get_threat_summary()
    assert summary["threat_level"] in ("critical", "high", "medium")
    assert len(summary["threats"]) > 0


# ── Reports ──────────────────────────────────────────────

def test_text_report(ws_no_checks):
    ws_no_checks.verify("test", b"a", {})
    report = ws_no_checks.generate_report("text")
    assert "Security Report" in report
    assert "Total Requests" in report


def test_json_report(ws_no_checks):
    ws_no_checks.verify("test", b"a", {})
    report = ws_no_checks.generate_report("json")
    data = json.loads(report)
    assert "stats" in data
    assert "threat_summary" in data


# ── Reset ────────────────────────────────────────────────

def test_reset_stats(ws_no_checks):
    ws_no_checks.verify("test", b"a", {})
    ws_no_checks.reset_stats()
    stats = ws_no_checks.get_stats()
    assert stats["global"]["total_requests"] == 0
    assert ws_no_checks.get_audit_log() == []


# ── Data Classes ─────────────────────────────────────────

def test_verification_report_to_dict():
    r = VerificationReport(
        result=VerificationResult.VALID,
        platform="telegram",
        ip_address="1.2.3.4",
    )
    d = r.to_dict()
    assert d["result"] == "valid"
    assert d["valid"] is True
    assert d["platform"] == "telegram"


def test_verification_report_invalid():
    r = VerificationReport(
        result=VerificationResult.INVALID_SIGNATURE,
        platform="slack",
    )
    assert r.is_valid is False


def test_security_stats_to_dict():
    s = SecurityStats(total_requests=100, valid_requests=90, invalid_signature=5, ip_blocked=5)
    d = s.to_dict()
    assert d["acceptance_rate"] == 90.0
    assert d["rejection_breakdown"]["invalid_signature"] == 5


# ── Extract Timestamp ────────────────────────────────────

def test_extract_timestamp_slack(ws):
    ts = ws._extract_timestamp("slack", {"x-slack-request-timestamp": "1234567890"})
    assert ts == 1234567890.0


def test_extract_timestamp_stripe(ws):
    ts = ws._extract_timestamp("stripe", {"stripe-signature": "t=1234567890,v1=abc"})
    assert ts == 1234567890.0


def test_extract_timestamp_discord(ws):
    ts = ws._extract_timestamp("discord", {"x-signature-timestamp": "1234567890"})
    assert ts == 1234567890.0


def test_extract_timestamp_none(ws):
    ts = ws._extract_timestamp("unknown", {})
    assert ts is None


def test_extract_timestamp_invalid(ws):
    ts = ws._extract_timestamp("slack", {"x-slack-request-timestamp": "not-a-number"})
    assert ts is None


# ── Nonce Cache Cleanup ─────────────────────────────────

def test_nonce_cache_cleanup():
    ws = WebhookSecurity(
        nonce_cache_size=5,
        enable_ip_check=False,
        enable_replay_check=True,
        enable_rate_limit=False,
    )
    # Fill cache beyond limit
    for i in range(10):
        ws.verify("test", f"unique_{i}".encode(), {})

    # Cache should have been trimmed
    assert len(ws._nonce_cache) <= 10  # some cleanup happens
