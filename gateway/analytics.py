"""
Analytics Engine - 消息分析引擎
成功率/延迟/渠道性能/趋势分析
"""

import json
import time
import threading
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple


class AnalyticsCollector:
    """
    实时分析收集器
    - 投递成功率 (总体 + 按渠道)
    - 平均延迟 (从创建到发送)
    - 渠道可用性
    - 时间序列趋势
    - 错误分类统计
    """

    def __init__(self, window_size: int = 3600):
        self._lock = threading.Lock()
        self._window_size = window_size  # 滑动窗口 (秒)

        # 计数器
        self._total_sent = 0
        self._total_failed = 0
        self._total_retried = 0

        # 按渠道统计
        self._channel_sent: Dict[str, int] = defaultdict(int)
        self._channel_failed: Dict[str, int] = defaultdict(int)

        # 延迟追踪 (毫秒)
        self._latencies: List[Tuple[float, float]] = []  # [(timestamp, latency_ms)]

        # 错误分类
        self._error_counts: Dict[str, int] = defaultdict(int)

        # 时间序列 (按分钟)
        self._minute_sent: Dict[str, int] = defaultdict(int)
        self._minute_failed: Dict[str, int] = defaultdict(int)

        # 目标统计
        self._target_counts: Dict[str, int] = defaultdict(int)

    def record_sent(self, channel: str, latency_ms: float = 0, target: str = None) -> None:
        """记录成功发送"""
        with self._lock:
            self._total_sent += 1
            self._channel_sent[channel] += 1

            now = time.time()
            if latency_ms > 0:
                self._latencies.append((now, latency_ms))

            minute_key = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
            self._minute_sent[minute_key] += 1

            if target:
                self._target_counts[target] += 1

    def record_failed(self, channel: str, error: str = "", target: str = None) -> None:
        """记录发送失败"""
        with self._lock:
            self._total_failed += 1
            self._channel_failed[channel] += 1

            if error:
                # 简化错误分类
                error_type = self._classify_error(error)
                self._error_counts[error_type] += 1

            minute_key = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
            self._minute_failed[minute_key] += 1

    def record_retry(self, channel: str) -> None:
        """记录重试"""
        with self._lock:
            self._total_retried += 1

    @staticmethod
    def _classify_error(error: str) -> str:
        """错误分类"""
        error_lower = error.lower()
        if "timeout" in error_lower:
            return "timeout"
        if "rate" in error_lower or "429" in error_lower or "limit" in error_lower:
            return "rate_limited"
        if "auth" in error_lower or "401" in error_lower or "403" in error_lower:
            return "auth_error"
        if "not found" in error_lower or "404" in error_lower:
            return "not_found"
        if "connection" in error_lower or "connect" in error_lower:
            return "connection_error"
        if "500" in error_lower or "502" in error_lower or "503" in error_lower:
            return "server_error"
        return "other"

    def _prune_latencies(self) -> None:
        """清理过期延迟数据"""
        cutoff = time.time() - self._window_size
        self._latencies = [(t, l) for t, l in self._latencies if t >= cutoff]

    def get_success_rate(self, channel: str = None) -> float:
        """获取成功率"""
        with self._lock:
            if channel:
                sent = self._channel_sent.get(channel, 0)
                failed = self._channel_failed.get(channel, 0)
            else:
                sent = self._total_sent
                failed = self._total_failed
            total = sent + failed
            return round(sent / total * 100, 2) if total > 0 else 0.0

    def get_latency_stats(self) -> Dict[str, float]:
        """获取延迟统计"""
        with self._lock:
            self._prune_latencies()
            if not self._latencies:
                return {"avg_ms": 0, "p50_ms": 0, "p95_ms": 0, "p99_ms": 0, "max_ms": 0}

            latencies = sorted([l for _, l in self._latencies])
            n = len(latencies)
            return {
                "avg_ms": round(sum(latencies) / n, 2),
                "p50_ms": round(latencies[int(n * 0.5)], 2),
                "p95_ms": round(latencies[int(n * 0.95)], 2),
                "p99_ms": round(latencies[min(int(n * 0.99), n - 1)], 2),
                "max_ms": round(latencies[-1], 2),
                "samples": n,
            }

    def get_channel_stats(self) -> Dict[str, Dict[str, Any]]:
        """获取渠道统计"""
        with self._lock:
            channels = set(list(self._channel_sent.keys()) + list(self._channel_failed.keys()))
            result = {}
            for ch in channels:
                sent = self._channel_sent.get(ch, 0)
                failed = self._channel_failed.get(ch, 0)
                total = sent + failed
                result[ch] = {
                    "sent": sent,
                    "failed": failed,
                    "total": total,
                    "success_rate": round(sent / total * 100, 2) if total > 0 else 0.0,
                }
            return result

    def get_error_breakdown(self) -> Dict[str, int]:
        """获取错误分类统计"""
        with self._lock:
            return dict(self._error_counts)

    def get_trend(self, minutes: int = 60) -> Dict[str, Any]:
        """获取趋势数据"""
        with self._lock:
            now = datetime.utcnow()
            start = now - timedelta(minutes=minutes)
            trend_data = []
            for i in range(minutes + 1):
                t = start + timedelta(minutes=i)
                key = t.strftime("%Y-%m-%d %H:%M")
                trend_data.append({
                    "time": key,
                    "sent": self._minute_sent.get(key, 0),
                    "failed": self._minute_failed.get(key, 0),
                })
            return {
                "period_minutes": minutes,
                "data": trend_data,
            }

    def get_top_targets(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取发送量最高的目标"""
        with self._lock:
            sorted_targets = sorted(
                self._target_counts.items(),
                key=lambda x: x[1],
                reverse=True,
            )[:limit]
            return [{"target": t, "count": c} for t, c in sorted_targets]

    @property
    def summary(self) -> Dict[str, Any]:
        """完整摘要"""
        return {
            "total_sent": self._total_sent,
            "total_failed": self._total_failed,
            "total_retried": self._total_retried,
            "success_rate": self.get_success_rate(),
            "latency": self.get_latency_stats(),
            "by_channel": self.get_channel_stats(),
            "errors": self.get_error_breakdown(),
            "top_targets": self.get_top_targets(5),
        }

    def reset(self) -> None:
        """重置所有统计"""
        with self._lock:
            self._total_sent = 0
            self._total_failed = 0
            self._total_retried = 0
            self._channel_sent.clear()
            self._channel_failed.clear()
            self._latencies.clear()
            self._error_counts.clear()
            self._minute_sent.clear()
            self._minute_failed.clear()
            self._target_counts.clear()


class AnalyticsExporter:
    """分析数据导出器"""

    @staticmethod
    def to_json(collector: AnalyticsCollector, indent: int = 2) -> str:
        return json.dumps(collector.summary, indent=indent, ensure_ascii=False)

    @staticmethod
    def to_csv(collector: AnalyticsCollector) -> str:
        """导出渠道统计为 CSV"""
        lines = ["channel,sent,failed,total,success_rate"]
        for ch, stats in collector.get_channel_stats().items():
            lines.append(f"{ch},{stats['sent']},{stats['failed']},{stats['total']},{stats['success_rate']}")
        return "\n".join(lines)

    @staticmethod
    def to_report(collector: AnalyticsCollector) -> str:
        """生成文本报告"""
        s = collector.summary
        lines = [
            "═══════════════════════════════════",
            "  OmniMessage Analytics Report",
            "═══════════════════════════════════",
            f"  Total Sent:    {s['total_sent']}",
            f"  Total Failed:  {s['total_failed']}",
            f"  Total Retried: {s['total_retried']}",
            f"  Success Rate:  {s['success_rate']}%",
            "",
            "── Latency ──────────────────────",
        ]
        lat = s["latency"]
        if lat["avg_ms"] > 0:
            lines.extend([
                f"  Average:  {lat['avg_ms']}ms",
                f"  P50:      {lat['p50_ms']}ms",
                f"  P95:      {lat['p95_ms']}ms",
                f"  P99:      {lat['p99_ms']}ms",
            ])
        else:
            lines.append("  No latency data")

        lines.append("")
        lines.append("── Channels ─────────────────────")
        for ch, cs in s["by_channel"].items():
            lines.append(f"  {ch}: {cs['sent']}/{cs['total']} ({cs['success_rate']}%)")

        if s["errors"]:
            lines.append("")
            lines.append("── Errors ───────────────────────")
            for err, cnt in s["errors"].items():
                lines.append(f"  {err}: {cnt}")

        lines.append("═══════════════════════════════════")
        return "\n".join(lines)
