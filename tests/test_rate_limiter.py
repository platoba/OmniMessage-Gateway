"""
Tests for Rate Limiter
"""

import time
import threading
import pytest

from gateway.rate_limiter import (
    BucketConfig,
    TokenBucket,
    RateLimiter,
    DEFAULT_LIMITS,
)


class TestTokenBucket:
    def test_initial_capacity(self):
        bucket = TokenBucket(BucketConfig(capacity=10, refill_rate=1.0, cooldown_ms=0))
        assert bucket.available >= 9.9  # 允许微小浮点误差

    def test_consume_reduces_tokens(self):
        bucket = TokenBucket(BucketConfig(capacity=10, refill_rate=0, cooldown_ms=0))
        assert bucket.try_consume(1) is True
        assert bucket.available < 10

    def test_consume_fails_when_empty(self):
        bucket = TokenBucket(BucketConfig(capacity=2, refill_rate=0, cooldown_ms=0))
        assert bucket.try_consume(1) is True
        assert bucket.try_consume(1) is True
        assert bucket.try_consume(1) is False

    def test_refill_over_time(self):
        bucket = TokenBucket(BucketConfig(capacity=5, refill_rate=100.0, cooldown_ms=0))
        # 消耗所有
        for _ in range(5):
            bucket.try_consume(1)
        # 等待一小段时间让令牌恢复
        time.sleep(0.05)
        assert bucket.try_consume(1) is True

    def test_burst_capacity(self):
        bucket = TokenBucket(BucketConfig(capacity=5, refill_rate=0, burst=3, cooldown_ms=0))
        # 初始容量 = 5, burst不额外增加初始量
        count = 0
        for _ in range(10):
            if bucket.try_consume(1):
                count += 1
        assert count == 5

    def test_cooldown(self):
        bucket = TokenBucket(BucketConfig(capacity=100, refill_rate=10, cooldown_ms=200))
        assert bucket.try_consume(1) is True
        # 立即再次消费应被 cooldown 拒绝
        assert bucket.try_consume(1) is False
        time.sleep(0.21)
        assert bucket.try_consume(1) is True

    def test_wait_time(self):
        bucket = TokenBucket(BucketConfig(capacity=1, refill_rate=10.0, cooldown_ms=0))
        bucket.try_consume(1)
        wait = bucket.wait_time()
        assert wait >= 0

    def test_blocking_consume(self):
        bucket = TokenBucket(BucketConfig(capacity=1, refill_rate=100.0, cooldown_ms=0))
        bucket.try_consume(1)
        # 应该在短时间内获得令牌
        assert bucket.consume(1, timeout=1.0) is True

    def test_blocking_consume_timeout(self):
        bucket = TokenBucket(BucketConfig(capacity=1, refill_rate=0.01, cooldown_ms=0))
        bucket.try_consume(1)
        assert bucket.consume(1, timeout=0.1) is False

    def test_stats(self):
        bucket = TokenBucket(BucketConfig(capacity=10, refill_rate=1.0, cooldown_ms=0))
        bucket.try_consume(1)
        bucket.try_consume(1)
        stats = bucket.stats
        assert stats["total_consumed"] == 2
        assert stats["capacity"] == 10
        assert "rejection_rate" in stats

    def test_thread_safety(self):
        bucket = TokenBucket(BucketConfig(capacity=100, refill_rate=0, cooldown_ms=0))
        consumed = []

        def consume_worker():
            count = 0
            for _ in range(20):
                if bucket.try_consume(1):
                    count += 1
            consumed.append(count)

        threads = [threading.Thread(target=consume_worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        total = sum(consumed)
        assert total == 100  # 精确 100 个令牌


class TestRateLimiter:
    def test_default_limits_exist(self):
        assert "telegram" in DEFAULT_LIMITS
        assert "discord" in DEFAULT_LIMITS
        assert "email" in DEFAULT_LIMITS

    def test_check_allows_initial(self):
        limiter = RateLimiter()
        assert limiter.check("webhook") is True

    def test_check_respects_channel_limit(self):
        limiter = RateLimiter(custom_limits={
            "test": BucketConfig(capacity=2, refill_rate=0, cooldown_ms=0),
        })
        assert limiter.check("test") is True
        assert limiter.check("test") is True
        assert limiter.check("test") is False

    def test_check_with_target(self):
        limiter = RateLimiter(custom_limits={
            "test": BucketConfig(capacity=5, refill_rate=0, cooldown_ms=0),
        })
        # 渠道级和目标级独立
        assert limiter.check("test", "user1") is True
        assert limiter.check("test", "user2") is True

    def test_wait(self):
        limiter = RateLimiter(custom_limits={
            "fast": BucketConfig(capacity=1, refill_rate=100.0, cooldown_ms=0),
        })
        limiter.check("fast")
        assert limiter.wait("fast", timeout=1.0) is True

    def test_estimated_wait(self):
        limiter = RateLimiter()
        wait = limiter.estimated_wait("telegram")
        assert wait >= 0

    def test_stats(self):
        limiter = RateLimiter()
        limiter.check("telegram")
        stats = limiter.stats
        assert "global" in stats
        assert "channels" in stats

    def test_reset_channel(self):
        limiter = RateLimiter(custom_limits={
            "test": BucketConfig(capacity=2, refill_rate=0, cooldown_ms=0),
        })
        limiter.check("test")
        limiter.check("test")
        assert limiter.check("test") is False
        limiter.reset("test")
        assert limiter.check("test") is True

    def test_reset_all(self):
        limiter = RateLimiter()
        limiter.check("telegram")
        limiter.check("discord")
        limiter.reset()
        assert limiter.stats["channels"] == {}

    def test_global_rate_limit(self):
        # 全局桶 capacity=200, 所以前200应该都OK
        limiter = RateLimiter(custom_limits={
            "unlimited": BucketConfig(capacity=10000, refill_rate=1000, cooldown_ms=0),
        })
        count = 0
        for _ in range(250):
            if limiter.check("unlimited"):
                count += 1
        assert count <= 201  # 全局限制 200 + burst
