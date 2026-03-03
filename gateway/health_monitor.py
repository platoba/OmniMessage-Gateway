"""
Channel Health Monitor - 渠道健康监控 + 自动故障转移 + SLA追踪
"""

import logging
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("omni.health")


class ChannelState(str, Enum):
    """渠道状态 (circuit breaker pattern)"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    CIRCUIT_OPEN = "circuit_open"
    RECOVERING = "recovering"


@dataclass
class HealthProbe:
    """健康探针结果"""
    channel: str
    success: bool
    latency_ms: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    error: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "channel": self.channel,
            "success": self.success,
            "latency_ms": round(self.latency_ms, 2),
            "timestamp": self.timestamp.isoformat(),
            "error": self.error,
            "details": self.details,
        }


@dataclass
class FailoverRule:
    """故障转移规则"""
    source_channel: str
    target_channel: str
    priority: int = 0  # 越大优先
    enabled: bool = True
    conditions: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source_channel,
            "target": self.target_channel,
            "priority": self.priority,
            "enabled": self.enabled,
            "conditions": self.conditions,
        }


@dataclass
class SLATarget:
    """SLA目标"""
    channel: str
    uptime_target: float = 99.9  # percentage
    max_latency_ms: float = 5000.0
    max_error_rate: float = 1.0  # percentage

    def to_dict(self) -> Dict[str, Any]:
        return {
            "channel": self.channel,
            "uptime_target": self.uptime_target,
            "max_latency_ms": self.max_latency_ms,
            "max_error_rate": self.max_error_rate,
        }


@dataclass
class ChannelHealth:
    """渠道健康状态"""
    channel: str
    state: ChannelState = ChannelState.HEALTHY
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    total_probes: int = 0
    total_successes: int = 0
    total_failures: int = 0
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    last_error: Optional[str] = None
    circuit_opened_at: Optional[datetime] = None
    uptime_percent: float = 100.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "channel": self.channel,
            "state": self.state.value,
            "consecutive_failures": self.consecutive_failures,
            "consecutive_successes": self.consecutive_successes,
            "total_probes": self.total_probes,
            "total_successes": self.total_successes,
            "total_failures": self.total_failures,
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "p95_latency_ms": round(self.p95_latency_ms, 2),
            "p99_latency_ms": round(self.p99_latency_ms, 2),
            "last_success": self.last_success.isoformat() if self.last_success else None,
            "last_failure": self.last_failure.isoformat() if self.last_failure else None,
            "last_error": self.last_error,
            "circuit_opened_at": self.circuit_opened_at.isoformat() if self.circuit_opened_at else None,
            "uptime_percent": round(self.uptime_percent, 3),
        }


class HealthMonitor:
    """
    渠道健康监控系统

    Features:
    - 健康探针: 定期探测每个渠道的可用性
    - 断路器: consecutive failures 触发断路, 半开恢复
    - SLA追踪: 可用率、延迟、错误率 vs 目标
    - 自动故障转移: 渠道不可用时路由到备用渠道
    - 健康报告: 全局/单渠道健康报告
    - 告警回调: 状态变更触发回调
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_threshold: int = 3,
        circuit_timeout_seconds: float = 60.0,
        probe_history_size: int = 1000,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_threshold = recovery_threshold
        self.circuit_timeout_seconds = circuit_timeout_seconds
        self.probe_history_size = probe_history_size

        self._health: Dict[str, ChannelHealth] = {}
        self._probe_history: Dict[str, List[HealthProbe]] = defaultdict(list)
        self._failover_rules: List[FailoverRule] = []
        self._sla_targets: Dict[str, SLATarget] = {}
        self._alert_callbacks: List[Callable] = []
        self._probe_functions: Dict[str, Callable] = {}
        self._lock = threading.Lock()

    def register_channel(self, channel: str) -> None:
        """注册渠道到监控"""
        with self._lock:
            if channel not in self._health:
                self._health[channel] = ChannelHealth(channel=channel)

    def register_probe(self, channel: str, probe_fn: Callable) -> None:
        """注册渠道探针函数"""
        self._probe_functions[channel] = probe_fn
        self.register_channel(channel)

    def set_sla_target(self, sla: SLATarget) -> None:
        """设置SLA目标"""
        self._sla_targets[sla.channel] = sla

    def add_failover_rule(self, rule: FailoverRule) -> None:
        """添加故障转移规则"""
        self._failover_rules.append(rule)
        self._failover_rules.sort(key=lambda r: r.priority, reverse=True)

    def add_alert_callback(self, callback: Callable) -> None:
        """添加告警回调 (state_change, channel, old_state, new_state)"""
        self._alert_callbacks.append(callback)

    def record_probe(self, probe: HealthProbe) -> ChannelState:
        """记录探针结果, 返回当前状态"""
        with self._lock:
            channel = probe.channel
            self.register_channel(channel)
            health = self._health[channel]
            old_state = health.state

            # 记录探针历史
            history = self._probe_history[channel]
            history.append(probe)
            if len(history) > self.probe_history_size:
                self._probe_history[channel] = history[-self.probe_history_size:]

            # 更新统计
            health.total_probes += 1

            if probe.success:
                health.total_successes += 1
                health.consecutive_successes += 1
                health.consecutive_failures = 0
                health.last_success = probe.timestamp
            else:
                health.total_failures += 1
                health.consecutive_failures += 1
                health.consecutive_successes = 0
                health.last_failure = probe.timestamp
                health.last_error = probe.error

            # 更新延迟统计
            self._update_latency_stats(channel)

            # 更新可用率
            if health.total_probes > 0:
                health.uptime_percent = (health.total_successes / health.total_probes) * 100

            # 状态机转换
            new_state = self._transition_state(health, probe)
            health.state = new_state

            # 触发告警
            if old_state != new_state:
                self._fire_alerts(channel, old_state, new_state)

            return new_state

    def _transition_state(self, health: ChannelHealth, probe: HealthProbe) -> ChannelState:
        """状态机转换逻辑"""
        current = health.state

        if current == ChannelState.HEALTHY:
            if health.consecutive_failures >= self.failure_threshold:
                health.circuit_opened_at = datetime.utcnow()
                return ChannelState.CIRCUIT_OPEN
            elif health.consecutive_failures >= 2:
                return ChannelState.DEGRADED
            return ChannelState.HEALTHY

        elif current == ChannelState.DEGRADED:
            if health.consecutive_failures >= self.failure_threshold:
                health.circuit_opened_at = datetime.utcnow()
                return ChannelState.CIRCUIT_OPEN
            elif health.consecutive_successes >= self.recovery_threshold:
                return ChannelState.HEALTHY
            elif probe.success:
                return ChannelState.DEGRADED
            return ChannelState.DEGRADED

        elif current == ChannelState.CIRCUIT_OPEN:
            # 断路超时后进入半开状态
            if health.circuit_opened_at:
                elapsed = (datetime.utcnow() - health.circuit_opened_at).total_seconds()
                if elapsed >= self.circuit_timeout_seconds:
                    if probe.success:
                        return ChannelState.RECOVERING
                    return ChannelState.CIRCUIT_OPEN
            return ChannelState.CIRCUIT_OPEN

        elif current == ChannelState.RECOVERING:
            if health.consecutive_successes >= self.recovery_threshold:
                health.circuit_opened_at = None
                return ChannelState.HEALTHY
            elif not probe.success:
                health.circuit_opened_at = datetime.utcnow()
                return ChannelState.CIRCUIT_OPEN
            return ChannelState.RECOVERING

        elif current == ChannelState.UNHEALTHY:
            if probe.success:
                return ChannelState.RECOVERING
            return ChannelState.UNHEALTHY

        return current

    def _update_latency_stats(self, channel: str) -> None:
        """更新延迟统计 (avg, P95, P99)"""
        history = self._probe_history[channel]
        latencies = [p.latency_ms for p in history if p.success]
        if not latencies:
            return

        health = self._health[channel]
        health.avg_latency_ms = sum(latencies) / len(latencies)

        sorted_lat = sorted(latencies)
        n = len(sorted_lat)
        health.p95_latency_ms = sorted_lat[int(n * 0.95)] if n >= 20 else sorted_lat[-1]
        health.p99_latency_ms = sorted_lat[int(n * 0.99)] if n >= 100 else sorted_lat[-1]

    def _fire_alerts(self, channel: str, old_state: ChannelState, new_state: ChannelState) -> None:
        """触发告警回调"""
        for callback in self._alert_callbacks:
            try:
                callback(channel, old_state, new_state)
            except Exception as e:
                logger.error(f"Alert callback error: {e}")

    def get_health(self, channel: str) -> Optional[ChannelHealth]:
        """获取渠道健康状态"""
        return self._health.get(channel)

    def get_all_health(self) -> Dict[str, ChannelHealth]:
        """获取所有渠道健康状态"""
        return dict(self._health)

    def get_state(self, channel: str) -> ChannelState:
        """获取渠道当前状态"""
        health = self._health.get(channel)
        return health.state if health else ChannelState.HEALTHY

    def is_available(self, channel: str) -> bool:
        """检查渠道是否可用 (非断路)"""
        state = self.get_state(channel)
        return state in (ChannelState.HEALTHY, ChannelState.DEGRADED, ChannelState.RECOVERING)

    def get_failover(self, channel: str) -> Optional[str]:
        """获取故障转移目标渠道"""
        if self.is_available(channel):
            return None  # 不需要故障转移

        for rule in self._failover_rules:
            if not rule.enabled:
                continue
            if rule.source_channel == channel:
                # 检查目标渠道是否可用
                if self.is_available(rule.target_channel):
                    return rule.target_channel

        return None

    def get_failover_chain(self, channel: str) -> List[str]:
        """获取完整故障转移链"""
        chain = []
        visited = {channel}
        current = channel

        while True:
            target = None
            for rule in self._failover_rules:
                if not rule.enabled:
                    continue
                if rule.source_channel == current and rule.target_channel not in visited:
                    target = rule.target_channel
                    break

            if target is None:
                break

            chain.append(target)
            visited.add(target)
            current = target

        return chain

    def check_sla(self, channel: str) -> Dict[str, Any]:
        """检查SLA达标情况"""
        health = self._health.get(channel)
        sla = self._sla_targets.get(channel)

        if not health or not sla:
            return {
                "channel": channel,
                "sla_defined": sla is not None,
                "health_tracked": health is not None,
                "compliant": True,
                "violations": [],
            }

        violations = []

        # 可用率检查
        if health.uptime_percent < sla.uptime_target:
            violations.append({
                "metric": "uptime",
                "target": sla.uptime_target,
                "actual": round(health.uptime_percent, 3),
                "severity": "critical" if health.uptime_percent < sla.uptime_target - 5 else "warning",
            })

        # 延迟检查
        if health.p95_latency_ms > sla.max_latency_ms:
            violations.append({
                "metric": "latency_p95",
                "target": sla.max_latency_ms,
                "actual": round(health.p95_latency_ms, 2),
                "severity": "warning",
            })

        # 错误率检查
        error_rate = 0.0
        if health.total_probes > 0:
            error_rate = (health.total_failures / health.total_probes) * 100

        if error_rate > sla.max_error_rate:
            violations.append({
                "metric": "error_rate",
                "target": sla.max_error_rate,
                "actual": round(error_rate, 2),
                "severity": "critical" if error_rate > sla.max_error_rate * 2 else "warning",
            })

        return {
            "channel": channel,
            "sla_defined": True,
            "health_tracked": True,
            "compliant": len(violations) == 0,
            "uptime_percent": round(health.uptime_percent, 3),
            "error_rate_percent": round(error_rate, 2),
            "p95_latency_ms": round(health.p95_latency_ms, 2),
            "violations": violations,
            "sla_targets": sla.to_dict(),
        }

    def check_all_sla(self) -> Dict[str, Any]:
        """检查所有渠道SLA"""
        results = {}
        total_compliant = 0
        total_checked = 0

        for channel in self._health:
            result = self.check_sla(channel)
            results[channel] = result
            if result["sla_defined"]:
                total_checked += 1
                if result["compliant"]:
                    total_compliant += 1

        return {
            "channels": results,
            "summary": {
                "total_channels": len(self._health),
                "sla_defined": total_checked,
                "compliant": total_compliant,
                "non_compliant": total_checked - total_compliant,
                "compliance_rate": round(
                    total_compliant / total_checked * 100, 1
                ) if total_checked > 0 else 100.0,
            },
        }

    def get_probe_history(
        self,
        channel: str,
        limit: int = 100,
        since: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """获取探针历史"""
        history = self._probe_history.get(channel, [])
        if since:
            history = [p for p in history if p.timestamp >= since]
        return [p.to_dict() for p in history[-limit:]]

    def generate_report(self, format: str = "text") -> str:
        """生成健康报告"""
        if format == "json":
            return self._report_json()
        return self._report_text()

    def _report_text(self) -> str:
        """文本格式健康报告"""
        lines = [
            "═══════════════════════════════════════",
            "  OmniMessage Gateway Health Report",
            "═══════════════════════════════════════",
            f"  Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC",
            f"  Channels Monitored: {len(self._health)}",
            "",
        ]

        state_icons = {
            ChannelState.HEALTHY: "🟢",
            ChannelState.DEGRADED: "🟡",
            ChannelState.UNHEALTHY: "🔴",
            ChannelState.CIRCUIT_OPEN: "⛔",
            ChannelState.RECOVERING: "🔄",
        }

        for channel, health in sorted(self._health.items()):
            icon = state_icons.get(health.state, "❓")
            lines.append(f"  {icon} {channel.upper()}")
            lines.append(f"     State: {health.state.value}")
            lines.append(f"     Uptime: {health.uptime_percent:.2f}%")
            lines.append(f"     Probes: {health.total_successes}/{health.total_probes}")
            lines.append(f"     Latency: avg={health.avg_latency_ms:.0f}ms p95={health.p95_latency_ms:.0f}ms")
            if health.last_error:
                lines.append(f"     Last Error: {health.last_error}")

            # SLA check
            sla_result = self.check_sla(channel)
            if sla_result["sla_defined"]:
                status = "✅ COMPLIANT" if sla_result["compliant"] else "❌ VIOLATION"
                lines.append(f"     SLA: {status}")
                for v in sla_result.get("violations", []):
                    lines.append(f"       ⚠ {v['metric']}: {v['actual']} (target: {v['target']})")

            # Failover
            failover = self.get_failover(channel)
            if failover:
                lines.append(f"     Failover → {failover}")

            lines.append("")

        # Summary
        healthy = sum(1 for h in self._health.values() if h.state == ChannelState.HEALTHY)
        degraded = sum(1 for h in self._health.values() if h.state == ChannelState.DEGRADED)
        down = sum(1 for h in self._health.values() if h.state in (ChannelState.UNHEALTHY, ChannelState.CIRCUIT_OPEN))

        lines.append("───────────────────────────────────────")
        lines.append(f"  Summary: 🟢 {healthy} healthy  🟡 {degraded} degraded  🔴 {down} down")
        lines.append("═══════════════════════════════════════")

        return "\n".join(lines)

    def _report_json(self) -> str:
        """JSON格式报告"""
        import json
        data = {
            "generated_at": datetime.utcnow().isoformat(),
            "channels": {ch: h.to_dict() for ch, h in self._health.items()},
            "failover_rules": [r.to_dict() for r in self._failover_rules],
            "sla": self.check_all_sla(),
        }
        return json.dumps(data, indent=2, ensure_ascii=False)

    def reset_channel(self, channel: str) -> None:
        """重置渠道健康状态"""
        with self._lock:
            self._health[channel] = ChannelHealth(channel=channel)
            self._probe_history[channel] = []

    def reset_all(self) -> None:
        """重置所有监控数据"""
        with self._lock:
            for channel in list(self._health.keys()):
                self._health[channel] = ChannelHealth(channel=channel)
            self._probe_history.clear()
