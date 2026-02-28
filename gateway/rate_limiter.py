"""
Rate Limiter - 令牌桶限流 (per-channel)
防止超过各平台 API 速率限制
"""

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class BucketConfig:
    """令牌桶配置"""
    capacity: float = 30.0       # 桶容量
    refill_rate: float = 1.0     # 每秒填充令牌数
    burst: float = 10.0          # 突发容量 (额外)
    cooldown_ms: int = 100       # 最小间隔 (毫秒)


# 各渠道默认限流配置
DEFAULT_LIMITS: Dict[str, BucketConfig] = {
    "telegram": BucketConfig(capacity=30, refill_rate=1.0, burst=5, cooldown_ms=35),
    "whatsapp": BucketConfig(capacity=80, refill_rate=2.0, burst=10, cooldown_ms=50),
    "discord": BucketConfig(capacity=5, refill_rate=0.2, burst=2, cooldown_ms=500),
    "slack": BucketConfig(capacity=1, refill_rate=1.0, burst=1, cooldown_ms=1000),
    "email": BucketConfig(capacity=10, refill_rate=0.5, burst=3, cooldown_ms=200),
    "webhook": BucketConfig(capacity=100, refill_rate=10.0, burst=20, cooldown_ms=10),
}


class TokenBucket:
    """
    令牌桶 - 线程安全
    支持: 消费/等待/预检/统计
    """

    def __init__(self, config: Optional[BucketConfig] = None):
        self.config = config or BucketConfig()
        self._tokens: float = self.config.capacity
        self._last_refill: float = time.monotonic()
        self._last_consume: float = 0.0
        self._lock = threading.Lock()
        self._total_consumed: int = 0
        self._total_rejected: int = 0
        self._total_waited_ms: float = 0.0

    def _refill(self) -> None:
        """填充令牌"""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(
            self.config.capacity + self.config.burst,
            self._tokens + elapsed * self.config.refill_rate,
        )
        self._last_refill = now

    def try_consume(self, tokens: float = 1.0) -> bool:
        """尝试消费令牌 (非阻塞)"""
        with self._lock:
            self._refill()

            # Cooldown check
            now = time.monotonic()
            if self._last_consume > 0:
                elapsed_ms = (now - self._last_consume) * 1000
                if elapsed_ms < self.config.cooldown_ms:
                    self._total_rejected += 1
                    return False

            if self._tokens >= tokens:
                self._tokens -= tokens
                self._last_consume = now
                self._total_consumed += 1
                return True

            self._total_rejected += 1
            return False

    def consume(self, tokens: float = 1.0, timeout: float = 30.0) -> bool:
        """消费令牌 (阻塞等待)"""
        deadline = time.monotonic() + timeout
        wait_start = time.monotonic()

        while time.monotonic() < deadline:
            if self.try_consume(tokens):
                waited = (time.monotonic() - wait_start) * 1000
                with self._lock:
                    self._total_waited_ms += waited
                return True
            time.sleep(0.05)

        return False

    def wait_time(self, tokens: float = 1.0) -> float:
        """预估等待时间 (秒)"""
        with self._lock:
            self._refill()
            if self._tokens >= tokens:
                return 0.0
            deficit = tokens - self._tokens
            return deficit / self.config.refill_rate if self.config.refill_rate > 0 else float("inf")

    @property
    def available(self) -> float:
        """当前可用令牌"""
        with self._lock:
            self._refill()
            return self._tokens

    @property
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            self._refill()
            return {
                "available_tokens": round(self._tokens, 2),
                "capacity": self.config.capacity,
                "refill_rate": self.config.refill_rate,
                "total_consumed": self._total_consumed,
                "total_rejected": self._total_rejected,
                "total_waited_ms": round(self._total_waited_ms, 2),
                "rejection_rate": round(
                    self._total_rejected / max(1, self._total_consumed + self._total_rejected) * 100, 2
                ),
            }


class RateLimiter:
    """
    多渠道速率限制器
    - 每个渠道独立限流
    - 支持全局限流
    - 支持自定义目标粒度 (如 per-chat_id)
    """

    def __init__(self, custom_limits: Dict[str, BucketConfig] = None):
        self._buckets: Dict[str, TokenBucket] = {}
        self._limits = {**DEFAULT_LIMITS, **(custom_limits or {})}
        self._global_bucket = TokenBucket(BucketConfig(capacity=200, refill_rate=20.0, burst=50, cooldown_ms=0))
        self._lock = threading.Lock()

    def _get_bucket(self, key: str) -> TokenBucket:
        """获取或创建令牌桶"""
        if key not in self._buckets:
            with self._lock:
                if key not in self._buckets:
                    # 从限流配置中查找匹配
                    channel = key.split(":")[0] if ":" in key else key
                    config = self._limits.get(channel, BucketConfig())
                    self._buckets[key] = TokenBucket(config)
        return self._buckets[key]

    def check(self, channel: str, target: str = None) -> bool:
        """
        检查是否允许发送
        二级限流: 渠道级 + 目标级 (可选)
        """
        # 全局限流
        if not self._global_bucket.try_consume():
            return False

        # 渠道级限流
        channel_bucket = self._get_bucket(channel)
        if not channel_bucket.try_consume():
            return False

        # 目标级限流 (可选)
        if target:
            target_key = f"{channel}:{target}"
            target_bucket = self._get_bucket(target_key)
            if not target_bucket.try_consume():
                return False

        return True

    def wait(self, channel: str, target: str = None, timeout: float = 30.0) -> bool:
        """等待直到允许发送"""
        if not self._global_bucket.consume(timeout=timeout):
            return False
        channel_bucket = self._get_bucket(channel)
        if not channel_bucket.consume(timeout=timeout):
            return False
        if target:
            target_key = f"{channel}:{target}"
            target_bucket = self._get_bucket(target_key)
            if not target_bucket.consume(timeout=timeout):
                return False
        return True

    def estimated_wait(self, channel: str) -> float:
        """预估等待时间"""
        channel_bucket = self._get_bucket(channel)
        return max(
            self._global_bucket.wait_time(),
            channel_bucket.wait_time(),
        )

    @property
    def stats(self) -> Dict[str, Any]:
        result = {
            "global": self._global_bucket.stats,
            "channels": {},
        }
        for key, bucket in self._buckets.items():
            if ":" not in key:  # 只显示渠道级
                result["channels"][key] = bucket.stats
        return result

    def reset(self, channel: str = None) -> None:
        """重置限流器"""
        if channel:
            keys_to_remove = [k for k in self._buckets if k == channel or k.startswith(f"{channel}:")]
            for k in keys_to_remove:
                del self._buckets[k]
        else:
            self._buckets.clear()
