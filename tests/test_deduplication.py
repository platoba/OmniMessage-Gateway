"""Tests for message deduplication system."""

import pytest
import asyncio
import time
from pathlib import Path
import tempfile
import os

from gateway.deduplication import (
    DeduplicationCache,
    DeduplicationStore,
    MessageDeduplicator
)
from gateway.models import Message, ChannelType


@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def sample_message():
    """Create sample message for testing."""
    return Message(
        from_channel=ChannelType.TELEGRAM,
        to_channel=ChannelType.TELEGRAM,
        target="123456",
        content="Hello, world!"
    )


class TestDeduplicationCache:
    """Test in-memory LRU cache."""
    
    @pytest.mark.asyncio
    async def test_add_and_contains(self):
        cache = DeduplicationCache(max_size=100, ttl_seconds=60)
        
        assert not await cache.contains("fp1")
        
        await cache.add("fp1")
        assert await cache.contains("fp1")
    
    @pytest.mark.asyncio
    async def test_ttl_expiration(self):
        cache = DeduplicationCache(max_size=100, ttl_seconds=1)
        
        await cache.add("fp1")
        assert await cache.contains("fp1")
        
        await asyncio.sleep(1.1)
        assert not await cache.contains("fp1")
    
    @pytest.mark.asyncio
    async def test_lru_eviction(self):
        cache = DeduplicationCache(max_size=3, ttl_seconds=60)
        
        await cache.add("fp1")
        await cache.add("fp2")
        await cache.add("fp3")
        await cache.add("fp4")  # Should evict fp1
        
        assert not await cache.contains("fp1")
        assert await cache.contains("fp2")
        assert await cache.contains("fp3")
        assert await cache.contains("fp4")
    
    @pytest.mark.asyncio
    async def test_cleanup_expired(self):
        cache = DeduplicationCache(max_size=100, ttl_seconds=1)
        
        await cache.add("fp1")
        await cache.add("fp2")
        
        await asyncio.sleep(1.1)
        
        removed = await cache.cleanup_expired()
        assert removed == 2
        assert len(cache.cache) == 0


class TestDeduplicationStore:
    """Test SQLite persistent store."""
    
    @pytest.mark.asyncio
    async def test_add_and_contains(self, temp_db):
        store = DeduplicationStore(temp_db)
        
        assert not await store.contains("fp1", ttl_seconds=60)
        
        await store.add("fp1", "telegram", "123")
        assert await store.contains("fp1", ttl_seconds=60)
    
    @pytest.mark.asyncio
    async def test_ttl_expiration(self, temp_db):
        store = DeduplicationStore(temp_db)
        
        await store.add("fp1", "telegram", "123")
        
        # Should not be found with 0 TTL
        assert not await store.contains("fp1", ttl_seconds=0)
    
    @pytest.mark.asyncio
    async def test_duplicate_count(self, temp_db):
        store = DeduplicationStore(temp_db)
        
        await store.add("fp1", "telegram", "123")
        await store.add("fp1", "telegram", "123")
        await store.add("fp1", "telegram", "123")
        
        stats = await store.get_stats()
        assert stats["total_fingerprints"] == 1
        assert stats["duplicate_attempts"] == 1
    
    @pytest.mark.asyncio
    async def test_cleanup_expired(self, temp_db):
        store = DeduplicationStore(temp_db)
        
        await store.add("fp1", "telegram", "123")
        await asyncio.sleep(0.1)
        
        removed = await store.cleanup_expired(ttl_seconds=0)
        assert removed == 1
        
        assert not await store.contains("fp1", ttl_seconds=60)
    
    @pytest.mark.asyncio
    async def test_get_stats(self, temp_db):
        store = DeduplicationStore(temp_db)
        
        await store.add("fp1", "telegram", "123")
        await store.add("fp2", "discord", "456")
        await store.add("fp3", "telegram", "789")
        
        stats = await store.get_stats()
        
        assert stats["total_fingerprints"] == 3
        assert len(stats["top_channels"]) == 2
        assert stats["top_channels"][0]["channel"] == "telegram"
        assert stats["top_channels"][0]["count"] == 2


