"""Tests for priority queue system"""

import asyncio

import pytest

from gateway.priority_queue import (
    Priority,
    PriorityQueueManager,
    PriorityQueueWorker,
)


@pytest.fixture
def queue_manager():
    return PriorityQueueManager(max_size=100)


@pytest.mark.asyncio
async def test_enqueue_dequeue(queue_manager):
    """Test basic enqueue and dequeue"""
    msg_id = await queue_manager.enqueue(
        channel="telegram",
        target="123",
        content="test",
        priority=Priority.NORMAL,
    )
    assert msg_id is not None

    msg = await queue_manager.dequeue_nowait()
    assert msg is not None
    assert msg.channel == "telegram"
    assert msg.target == "123"
    assert msg.content == "test"


@pytest.mark.asyncio
async def test_priority_ordering(queue_manager):
    """Test messages are dequeued by priority"""
    # Enqueue in reverse priority order
    await queue_manager.enqueue("telegram", "1", "low", Priority.LOW)
    await queue_manager.enqueue("telegram", "2", "critical", Priority.CRITICAL)
    await queue_manager.enqueue("telegram", "3", "normal", Priority.NORMAL)
    await queue_manager.enqueue("telegram", "4", "high", Priority.HIGH)

    # Should dequeue in priority order
    msg1 = await queue_manager.dequeue_nowait()
    assert msg1.content == "critical"

    msg2 = await queue_manager.dequeue_nowait()
    assert msg2.content == "high"

    msg3 = await queue_manager.dequeue_nowait()
    assert msg3.content == "normal"

    msg4 = await queue_manager.dequeue_nowait()
    assert msg4.content == "low"


@pytest.mark.asyncio
async def test_same_priority_fifo(queue_manager):
    """Test same priority messages are FIFO"""
    await queue_manager.enqueue("telegram", "1", "first", Priority.NORMAL)
    await asyncio.sleep(0.01)  # Ensure different timestamps
    await queue_manager.enqueue("telegram", "2", "second", Priority.NORMAL)
    await asyncio.sleep(0.01)
    await queue_manager.enqueue("telegram", "3", "third", Priority.NORMAL)

    msg1 = await queue_manager.dequeue_nowait()
    assert msg1.content == "first"

    msg2 = await queue_manager.dequeue_nowait()
    assert msg2.content == "second"

    msg3 = await queue_manager.dequeue_nowait()
    assert msg3.content == "third"


@pytest.mark.asyncio
async def test_queue_full_drops_lowest_priority(queue_manager):
    """Test queue drops lowest priority when full"""
    small_queue = PriorityQueueManager(max_size=3)

    await small_queue.enqueue("telegram", "1", "low1", Priority.LOW)
    await small_queue.enqueue("telegram", "2", "low2", Priority.LOW)
    await small_queue.enqueue("telegram", "3", "low3", Priority.LOW)

    # Queue is full, adding high priority should drop a low priority
    msg_id = await small_queue.enqueue("telegram", "4", "high", Priority.HIGH)
    assert msg_id is not None

    stats = await small_queue.get_stats()
    assert stats["dropped_total"] == 1
    assert stats["queue_size"] == 3


@pytest.mark.asyncio
async def test_requeue(queue_manager):
    """Test message requeue for retry"""
    msg_id = await queue_manager.enqueue(
        channel="telegram",
        target="123",
        content="test",
        max_retries=2,
    )

    msg = await queue_manager.dequeue_nowait()
    assert msg.retry_count == 0

    # Requeue for retry
    success = await queue_manager.requeue(msg)
    assert success is True

    msg2 = await queue_manager.dequeue_nowait()
    assert msg2.message_id == msg.message_id
    assert msg2.retry_count == 1


@pytest.mark.asyncio
async def test_requeue_max_retries(queue_manager):
    """Test requeue fails after max retries"""
    msg_id = await queue_manager.enqueue(
        channel="telegram",
        target="123",
        content="test",
        max_retries=1,
    )

    msg = await queue_manager.dequeue_nowait()

    # First requeue succeeds
    success = await queue_manager.requeue(msg)
    assert success is True

    msg2 = await queue_manager.dequeue_nowait()

    # Second requeue fails (max_retries=1)
    success = await queue_manager.requeue(msg2)
    assert success is False


@pytest.mark.asyncio
async def test_peek(queue_manager):
    """Test peek doesn't remove message"""
    await queue_manager.enqueue("telegram", "123", "test", Priority.HIGH)

    msg1 = await queue_manager.peek()
    assert msg1 is not None
    assert msg1.content == "test"

    # Peek again, should be same message
    msg2 = await queue_manager.peek()
    assert msg2.message_id == msg1.message_id

    # Size should still be 1
    size = await queue_manager.size()
    assert size == 1


@pytest.mark.asyncio
async def test_size_and_empty(queue_manager):
    """Test size and is_empty"""
    assert await queue_manager.is_empty() is True
    assert await queue_manager.size() == 0

    await queue_manager.enqueue("telegram", "123", "test")
    assert await queue_manager.is_empty() is False
    assert await queue_manager.size() == 1

    await queue_manager.enqueue("telegram", "456", "test2")
    assert await queue_manager.size() == 2

    await queue_manager.dequeue_nowait()
    assert await queue_manager.size() == 1


