"""
Message Deduplication System

Prevents duplicate message delivery using content-based fingerprinting
and time-window deduplication with LRU cache and SQLite persistence.
"""

import hashlib
import time
from typing import Optional, Dict, Any
from collections import OrderedDict
from datetime import datetime, timedelta
import sqlite3
import asyncio
from pathlib import Path

from .models import Message


class DeduplicationCache:
    """In-memory LRU cache for fast deduplication checks."""
    
    def __init__(self, max_size: int = 10000, ttl_seconds: int = 3600):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.cache: OrderedDict[str, float] = OrderedDict()
        self._lock = asyncio.Lock()
    
    async def contains(self, fingerprint: str) -> bool:
        """Check if fingerprint exists and is not expired."""
        async with self._lock:
            if fingerprint not in self.cache:
                return False
            
            timestamp = self.cache[fingerprint]
            if time.time() - timestamp > self.ttl_seconds:
                # Expired, remove it
                del self.cache[fingerprint]
                return False
            
            # Move to end (LRU)
            self.cache.move_to_end(fingerprint)
            return True
    
    async def add(self, fingerprint: str) -> None:
        """Add fingerprint to cache."""
        async with self._lock:
            self.cache[fingerprint] = time.time()
            self.cache.move_to_end(fingerprint)
            
            # Evict oldest if over size
            while len(self.cache) > self.max_size:
                self.cache.popitem(last=False)
    
    async def cleanup_expired(self) -> int:
        """Remove expired entries, return count removed."""
        async with self._lock:
            now = time.time()
            expired = [
                fp for fp, ts in self.cache.items()
                if now - ts > self.ttl_seconds
            ]
            for fp in expired:
                del self.cache[fp]
            return len(expired)


class DeduplicationStore:
    """SQLite-backed persistent deduplication store."""
    
    def __init__(self, db_path: str = "deduplication.db"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """Initialize SQLite schema."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS dedup_fingerprints (
                fingerprint TEXT PRIMARY KEY,
                first_seen REAL NOT NULL,
                last_seen REAL NOT NULL,
                count INTEGER DEFAULT 1,
                channel TEXT,
                target TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_last_seen 
            ON dedup_fingerprints(last_seen)
        """)
        conn.commit()
        conn.close()
    
    async def contains(self, fingerprint: str, ttl_seconds: int) -> bool:
        """Check if fingerprint exists within TTL window."""
        conn = sqlite3.connect(self.db_path)
        cutoff = time.time() - ttl_seconds
        
        result = conn.execute(
            "SELECT 1 FROM dedup_fingerprints WHERE fingerprint = ? AND last_seen > ?",
            (fingerprint, cutoff)
        ).fetchone()
        
        conn.close()
        return result is not None
    
    async def add(self, fingerprint: str, channel: str, target: str) -> None:
        """Add or update fingerprint in store."""
        conn = sqlite3.connect(self.db_path)
        now = time.time()
        
        conn.execute("""
            INSERT INTO dedup_fingerprints (fingerprint, first_seen, last_seen, count, channel, target)
            VALUES (?, ?, ?, 1, ?, ?)
            ON CONFLICT(fingerprint) DO UPDATE SET
                last_seen = ?,
                count = count + 1
        """, (fingerprint, now, now, channel, target, now))
        
        conn.commit()
        conn.close()
    
    async def cleanup_expired(self, ttl_seconds: int) -> int:
        """Remove expired entries, return count removed."""
        conn = sqlite3.connect(self.db_path)
        cutoff = time.time() - ttl_seconds
        
        cursor = conn.execute(
            "DELETE FROM dedup_fingerprints WHERE last_seen < ?",
            (cutoff,)
        )
        count = cursor.rowcount
        
        conn.commit()
        conn.close()
        return count
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get deduplication statistics."""
        conn = sqlite3.connect(self.db_path)
        
        total = conn.execute("SELECT COUNT(*) FROM dedup_fingerprints").fetchone()[0]
        
        duplicates = conn.execute(
            "SELECT COUNT(*) FROM dedup_fingerprints WHERE count > 1"
        ).fetchone()[0]
        
        top_channels = conn.execute("""
            SELECT channel, COUNT(*) as cnt
            FROM dedup_fingerprints
            GROUP BY channel
            ORDER BY cnt DESC
            LIMIT 5
        """).fetchall()
        
        conn.close()
        
        return {
            "total_fingerprints": total,
            "duplicate_attempts": duplicates,
            "top_channels": [{"channel": ch, "count": cnt} for ch, cnt in top_channels]
        }


class MessageDeduplicator:
    """
    Message deduplication manager with two-tier caching:
    - L1: In-memory LRU cache (fast, limited size)
    - L2: SQLite persistent store (slower, unlimited)
    """
    
    def __init__(
        self,
        cache_size: int = 10000,
        ttl_seconds: int = 3600,
        db_path: str = "deduplication.db"
    ):
        self.cache = DeduplicationCache(cache_size, ttl_seconds)
        self.store = DeduplicationStore(db_path)
        self.ttl_seconds = ttl_seconds
        self._cleanup_task: Optional[asyncio.Task] = None
    
    def _compute_fingerprint(self, message: Message) -> str:
        """
        Compute content-based fingerprint for message.
        
        Uses: to_channel + target + content + template
        Ignores: timestamp, priority, metadata
        """
        parts = [
            message.to_channel.value,
            message.target,
            message.content,
            message.template or ""
        ]
        
        content = "|".join(parts).encode("utf-8")
        return hashlib.sha256(content).hexdigest()
    
    async def is_duplicate(self, message: Message) -> bool:
        """
        Check if message is a duplicate within TTL window.
        
        Returns True if duplicate, False if unique.
        """
        fingerprint = self._compute_fingerprint(message)
        
        # Check L1 cache first (fast)
        if await self.cache.contains(fingerprint):
            return True
        
        # Check L2 store (slower)
        if await self.store.contains(fingerprint, self.ttl_seconds):
            # Add to cache for future fast lookups
            await self.cache.add(fingerprint)
            return True
        
        return False
    
    async def mark_sent(self, message: Message) -> None:
        """Mark message as sent (add to dedup tracking)."""
        fingerprint = self._compute_fingerprint(message)
        
        # Add to both cache and store
        await self.cache.add(fingerprint)
        await self.store.add(fingerprint, message.to_channel.value, message.target)
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get deduplication statistics."""
        store_stats = await self.store.get_stats()
        
        return {
            "cache_size": len(self.cache.cache),
            "cache_max_size": self.cache.max_size,
            "ttl_seconds": self.ttl_seconds,
            **store_stats
        }
    
    async def start_cleanup_task(self, interval_seconds: int = 300):
        """Start background cleanup task."""
        async def cleanup_loop():
            while True:
                await asyncio.sleep(interval_seconds)
                
                cache_removed = await self.cache.cleanup_expired()
                store_removed = await self.store.cleanup_expired(self.ttl_seconds)
                
                print(f"[Dedup Cleanup] Removed {cache_removed} from cache, {store_removed} from store")
        
        self._cleanup_task = asyncio.create_task(cleanup_loop())
    
    async def stop_cleanup_task(self):
        """Stop background cleanup task."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