class TestMessageDeduplicator:
    """Test full deduplication manager."""
    
    @pytest.mark.asyncio
    async def test_fingerprint_computation(self, temp_db, sample_message):
        dedup = MessageDeduplicator(db_path=temp_db)
        
        fp1 = dedup._compute_fingerprint(sample_message)
        fp2 = dedup._compute_fingerprint(sample_message)
        
        assert fp1 == fp2
        assert len(fp1) == 64  # SHA-256 hex
    
    @pytest.mark.asyncio
    async def test_fingerprint_ignores_metadata(self, temp_db):
        dedup = MessageDeduplicator(db_path=temp_db)
        
        msg1 = Message(
            from_channel=ChannelType.TELEGRAM,
            to_channel=ChannelType.TELEGRAM,
            target="123",
            content="Hello",
            metadata={"key": "value1"}
        )
        
        msg2 = Message(
            from_channel=ChannelType.TELEGRAM,
            to_channel=ChannelType.TELEGRAM,
            target="123",
            content="Hello",
            metadata={"key": "value2"}
        )
        
        fp1 = dedup._compute_fingerprint(msg1)
        fp2 = dedup._compute_fingerprint(msg2)
        
        assert fp1 == fp2
    
    @pytest.mark.asyncio
    async def test_is_duplicate_new_message(self, temp_db, sample_message):
        dedup = MessageDeduplicator(db_path=temp_db)
        
        assert not await dedup.is_duplicate(sample_message)
    
    @pytest.mark.asyncio
    async def test_is_duplicate_after_mark_sent(self, temp_db, sample_message):
        dedup = MessageDeduplicator(db_path=temp_db)
        
        await dedup.mark_sent(sample_message)
        
        assert await dedup.is_duplicate(sample_message)
    
    @pytest.mark.asyncio
    async def test_two_tier_caching(self, temp_db, sample_message):
        dedup = MessageDeduplicator(db_path=temp_db, cache_size=10)
        
        # Mark as sent (adds to both cache and store)
        await dedup.mark_sent(sample_message)
        
        # First check hits cache
        assert await dedup.is_duplicate(sample_message)
        
        # Clear cache
        dedup.cache.cache.clear()
        
        # Second check hits store and repopulates cache
        assert await dedup.is_duplicate(sample_message)
        assert len(dedup.cache.cache) == 1
    
    @pytest.mark.asyncio
    async def test_ttl_expiration(self, temp_db, sample_message):
        dedup = MessageDeduplicator(db_path=temp_db, ttl_seconds=1)
        
        await dedup.mark_sent(sample_message)
        assert await dedup.is_duplicate(sample_message)
        
        await asyncio.sleep(1.1)
        
        # Should be expired
        assert not await dedup.is_duplicate(sample_message)
    
    @pytest.mark.asyncio
    async def test_get_stats(self, temp_db):
        dedup = MessageDeduplicator(db_path=temp_db)
        
        msg1 = Message(
            from_channel=ChannelType.TELEGRAM,
            to_channel=ChannelType.TELEGRAM,
            target="123",
            content="Hello"
        )
        msg2 = Message(
            from_channel=ChannelType.DISCORD,
            to_channel=ChannelType.DISCORD,
            target="456",
            content="World"
        )
        
        await dedup.mark_sent(msg1)
        await dedup.mark_sent(msg2)
        
        stats = await dedup.get_stats()
        
        assert stats["cache_size"] == 2
        assert stats["total_fingerprints"] == 2
    
    @pytest.mark.asyncio
    async def test_cleanup_task(self, temp_db, sample_message):
        dedup = MessageDeduplicator(db_path=temp_db, ttl_seconds=1)
        
        await dedup.mark_sent(sample_message)
        
        # Start cleanup task with short interval
        await dedup.start_cleanup_task(interval_seconds=2)
        
        await asyncio.sleep(3)
        
        # Should have cleaned up expired entry
        assert not await dedup.is_duplicate(sample_message)
        
        await dedup.stop_cleanup_task()
    
    @pytest.mark.asyncio
    async def test_different_channels_not_duplicate(self, temp_db):
        dedup = MessageDeduplicator(db_path=temp_db)
        
        msg1 = Message(
            from_channel=ChannelType.TELEGRAM,
            to_channel=ChannelType.TELEGRAM,
            target="123",
            content="Hello"
        )
        msg2 = Message(
            from_channel=ChannelType.DISCORD,
            to_channel=ChannelType.DISCORD,
            target="123",
            content="Hello"
        )
        
        await dedup.mark_sent(msg1)
        
        # Different channel, not a duplicate
        assert not await dedup.is_duplicate(msg2)
    
    @pytest.mark.asyncio
    async def test_different_targets_not_duplicate(self, temp_db):
        dedup = MessageDeduplicator(db_path=temp_db)
        
        msg1 = Message(
            from_channel=ChannelType.TELEGRAM,
            to_channel=ChannelType.TELEGRAM,
            target="123",
            content="Hello"
        )
        msg2 = Message(
            from_channel=ChannelType.TELEGRAM,
            to_channel=ChannelType.TELEGRAM,
            target="456",
            content="Hello"
        )
        
        await dedup.mark_sent(msg1)
        
        # Different target, not a duplicate
        assert not await dedup.is_duplicate(msg2)
