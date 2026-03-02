"""
Webhook Security - 入站Webhook验证 + 签名校验 + IP白名单 + 重放防御
"""

import hashlib
import hmac
import ipaddress
import json
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("omni.webhook_security")


class VerificationResult(str, Enum):
    """验证结果"""
    VALID = "valid"
    INVALID_SIGNATURE = "invalid_signature"
    MISSING_SIGNATURE = "missing_signature"
    EXPIRED = "expired"
    REPLAY = "replay"
    IP_BLOCKED = "ip_blocked"
    RATE_LIMITED = "rate_limited"
    UNKNOWN_PLATFORM = "unknown_platform"


@dataclass
class VerificationReport:
    """验证报告"""
    result: VerificationResult
    platform: str
    ip_address: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        return self.result == VerificationResult.VALID

    def to_dict(self) -> Dict[str, Any]:
        return {
            "result": self.result.value,
            "valid": self.is_valid,
            "platform": self.platform,
            "ip_address": self.ip_address,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details,
        }


@dataclass
class SecurityStats:
    """安全统计"""
    total_requests: int = 0
    valid_requests: int = 0
    invalid_signature: int = 0
    missing_signature: int = 0
    expired: int = 0
    replay_attacks: int = 0
    ip_blocked: int = 0
    rate_limited: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_requests": self.total_requests,
            "valid_requests": self.valid_requests,
            "rejection_breakdown": {
                "invalid_signature": self.invalid_signature,
                "missing_signature": self.missing_signature,
                "expired": self.expired,
                "replay_attacks": self.replay_attacks,
                "ip_blocked": self.ip_blocked,
                "rate_limited": self.rate_limited,
            },
            "acceptance_rate": round(
                self.valid_requests / self.total_requests * 100, 2
            ) if self.total_requests > 0 else 100.0,
        }