@pytest.mark.asyncio
async def test_clear(queue_manager):
    """Test clear empties queue"""
    await queue_manager.enqueue("telegram", "1", "test1")
    await queue_manager.enqueue("telegram", "2", "test2")
    await queue_manager.enqueue("telegram", "3", "test3")

    assert await queue_manager.size() == 3

    await queue_manager.clear()
    assert await queue_manager.size() == 0
    assert await queue_manager.is_empty() is True


@pytest.mark.asyncio
async def test_get_stats(queue_manager):
    """Test statistics tracking"""
    await queue_manager.enqueue("telegram", "1", "test1", Priority.HIGH)
    await queue_manager.enqueue("telegram", "2", "test2", Priority.NORMAL)
    await queue_manager.enqueue("telegram", "3", "test3", Priority.LOW)

    stats = await queue_manager.get_stats()
    assert stats["queue_size"] == 3
    assert stats["enqueued_total"] == 3
    assert stats["dequeued_total"] == 0
    assert stats["by_priority"]["HIGH"] == 1
    assert stats["by_priority"]["NORMAL"] == 1
    assert stats["by_priority"]["LOW"] == 1

    await queue_manager.dequeue_nowait()
    stats = await queue_manager.get_stats()
    assert stats["dequeued_total"] == 1


@pytest.mark.asyncio
async def test_get_messages_by_priority(queue_manager):
    """Test filtering messages by priority"""
    await queue_manager.enqueue("telegram", "1", "high1", Priority.HIGH)
    await queue_manager.enqueue("telegram", "2", "normal1", Priority.NORMAL)
    await queue_manager.enqueue("telegram", "3", "high2", Priority.HIGH)

    high_msgs = await queue_manager.get_messages_by_priority(Priority.HIGH)
    assert len(high_msgs) == 2
    assert all(msg["priority"] == "HIGH" for msg in high_msgs)

    normal_msgs = await queue_manager.get_messages_by_priority(Priority.NORMAL)
    assert len(normal_msgs) == 1
    assert normal_msgs[0]["priority"] == "NORMAL"


@pytest.mark.asyncio
async def test_dequeue_with_timeout(queue_manager):
    """Test dequeue blocks until message or timeout"""
    # Empty queue, should timeout
    msg = await queue_manager.dequeue(timeout=0.1)
    assert msg is None

    # Add message in background
    async def add_message():
        await asyncio.sleep(0.1)
        await queue_manager.enqueue("telegram", "123", "test")

    asyncio.create_task(add_message())

    # Should block until message arrives
    msg = await queue_manager.dequeue(timeout=1.0)
    assert msg is not None
    assert msg.content == "test"


@pytest.mark.asyncio
async def test_worker_basic():
    """Test worker processes messages"""
    queue = PriorityQueueManager()
    sent_messages = []

    async def mock_send(channel, target, content, metadata):
        sent_messages.append({"channel": channel, "target": target, "content": content})

    worker = PriorityQueueWorker(queue, mock_send, worker_count=1)
    await worker.start()

    # Enqueue messages
    await queue.enqueue("telegram", "123", "msg1")
    await queue.enqueue("telegram", "456", "msg2")

    # Wait for processing
    await asyncio.sleep(0.5)

    await worker.stop()

    assert len(sent_messages) == 2
    assert sent_messages[0]["content"] == "msg1"
    assert sent_messages[1]["content"] == "msg2"


@pytest.mark.asyncio
async def test_worker_retry_on_failure():
    """Test worker retries failed messages"""
    queue = PriorityQueueManager()
    attempts = []

    async def mock_send_fail_once(channel, target, content, metadata):
        attempts.append(content)
        if len(attempts) == 1:
            raise Exception("Simulated failure")

    worker = PriorityQueueWorker(queue, mock_send_fail_once, worker_count=1)
    await worker.start()

    await queue.enqueue("telegram", "123", "test", max_retries=2)

    # Wait for processing and retry
    await asyncio.sleep(0.5)

    await worker.stop()

    # Should have tried twice (initial + 1 retry)
    assert len(attempts) == 2
    stats = worker.get_stats()
    assert stats["retried"] >= 1


@pytest.mark.asyncio
async def test_worker_stats():
    """Test worker statistics"""
    queue = PriorityQueueManager()

    async def mock_send(channel, target, content, metadata):
        pass

    worker = PriorityQueueWorker(queue, mock_send, worker_count=2)
    await worker.start()

    await queue.enqueue("telegram", "1", "msg1")
    await queue.enqueue("telegram", "2", "msg2")
    await queue.enqueue("telegram", "3", "msg3")

    await asyncio.sleep(0.5)
    await worker.stop()

    stats = worker.get_stats()
    assert stats["worker_count"] == 2
    assert stats["processed"] == 3
    assert stats["succeeded"] == 3
    assert stats["success_rate"] == 1.0


@pytest.mark.asyncio
async def test_metadata_preserved(queue_manager):
    """Test message metadata is preserved"""
    metadata = {"user_id": 123, "campaign": "test"}

    await queue_manager.enqueue(
        channel="telegram",
        target="123",
        content="test",
        metadata=metadata,
    )

    msg = await queue_manager.dequeue_nowait()
    assert msg.metadata == metadata
