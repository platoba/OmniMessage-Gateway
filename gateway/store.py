"""
SQLite Message Store - 持久化消息存储 + 投递追踪 + 查询
"""

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple


class MessageStore:
    """
    SQLite-backed message persistence
    - 消息存储: 全量消息记录
    - 投递追踪: 状态流转 (pending→sending→sent/failed→dead)
    - 查询接口: 按渠道/状态/时间/目标查询
    - 统计分析: 成功率/延迟/渠道分布
    """

    def __init__(self, db_path: str = "omni_messages.db"):
        self.db_path = db_path
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA foreign_keys=ON")
        return self._local.conn

    @contextmanager
    def _cursor(self):
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def _init_db(self) -> None:
        with self._cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    from_channel TEXT NOT NULL,
                    to_channel TEXT NOT NULL,
                    content TEXT,
                    target TEXT NOT NULL,
                    template TEXT,
                    template_vars TEXT,
                    metadata TEXT,
                    priority INTEGER DEFAULT 5,
                    status TEXT DEFAULT 'pending',
                    retry_count INTEGER DEFAULT 0,
                    max_retries INTEGER DEFAULT 3,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    sent_at TEXT,
                    updated_at TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS delivery_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id TEXT NOT NULL,
                    event TEXT NOT NULL,
                    channel TEXT,
                    details TEXT,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY (message_id) REFERENCES messages(id)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS scheduled_messages (
                    id TEXT PRIMARY KEY,
                    message_data TEXT NOT NULL,
                    scheduled_at TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    executed_at TEXT,
                    result TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            # Indexes
            cur.execute("CREATE INDEX IF NOT EXISTS idx_msg_status ON messages(status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_msg_channel ON messages(to_channel)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_msg_created ON messages(created_at)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_msg_target ON messages(target)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_events_msg ON delivery_events(message_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_sched_status ON scheduled_messages(status)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_sched_at ON scheduled_messages(scheduled_at)")

    def save_message(self, msg_dict: Dict[str, Any]) -> None:
        """保存消息"""
        now = datetime.utcnow().isoformat()
        with self._cursor() as cur:
            cur.execute("""
                INSERT OR REPLACE INTO messages
                (id, from_channel, to_channel, content, target, template, template_vars,
                 metadata, priority, status, retry_count, max_retries, last_error,
                 created_at, sent_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                msg_dict["id"],
                msg_dict.get("from_channel", ""),
                msg_dict.get("to_channel", ""),
                msg_dict.get("content", ""),
                msg_dict.get("target", ""),
                msg_dict.get("template"),
                json.dumps(msg_dict.get("template_vars", {})),
                json.dumps(msg_dict.get("metadata", {})),
                msg_dict.get("priority", 5),
                msg_dict.get("status", "pending"),
                msg_dict.get("retry_count", 0),
                msg_dict.get("max_retries", 3),
                msg_dict.get("last_error"),
                msg_dict.get("created_at", now),
                msg_dict.get("sent_at"),
                now,
            ))

    def update_status(self, message_id: str, status: str, error: str = None) -> None:
        """更新消息状态"""
        now = datetime.utcnow().isoformat()
        with self._cursor() as cur:
            if error:
                cur.execute(
                    "UPDATE messages SET status=?, last_error=?, updated_at=? WHERE id=?",
                    (status, error, now, message_id),
                )
            else:
                sent_at = now if status == "sent" else None
                cur.execute(
                    "UPDATE messages SET status=?, sent_at=COALESCE(?, sent_at), updated_at=? WHERE id=?",
                    (status, sent_at, now, message_id),
                )

    def log_event(self, message_id: str, event: str, channel: str = None, details: str = None) -> None:
        """记录投递事件"""
        with self._cursor() as cur:
            cur.execute("""
                INSERT INTO delivery_events (message_id, event, channel, details, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, (message_id, event, channel, details, datetime.utcnow().isoformat()))

    def get_message(self, message_id: str) -> Optional[Dict[str, Any]]:
        """获取单条消息"""
        with self._cursor() as cur:
            cur.execute("SELECT * FROM messages WHERE id=?", (message_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_events(self, message_id: str) -> List[Dict[str, Any]]:
        """获取消息的投递事件"""
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM delivery_events WHERE message_id=? ORDER BY timestamp",
                (message_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    def query_messages(
        self,
        channel: str = None,
        status: str = None,
        target: str = None,
        since: str = None,
        until: str = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """查询消息"""
        conditions = []
        params: list = []

        if channel:
            conditions.append("to_channel=?")
            params.append(channel)
        if status:
            conditions.append("status=?")
            params.append(status)
        if target:
            conditions.append("target=?")
            params.append(target)
        if since:
            conditions.append("created_at>=?")
            params.append(since)
        if until:
            conditions.append("created_at<=?")
            params.append(until)

        where = " AND ".join(conditions) if conditions else "1=1"
        params.extend([limit, offset])

        with self._cursor() as cur:
            cur.execute(
                f"SELECT * FROM messages WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                params,
            )
            return [dict(r) for r in cur.fetchall()]

    def count_messages(self, channel: str = None, status: str = None) -> int:
        """统计消息数量"""
        conditions = []
        params: list = []
        if channel:
            conditions.append("to_channel=?")
            params.append(channel)
        if status:
            conditions.append("status=?")
            params.append(status)

        where = " AND ".join(conditions) if conditions else "1=1"
        with self._cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM messages WHERE {where}", params)
            return cur.fetchone()[0]

    def get_stats(self, hours: int = 24) -> Dict[str, Any]:
        """获取统计数据"""
        since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        with self._cursor() as cur:
            # 总体统计
            cur.execute(
                "SELECT status, COUNT(*) as cnt FROM messages WHERE created_at>=? GROUP BY status",
                (since,),
            )
            status_counts = {row["status"]: row["cnt"] for row in cur.fetchall()}

            # 按渠道统计
            cur.execute(
                "SELECT to_channel, COUNT(*) as cnt FROM messages WHERE created_at>=? GROUP BY to_channel",
                (since,),
            )
            channel_counts = {row["to_channel"]: row["cnt"] for row in cur.fetchall()}

            # 按小时统计
            cur.execute("""
                SELECT substr(created_at, 1, 13) as hour, COUNT(*) as cnt
                FROM messages WHERE created_at>=?
                GROUP BY hour ORDER BY hour
            """, (since,))
            hourly = {row["hour"]: row["cnt"] for row in cur.fetchall()}

            total = sum(status_counts.values())
            sent = status_counts.get("sent", 0)

            return {
                "period_hours": hours,
                "total": total,
                "by_status": status_counts,
                "by_channel": channel_counts,
                "by_hour": hourly,
                "success_rate": round(sent / total * 100, 2) if total > 0 else 0.0,
            }

    # ── Scheduled Messages ───────────────────────────────

    def save_scheduled(self, schedule_id: str, message_data: Dict, scheduled_at: str) -> None:
        """保存定时消息"""
        with self._cursor() as cur:
            cur.execute("""
                INSERT INTO scheduled_messages (id, message_data, scheduled_at, created_at)
                VALUES (?, ?, ?, ?)
            """, (schedule_id, json.dumps(message_data), scheduled_at, datetime.utcnow().isoformat()))

    def get_due_scheduled(self) -> List[Dict[str, Any]]:
        """获取到期的定时消息"""
        now = datetime.utcnow().isoformat()
        with self._cursor() as cur:
            cur.execute("""
                SELECT * FROM scheduled_messages
                WHERE status='pending' AND scheduled_at<=?
                ORDER BY scheduled_at
            """, (now,))
            return [dict(r) for r in cur.fetchall()]

    def mark_scheduled_done(self, schedule_id: str, result: str = None) -> None:
        """标记定时消息已执行"""
        with self._cursor() as cur:
            cur.execute("""
                UPDATE scheduled_messages
                SET status='executed', executed_at=?, result=?
                WHERE id=?
            """, (datetime.utcnow().isoformat(), result, schedule_id))

    def get_scheduled(self, status: str = None, limit: int = 50) -> List[Dict[str, Any]]:
        """查询定时消息"""
        with self._cursor() as cur:
            if status:
                cur.execute(
                    "SELECT * FROM scheduled_messages WHERE status=? ORDER BY scheduled_at LIMIT ?",
                    (status, limit),
                )
            else:
                cur.execute(
                    "SELECT * FROM scheduled_messages ORDER BY scheduled_at LIMIT ?",
                    (limit,),
                )
            return [dict(r) for r in cur.fetchall()]

    def delete_scheduled(self, schedule_id: str) -> bool:
        """删除定时消息"""
        with self._cursor() as cur:
            cur.execute("DELETE FROM scheduled_messages WHERE id=?", (schedule_id,))
            return cur.rowcount > 0

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