class WebhookSecurity:
    """
    入站Webhook安全验证系统

    Features:
    - 平台签名验证: Telegram/Slack/Discord/Stripe/GitHub/Generic HMAC
    - IP白名单: 按平台配置可信IP范围
    - 重放防御: 基于时间戳+nonce的重放攻击检测
    - 请求速率限制: 按IP/平台的请求频率限制
    - 审计日志: 全部请求的验证记录
    - 安全报告: 威胁分析+统计
    """

    # 平台已知IP范围
    KNOWN_IP_RANGES: Dict[str, List[str]] = {
        "telegram": [
            "149.154.160.0/20",
            "91.108.4.0/22",
        ],
        "slack": [
            "54.209.0.0/16",
        ],
        "github": [
            "192.30.252.0/22",
            "185.199.108.0/22",
            "140.82.112.0/20",
        ],
        "stripe": [
            "54.187.174.169/32",
            "54.187.205.235/32",
            "54.187.216.72/32",
        ],
    }

    def __init__(
        self,
        max_age_seconds: float = 300.0,
        nonce_cache_size: int = 10000,
        rate_limit_per_minute: int = 120,
        enable_ip_check: bool = True,
        enable_replay_check: bool = True,
        enable_rate_limit: bool = True,
    ):
        self.max_age_seconds = max_age_seconds
        self.nonce_cache_size = nonce_cache_size
        self.rate_limit_per_minute = rate_limit_per_minute
        self.enable_ip_check = enable_ip_check
        self.enable_replay_check = enable_replay_check
        self.enable_rate_limit = enable_rate_limit

        self._secrets: Dict[str, str] = {}
        self._ip_allowlists: Dict[str, List[str]] = {}
        self._nonce_cache: Set[str] = set()
        self._nonce_timestamps: Dict[str, float] = {}
        self._rate_counters: Dict[str, List[float]] = defaultdict(list)
        self._stats: SecurityStats = SecurityStats()
        self._platform_stats: Dict[str, SecurityStats] = defaultdict(SecurityStats)
        self._audit_log: List[Dict[str, Any]] = []
        self._custom_verifiers: Dict[str, Callable] = {}
        self._lock = threading.Lock()

    def configure_platform(
        self,
        platform: str,
        secret: str,
        ip_ranges: List[str] = None,
    ) -> None:
        """配置平台验证密钥"""
        self._secrets[platform] = secret
        if ip_ranges is not None:
            self._ip_allowlists[platform] = ip_ranges

    def register_custom_verifier(
        self,
        platform: str,
        verifier: Callable,
    ) -> None:
        """注册自定义验证器"""
        self._custom_verifiers[platform] = verifier

    def verify(
        self,
        platform: str,
        body: bytes,
        headers: Dict[str, str],
        ip_address: str = None,
        timestamp: float = None,
    ) -> VerificationReport:
        """
        验证入站Webhook请求

        Args:
            platform: 平台标识 (telegram/slack/discord/stripe/github/generic)
            body: 原始请求体
            headers: 请求头
            ip_address: 来源IP
            timestamp: 请求时间戳 (None=当前时间)
        """
        with self._lock:
            self._stats.total_requests += 1
            self._platform_stats[platform].total_requests += 1

        now = timestamp or time.time()

        # 1. IP白名单检查
        if self.enable_ip_check and ip_address:
            ip_result = self._check_ip(platform, ip_address)
            if ip_result is not None:
                self._record_rejection(ip_result, platform, ip_address)
                return VerificationReport(
                    result=ip_result,
                    platform=platform,
                    ip_address=ip_address,
                    details={"check": "ip_allowlist"},
                )

        # 2. 速率限制
        if self.enable_rate_limit and ip_address:
            if self._is_rate_limited(ip_address, now):
                self._record_rejection(VerificationResult.RATE_LIMITED, platform, ip_address)
                return VerificationReport(
                    result=VerificationResult.RATE_LIMITED,
                    platform=platform,
                    ip_address=ip_address,
                    details={"limit": self.rate_limit_per_minute},
                )

        # 3. 签名验证
        sig_result = self._verify_signature(platform, body, headers)
        if not sig_result.is_valid:
            self._record_rejection(sig_result.result, platform, ip_address)
            return sig_result

        # 4. 重放防御
        if self.enable_replay_check:
            replay_result = self._check_replay(platform, body, headers, now)
            if replay_result is not None:
                self._record_rejection(replay_result, platform, ip_address)
                return VerificationReport(
                    result=replay_result,
                    platform=platform,
                    ip_address=ip_address,
                    details={"check": "replay_prevention"},
                )

        # 通过全部检查
        with self._lock:
            self._stats.valid_requests += 1
            self._platform_stats[platform].valid_requests += 1

        report = VerificationReport(
            result=VerificationResult.VALID,
            platform=platform,
            ip_address=ip_address,
        )
        self._audit(report)
        return report

    def _check_ip(self, platform: str, ip_address: str) -> Optional[VerificationResult]:
        """IP白名单检查"""
        # 检查自定义白名单
        allowlist = self._ip_allowlists.get(platform)
        if not allowlist:
            # 检查已知IP范围
            allowlist = self.KNOWN_IP_RANGES.get(platform)
        if not allowlist:
            return None  # 无白名单配置,跳过

        try:
            ip = ipaddress.ip_address(ip_address)
            for cidr in allowlist:
                try:
                    network = ipaddress.ip_network(cidr, strict=False)
                    if ip in network:
                        return None  # IP在白名单中
                except ValueError:
                    continue
        except ValueError:
            return VerificationResult.IP_BLOCKED

        return VerificationResult.IP_BLOCKED

    def _is_rate_limited(self, ip_address: str, now: float) -> bool:
        """速率限制检查"""
        with self._lock:
            key = f"rate:{ip_address}"
            timestamps = self._rate_counters[key]

            # 清理60秒前的记录
            cutoff = now - 60.0
            self._rate_counters[key] = [t for t in timestamps if t > cutoff]
            timestamps = self._rate_counters[key]

            if len(timestamps) >= self.rate_limit_per_minute:
                return True

            timestamps.append(now)
            return False

    def _verify_signature(
        self,
        platform: str,
        body: bytes,
        headers: Dict[str, str],
    ) -> VerificationReport:
        """平台签名验证"""
        # 自定义验证器优先
        if platform in self._custom_verifiers:
            try:
                is_valid = self._custom_verifiers[platform](body, headers)
                result = VerificationResult.VALID if is_valid else VerificationResult.INVALID_SIGNATURE
                return VerificationReport(result=result, platform=platform)
            except Exception as e:
                return VerificationReport(
                    result=VerificationResult.INVALID_SIGNATURE,
                    platform=platform,
                    details={"error": str(e)},
                )

        secret = self._secrets.get(platform)
        if not secret:
            # 无密钥配置, 跳过签名验证
            return VerificationReport(
                result=VerificationResult.VALID,
                platform=platform,
                details={"note": "no_secret_configured"},
            )

        # 按平台调用对应验证器
        verifier_map = {
            "telegram": self._verify_telegram,
            "slack": self._verify_slack,
            "discord": self._verify_discord,
            "stripe": self._verify_stripe,
            "github": self._verify_github,
            "generic": self._verify_generic_hmac,
        }

        verifier = verifier_map.get(platform, self._verify_generic_hmac)
        return verifier(body, headers, secret)

    def _verify_telegram(
        self, body: bytes, headers: Dict[str, str], secret: str
    ) -> VerificationReport:
        """Telegram Bot API Webhook验证 (secret_token header)"""
        token = headers.get("x-telegram-bot-api-secret-token", "")
        if not token:
            return VerificationReport(
                result=VerificationResult.MISSING_SIGNATURE,
                platform="telegram",
                details={"header": "x-telegram-bot-api-secret-token"},
            )

        if hmac.compare_digest(token, secret):
            return VerificationReport(result=VerificationResult.VALID, platform="telegram")

        return VerificationReport(
            result=VerificationResult.INVALID_SIGNATURE,
            platform="telegram",
        )

    def _verify_slack(
        self, body: bytes, headers: Dict[str, str], secret: str
    ) -> VerificationReport:
        """Slack Request Verification (v0 signature)"""
        signature = headers.get("x-slack-signature", "")
        timestamp = headers.get("x-slack-request-timestamp", "")

        if not signature or not timestamp:
            return VerificationReport(
                result=VerificationResult.MISSING_SIGNATURE,
                platform="slack",
                details={"headers": ["x-slack-signature", "x-slack-request-timestamp"]},
            )

        # 构造签名基串
        sig_basestring = f"v0:{timestamp}:{body.decode('utf-8', errors='replace')}"
        computed = "v0=" + hmac.new(
            secret.encode("utf-8"),
            sig_basestring.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if hmac.compare_digest(computed, signature):
            return VerificationReport(result=VerificationResult.VALID, platform="slack")

        return VerificationReport(
            result=VerificationResult.INVALID_SIGNATURE,
            platform="slack",
        )

    def _verify_discord(
        self, body: bytes, headers: Dict[str, str], secret: str
    ) -> VerificationReport:
        """Discord Interaction Verification (Ed25519-like via HMAC fallback)"""
        signature = headers.get("x-signature-ed25519", "")
        timestamp = headers.get("x-signature-timestamp", "")

        if not signature or not timestamp:
            return VerificationReport(
                result=VerificationResult.MISSING_SIGNATURE,
                platform="discord",
                details={"headers": ["x-signature-ed25519", "x-signature-timestamp"]},
            )

        # HMAC-SHA256 fallback (真实Discord用Ed25519, 这里提供HMAC兼容)
        message = timestamp.encode("utf-8") + body
        computed = hmac.new(
            secret.encode("utf-8"),
            message,
            hashlib.sha256,
        ).hexdigest()

        if hmac.compare_digest(computed, signature):
            return VerificationReport(result=VerificationResult.VALID, platform="discord")

        return VerificationReport(
            result=VerificationResult.INVALID_SIGNATURE,
            platform="discord",
        )

    def _verify_stripe(
        self, body: bytes, headers: Dict[str, str], secret: str
    ) -> VerificationReport:
        """Stripe Webhook Signature Verification"""
        sig_header = headers.get("stripe-signature", "")
        if not sig_header:
            return VerificationReport(
                result=VerificationResult.MISSING_SIGNATURE,
                platform="stripe",
                details={"header": "stripe-signature"},
            )

        # 解析 t=xxx,v1=yyy
        elements = {}
        for part in sig_header.split(","):
            if "=" in part:
                key, value = part.split("=", 1)
                elements[key.strip()] = value.strip()

        timestamp = elements.get("t", "")
        sig_v1 = elements.get("v1", "")

        if not timestamp or not sig_v1:
            return VerificationReport(
                result=VerificationResult.MISSING_SIGNATURE,
                platform="stripe",
                details={"parsed": elements},
            )

        # 计算期望签名
        signed_payload = f"{timestamp}.{body.decode('utf-8', errors='replace')}"
        expected = hmac.new(
            secret.encode("utf-8"),
            signed_payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if hmac.compare_digest(expected, sig_v1):
            return VerificationReport(result=VerificationResult.VALID, platform="stripe")

        return VerificationReport(
            result=VerificationResult.INVALID_SIGNATURE,
            platform="stripe",
        )

    def _verify_github(
        self, body: bytes, headers: Dict[str, str], secret: str
    ) -> VerificationReport:
        """GitHub Webhook HMAC-SHA256 Verification"""
        signature = headers.get("x-hub-signature-256", "")
        if not signature:
            return VerificationReport(
                result=VerificationResult.MISSING_SIGNATURE,
                platform="github",
                details={"header": "x-hub-signature-256"},
            )

        # sha256=xxxxx
        if signature.startswith("sha256="):
            signature = signature[7:]

        computed = hmac.new(
            secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()

        if hmac.compare_digest(computed, signature):
            return VerificationReport(result=VerificationResult.VALID, platform="github")

        return VerificationReport(
            result=VerificationResult.INVALID_SIGNATURE,
            platform="github",
        )

    def _verify_generic_hmac(
        self, body: bytes, headers: Dict[str, str], secret: str
    ) -> VerificationReport:
        """Generic HMAC-SHA256 verification"""
        # 尝试常见签名头
        sig_headers = [
            "x-signature",
            "x-webhook-signature",
            "x-hmac-signature",
            "authorization",
        ]

        signature = None
        used_header = None
        for h in sig_headers:
            if h in headers:
                signature = headers[h]
                used_header = h
                break

        if not signature:
            return VerificationReport(
                result=VerificationResult.MISSING_SIGNATURE,
                platform="generic",
                details={"tried_headers": sig_headers},
            )

        # 移除常见前缀
        for prefix in ("sha256=", "hmac-sha256=", "Bearer "):
            if signature.startswith(prefix):
                signature = signature[len(prefix):]
                break

        computed = hmac.new(
            secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()

        if hmac.compare_digest(computed, signature):
            return VerificationReport(
                result=VerificationResult.VALID,
                platform="generic",
                details={"header": used_header},
            )

        return VerificationReport(
            result=VerificationResult.INVALID_SIGNATURE,
            platform="generic",
            details={"header": used_header},
        )

    def _check_replay(
        self,
        platform: str,
        body: bytes,
        headers: Dict[str, str],
        now: float,
    ) -> Optional[VerificationResult]:
        """重放攻击检测"""
        # 提取时间戳
        ts = self._extract_timestamp(platform, headers)
        if ts is not None:
            # 检查时间戳是否过期
            age = abs(now - ts)
            if age > self.max_age_seconds:
                return VerificationResult.EXPIRED

        # Nonce检查 (基于body hash)
        nonce = hashlib.sha256(body).hexdigest()[:32]
        with self._lock:
            if nonce in self._nonce_cache:
                return VerificationResult.REPLAY

            self._nonce_cache.add(nonce)
            self._nonce_timestamps[nonce] = now

            # 清理过期nonce
            if len(self._nonce_cache) > self.nonce_cache_size:
                cutoff = now - self.max_age_seconds * 2
                expired = [k for k, v in self._nonce_timestamps.items() if v < cutoff]
                for k in expired:
                    self._nonce_cache.discard(k)
                    self._nonce_timestamps.pop(k, None)

        return None

    def _extract_timestamp(self, platform: str, headers: Dict[str, str]) -> Optional[float]:
        """从请求头提取时间戳"""
        ts_headers = {
            "slack": "x-slack-request-timestamp",
            "stripe": None,  # 在签名头中
            "discord": "x-signature-timestamp",
        }

        header_name = ts_headers.get(platform)
        if header_name and header_name in headers:
            try:
                return float(headers[header_name])
            except (ValueError, TypeError):
                return None

        # Stripe: 从 stripe-signature 的 t= 中提取
        if platform == "stripe":
            sig = headers.get("stripe-signature", "")
            for part in sig.split(","):
                if part.strip().startswith("t="):
                    try:
                        return float(part.strip()[2:])
                    except (ValueError, TypeError):
                        pass

        return None

    def _record_rejection(
        self,
        result: VerificationResult,
        platform: str,
        ip_address: str = None,
    ) -> None:
        """记录拒绝"""
        with self._lock:
            stat_map = {
                VerificationResult.INVALID_SIGNATURE: "invalid_signature",
                VerificationResult.MISSING_SIGNATURE: "missing_signature",
                VerificationResult.EXPIRED: "expired",
                VerificationResult.REPLAY: "replay_attacks",
                VerificationResult.IP_BLOCKED: "ip_blocked",
                VerificationResult.RATE_LIMITED: "rate_limited",
            }
            attr = stat_map.get(result)
            if attr:
                setattr(self._stats, attr, getattr(self._stats, attr) + 1)
                p_stats = self._platform_stats[platform]
                setattr(p_stats, attr, getattr(p_stats, attr) + 1)

        report = VerificationReport(
            result=result,
            platform=platform,
            ip_address=ip_address,
        )
        self._audit(report)

    def _audit(self, report: VerificationReport) -> None:
        """记录审计日志"""
        entry = report.to_dict()
        with self._lock:
            self._audit_log.append(entry)
            # 保留最近10000条
            if len(self._audit_log) > 10000:
                self._audit_log = self._audit_log[-10000:]

    # ── Public API ───────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """获取安全统计"""
        return {
            "global": self._stats.to_dict(),
            "by_platform": {
                p: s.to_dict() for p, s in self._platform_stats.items()
            },
        }

    def get_audit_log(
        self,
        limit: int = 100,
        platform: str = None,
        result: str = None,
    ) -> List[Dict[str, Any]]:
        """获取审计日志"""
        logs = list(self._audit_log)
        if platform:
            logs = [l for l in logs if l.get("platform") == platform]
        if result:
            logs = [l for l in logs if l.get("result") == result]
        return logs[-limit:]

    def get_threat_summary(self) -> Dict[str, Any]:
        """威胁概要"""
        total = self._stats.total_requests
        if total == 0:
            return {"total_requests": 0, "threat_level": "none", "threats": []}

        threats = []
        if self._stats.replay_attacks > 0:
            threats.append({
                "type": "replay_attack",
                "count": self._stats.replay_attacks,
                "severity": "high",
            })
        if self._stats.invalid_signature > 0:
            threats.append({
                "type": "invalid_signature",
                "count": self._stats.invalid_signature,
                "severity": "high",
            })
        if self._stats.ip_blocked > 0:
            threats.append({
                "type": "ip_blocked",
                "count": self._stats.ip_blocked,
                "severity": "medium",
            })
        if self._stats.rate_limited > 0:
            threats.append({
                "type": "rate_limited",
                "count": self._stats.rate_limited,
                "severity": "low",
            })

        rejection_rate = (total - self._stats.valid_requests) / total * 100
        if rejection_rate > 50:
            level = "critical"
        elif rejection_rate > 20:
            level = "high"
        elif rejection_rate > 5:
            level = "medium"
        elif threats:
            level = "low"
        else:
            level = "none"

        return {
            "total_requests": total,
            "rejection_rate": round(rejection_rate, 2),
            "threat_level": level,
            "threats": sorted(threats, key=lambda t: {"high": 3, "medium": 2, "low": 1}.get(t["severity"], 0), reverse=True),
        }

    def generate_report(self, format: str = "text") -> str:
        """生成安全报告"""
        if format == "json":
            import json as json_mod
            data = {
                "generated_at": datetime.utcnow().isoformat(),
                "stats": self.get_stats(),
                "threat_summary": self.get_threat_summary(),
                "configured_platforms": list(self._secrets.keys()),
            }
            return json_mod.dumps(data, indent=2, ensure_ascii=False)

        return self._report_text()

    def _report_text(self) -> str:
        """文本安全报告"""
        stats = self._stats
        threat = self.get_threat_summary()

        level_icons = {
            "none": "🟢",
            "low": "🟡",
            "medium": "🟠",
            "high": "🔴",
            "critical": "⛔",
        }

        lines = [
            "═══════════════════════════════════════",
            "  Webhook Security Report",
            "═══════════════════════════════════════",
            f"  Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC",
            "",
            f"  {level_icons.get(threat['threat_level'], '❓')} Threat Level: {threat['threat_level'].upper()}",
            f"  Total Requests: {stats.total_requests}",
            f"  Accepted: {stats.valid_requests}",
            f"  Rejected: {stats.total_requests - stats.valid_requests}",
            "",
            "  Rejection Breakdown:",
            f"    ❌ Invalid Signature: {stats.invalid_signature}",
            f"    ⚠️  Missing Signature: {stats.missing_signature}",
            f"    ⏰ Expired: {stats.expired}",
            f"    🔄 Replay Attacks: {stats.replay_attacks}",
            f"    🚫 IP Blocked: {stats.ip_blocked}",
            f"    🔒 Rate Limited: {stats.rate_limited}",
            "",
            f"  Configured Platforms: {', '.join(self._secrets.keys()) or 'none'}",
            "═══════════════════════════════════════",
        ]
        return "\n".join(lines)

    def reset_stats(self) -> None:
        """重置统计"""
        with self._lock:
            self._stats = SecurityStats()
            self._platform_stats.clear()
            self._audit_log.clear()
            self._nonce_cache.clear()
            self._nonce_timestamps.clear()
            self._rate_counters.clear()
