"""
Contact Manager - 联系人管理 + 分组 + 标签 + 偏好 + 退订
"""

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set


class ContactManager:
    """
    统一联系人管理系统

    Features:
    - 联系人CRUD: 创建/更新/删除/查询联系人
    - 分组管理: 创建分组 + 联系人归组 + 分组查询
    - 标签系统: 添加/删除标签 + 按标签查询
    - 渠道偏好: 每个联系人的首选渠道 + 各渠道地址
    - 退订管理: 全局/渠道级退订 + 退订历史
    - 分段查询: 按条件组合筛选联系人
    - 活跃度追踪: 消息发送/接收计数 + 最后互动时间
    """

    def __init__(self, db_path: str = "omni_contacts.db"):
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
                CREATE TABLE IF NOT EXISTS contacts (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT,
                    phone TEXT,
                    preferred_channel TEXT,
                    metadata TEXT DEFAULT '{}',
                    messages_sent INTEGER DEFAULT 0,
                    messages_received INTEGER DEFAULT 0,
                    last_contacted_at TEXT,
                    opted_out INTEGER DEFAULT 0,
                    opted_out_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS contact_channels (
                    contact_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    address TEXT NOT NULL,
                    verified INTEGER DEFAULT 0,
                    opted_out INTEGER DEFAULT 0,
                    opted_out_at TEXT,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (contact_id, channel),
                    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS groups (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT,
                    metadata TEXT DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS contact_groups (
                    contact_id TEXT NOT NULL,
                    group_id TEXT NOT NULL,
                    added_at TEXT NOT NULL,
                    PRIMARY KEY (contact_id, group_id),
                    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE,
                    FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS contact_tags (
                    contact_id TEXT NOT NULL,
                    tag TEXT NOT NULL,
                    added_at TEXT NOT NULL,
                    PRIMARY KEY (contact_id, tag),
                    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS opt_out_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    contact_id TEXT NOT NULL,
                    channel TEXT,
                    action TEXT NOT NULL,
                    reason TEXT,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE
                )
            """)
            # Indexes
            cur.execute("CREATE INDEX IF NOT EXISTS idx_contact_name ON contacts(name)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_contact_email ON contacts(email)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_contact_opted ON contacts(opted_out)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_cc_channel ON contact_channels(channel)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_ct_tag ON contact_tags(tag)")

    # ── Contact CRUD ─────────────────────────────────────

    def create_contact(
        self,
        contact_id: str,
        name: str,
        email: str = None,
        phone: str = None,
        preferred_channel: str = None,
        metadata: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """创建联系人"""
        now = datetime.utcnow().isoformat()
        with self._cursor() as cur:
            cur.execute("""
                INSERT INTO contacts (id, name, email, phone, preferred_channel, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                contact_id, name, email, phone, preferred_channel,
                json.dumps(metadata or {}), now, now,
            ))
        return self.get_contact(contact_id)

    def get_contact(self, contact_id: str) -> Optional[Dict[str, Any]]:
        """获取联系人详情 (含渠道+标签+分组)"""
        with self._cursor() as cur:
            cur.execute("SELECT * FROM contacts WHERE id=?", (contact_id,))
            row = cur.fetchone()
            if not row:
                return None

            contact = dict(row)
            contact["metadata"] = json.loads(contact.get("metadata") or "{}")

            # 获取渠道
            cur.execute("SELECT * FROM contact_channels WHERE contact_id=?", (contact_id,))
            contact["channels"] = [dict(r) for r in cur.fetchall()]

            # 获取标签
            cur.execute("SELECT tag FROM contact_tags WHERE contact_id=?", (contact_id,))
            contact["tags"] = [r["tag"] for r in cur.fetchall()]

            # 获取分组
            cur.execute("""
                SELECT g.id, g.name FROM groups g
                JOIN contact_groups cg ON g.id = cg.group_id
                WHERE cg.contact_id=?
            """, (contact_id,))
            contact["groups"] = [{"id": r["id"], "name": r["name"]} for r in cur.fetchall()]

            return contact

    def update_contact(self, contact_id: str, **kwargs) -> Optional[Dict[str, Any]]:
        """更新联系人"""
        allowed = {"name", "email", "phone", "preferred_channel", "metadata"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return self.get_contact(contact_id)

        now = datetime.utcnow().isoformat()
        sets = []
        params = []
        for key, value in updates.items():
            if key == "metadata":
                value = json.dumps(value)
            sets.append(f"{key}=?")
            params.append(value)

        sets.append("updated_at=?")
        params.append(now)
        params.append(contact_id)

        with self._cursor() as cur:
            cur.execute(f"UPDATE contacts SET {', '.join(sets)} WHERE id=?", params)

        return self.get_contact(contact_id)

    def delete_contact(self, contact_id: str) -> bool:
        """删除联系人 (级联删除渠道、标签、分组关系)"""
        with self._cursor() as cur:
            cur.execute("DELETE FROM contacts WHERE id=?", (contact_id,))
            return cur.rowcount > 0

    def list_contacts(
        self,
        limit: int = 100,
        offset: int = 0,
        include_opted_out: bool = False,
    ) -> List[Dict[str, Any]]:
        """列出联系人"""
        with self._cursor() as cur:
            if include_opted_out:
                cur.execute(
                    "SELECT * FROM contacts ORDER BY name LIMIT ? OFFSET ?",
                    (limit, offset),
                )
            else:
                cur.execute(
                    "SELECT * FROM contacts WHERE opted_out=0 ORDER BY name LIMIT ? OFFSET ?",
                    (limit, offset),
                )
            contacts = []
            for row in cur.fetchall():
                c = dict(row)
                c["metadata"] = json.loads(c.get("metadata") or "{}")
                contacts.append(c)
            return contacts

    def count_contacts(self, include_opted_out: bool = False) -> int:
        """统计联系人数"""
        with self._cursor() as cur:
            if include_opted_out:
                cur.execute("SELECT COUNT(*) FROM contacts")
            else:
                cur.execute("SELECT COUNT(*) FROM contacts WHERE opted_out=0")
            return cur.fetchone()[0]

    # ── Channel Management ───────────────────────────────

    def add_channel(
        self,
        contact_id: str,
        channel: str,
        address: str,
        verified: bool = False,
    ) -> None:
        """为联系人添加渠道地址"""
        now = datetime.utcnow().isoformat()
        with self._cursor() as cur:
            cur.execute("""
                INSERT OR REPLACE INTO contact_channels
                (contact_id, channel, address, verified, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (contact_id, channel, address, int(verified), now))

    def remove_channel(self, contact_id: str, channel: str) -> bool:
        """移除渠道地址"""
        with self._cursor() as cur:
            cur.execute(
                "DELETE FROM contact_channels WHERE contact_id=? AND channel=?",
                (contact_id, channel),
            )
            return cur.rowcount > 0

    def get_channel_address(self, contact_id: str, channel: str) -> Optional[str]:
        """获取联系人在指定渠道的地址"""
        with self._cursor() as cur:
            cur.execute(
                "SELECT address FROM contact_channels WHERE contact_id=? AND channel=? AND opted_out=0",
                (contact_id, channel),
            )
            row = cur.fetchone()
            return row["address"] if row else None

    def get_contacts_by_channel(self, channel: str, limit: int = 1000) -> List[Dict[str, Any]]:
        """获取某渠道的所有联系人"""
        with self._cursor() as cur:
            cur.execute("""
                SELECT c.*, cc.address, cc.verified FROM contacts c
                JOIN contact_channels cc ON c.id = cc.contact_id
                WHERE cc.channel=? AND c.opted_out=0 AND cc.opted_out=0
                ORDER BY c.name LIMIT ?
            """, (channel, limit))
            results = []
            for row in cur.fetchall():
                r = dict(row)
                r["metadata"] = json.loads(r.get("metadata") or "{}")
                results.append(r)
            return results

    # ── Tag Management ───────────────────────────────────

    def add_tag(self, contact_id: str, tag: str) -> None:
        """添加标签"""
        now = datetime.utcnow().isoformat()
        with self._cursor() as cur:
            cur.execute("""
                INSERT OR IGNORE INTO contact_tags (contact_id, tag, added_at)
                VALUES (?, ?, ?)
            """, (contact_id, tag, now))

    def add_tags(self, contact_id: str, tags: List[str]) -> None:
        """批量添加标签"""
        for tag in tags:
            self.add_tag(contact_id, tag)

    def remove_tag(self, contact_id: str, tag: str) -> bool:
        """移除标签"""
        with self._cursor() as cur:
            cur.execute(
                "DELETE FROM contact_tags WHERE contact_id=? AND tag=?",
                (contact_id, tag),
            )
            return cur.rowcount > 0

    def get_tags(self, contact_id: str) -> List[str]:
        """获取联系人的所有标签"""
        with self._cursor() as cur:
            cur.execute("SELECT tag FROM contact_tags WHERE contact_id=? ORDER BY tag", (contact_id,))
            return [r["tag"] for r in cur.fetchall()]

    def get_contacts_by_tag(self, tag: str, limit: int = 1000) -> List[Dict[str, Any]]:
        """按标签查询联系人"""
        with self._cursor() as cur:
            cur.execute("""
                SELECT c.* FROM contacts c
                JOIN contact_tags ct ON c.id = ct.contact_id
                WHERE ct.tag=? AND c.opted_out=0
                ORDER BY c.name LIMIT ?
            """, (tag, limit))
            results = []
            for row in cur.fetchall():
                r = dict(row)
                r["metadata"] = json.loads(r.get("metadata") or "{}")
                results.append(r)
            return results

    def get_contacts_by_tags(self, tags: List[str], match_all: bool = False) -> List[Dict[str, Any]]:
        """按多个标签查询 (match_all=True时要求全部匹配)"""
        if not tags:
            return []

        placeholders = ",".join("?" * len(tags))

        with self._cursor() as cur:
            if match_all:
                cur.execute(f"""
                    SELECT c.* FROM contacts c
                    JOIN contact_tags ct ON c.id = ct.contact_id
                    WHERE ct.tag IN ({placeholders}) AND c.opted_out=0
                    GROUP BY c.id
                    HAVING COUNT(DISTINCT ct.tag) = ?
                    ORDER BY c.name
                """, (*tags, len(tags)))
            else:
                cur.execute(f"""
                    SELECT DISTINCT c.* FROM contacts c
                    JOIN contact_tags ct ON c.id = ct.contact_id
                    WHERE ct.tag IN ({placeholders}) AND c.opted_out=0
                    ORDER BY c.name
                """, tags)

            results = []
            for row in cur.fetchall():
                r = dict(row)
                r["metadata"] = json.loads(r.get("metadata") or "{}")
                results.append(r)
            return results

    def get_all_tags(self) -> List[Dict[str, Any]]:
        """获取所有标签及其使用计数"""
        with self._cursor() as cur:
            cur.execute("""
                SELECT tag, COUNT(*) as count FROM contact_tags
                GROUP BY tag ORDER BY count DESC
            """)
            return [{"tag": r["tag"], "count": r["count"]} for r in cur.fetchall()]

    # ── Group Management ─────────────────────────────────

    def create_group(
        self,
        group_id: str,
        name: str,
        description: str = None,
        metadata: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """创建分组"""
        now = datetime.utcnow().isoformat()
        with self._cursor() as cur:
            cur.execute("""
                INSERT INTO groups (id, name, description, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (group_id, name, description, json.dumps(metadata or {}), now, now))
        return self.get_group(group_id)

    def get_group(self, group_id: str) -> Optional[Dict[str, Any]]:
        """获取分组详情"""
        with self._cursor() as cur:
            cur.execute("SELECT * FROM groups WHERE id=?", (group_id,))
            row = cur.fetchone()
            if not row:
                return None

            group = dict(row)
            group["metadata"] = json.loads(group.get("metadata") or "{}")

            # 成员数
            cur.execute("SELECT COUNT(*) FROM contact_groups WHERE group_id=?", (group_id,))
            group["member_count"] = cur.fetchone()[0]

            return group

    def delete_group(self, group_id: str) -> bool:
        """删除分组"""
        with self._cursor() as cur:
            cur.execute("DELETE FROM groups WHERE id=?", (group_id,))
            return cur.rowcount > 0

    def list_groups(self) -> List[Dict[str, Any]]:
        """列出所有分组"""
        with self._cursor() as cur:
            cur.execute("""
                SELECT g.*, COUNT(cg.contact_id) as member_count
                FROM groups g
                LEFT JOIN contact_groups cg ON g.id = cg.group_id
                GROUP BY g.id
                ORDER BY g.name
            """)
            results = []
            for row in cur.fetchall():
                r = dict(row)
                r["metadata"] = json.loads(r.get("metadata") or "{}")
                results.append(r)
            return results

    def add_to_group(self, contact_id: str, group_id: str) -> None:
        """添加联系人到分组"""
        now = datetime.utcnow().isoformat()
        with self._cursor() as cur:
            cur.execute("""
                INSERT OR IGNORE INTO contact_groups (contact_id, group_id, added_at)
                VALUES (?, ?, ?)
            """, (contact_id, group_id, now))

    def remove_from_group(self, contact_id: str, group_id: str) -> bool:
        """从分组移除联系人"""
        with self._cursor() as cur:
            cur.execute(
                "DELETE FROM contact_groups WHERE contact_id=? AND group_id=?",
                (contact_id, group_id),
            )
            return cur.rowcount > 0

    def get_group_members(self, group_id: str, limit: int = 1000) -> List[Dict[str, Any]]:
        """获取分组成员"""
        with self._cursor() as cur:
            cur.execute("""
                SELECT c.* FROM contacts c
                JOIN contact_groups cg ON c.id = cg.contact_id
                WHERE cg.group_id=? AND c.opted_out=0
                ORDER BY c.name LIMIT ?
            """, (group_id, limit))
            results = []
            for row in cur.fetchall():
                r = dict(row)
                r["metadata"] = json.loads(r.get("metadata") or "{}")
                results.append(r)
            return results

    # ── Opt-out / Unsubscribe ────────────────────────────

    def opt_out(self, contact_id: str, channel: str = None, reason: str = None) -> None:
        """退订 (channel=None表示全局退订)"""
        now = datetime.utcnow().isoformat()
        with self._cursor() as cur:
            if channel:
                # 渠道级退订
                cur.execute("""
                    UPDATE contact_channels SET opted_out=1, opted_out_at=?
                    WHERE contact_id=? AND channel=?
                """, (now, contact_id, channel))
                action = f"opt_out:{channel}"
            else:
                # 全局退订
                cur.execute(
                    "UPDATE contacts SET opted_out=1, opted_out_at=? WHERE id=?",
                    (now, contact_id),
                )
                action = "opt_out:global"

            # 记录历史
            cur.execute("""
                INSERT INTO opt_out_history (contact_id, channel, action, reason, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, (contact_id, channel, action, reason, now))

    def opt_in(self, contact_id: str, channel: str = None, reason: str = None) -> None:
        """重新订阅"""
        now = datetime.utcnow().isoformat()
        with self._cursor() as cur:
            if channel:
                cur.execute("""
                    UPDATE contact_channels SET opted_out=0, opted_out_at=NULL
                    WHERE contact_id=? AND channel=?
                """, (contact_id, channel))
                action = f"opt_in:{channel}"
            else:
                cur.execute(
                    "UPDATE contacts SET opted_out=0, opted_out_at=NULL WHERE id=?",
                    (contact_id,),
                )
                action = "opt_in:global"

            cur.execute("""
                INSERT INTO opt_out_history (contact_id, channel, action, reason, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """, (contact_id, channel, action, reason, now))

    def is_opted_out(self, contact_id: str, channel: str = None) -> bool:
        """检查是否已退订"""
        with self._cursor() as cur:
            # 先检查全局退订
            cur.execute("SELECT opted_out FROM contacts WHERE id=?", (contact_id,))
            row = cur.fetchone()
            if not row:
                return True  # 联系人不存在视为退订
            if row["opted_out"]:
                return True

            # 检查渠道级退订
            if channel:
                cur.execute(
                    "SELECT opted_out FROM contact_channels WHERE contact_id=? AND channel=?",
                    (contact_id, channel),
                )
                row = cur.fetchone()
                if row and row["opted_out"]:
                    return True

            return False

    def get_opt_out_history(self, contact_id: str) -> List[Dict[str, Any]]:
        """获取退订历史"""
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM opt_out_history WHERE contact_id=? ORDER BY timestamp DESC",
                (contact_id,),
            )
            return [dict(r) for r in cur.fetchall()]

    # ── Activity Tracking ────────────────────────────────

    def record_sent(self, contact_id: str) -> None:
        """记录发送消息"""
        now = datetime.utcnow().isoformat()
        with self._cursor() as cur:
            cur.execute("""
                UPDATE contacts
                SET messages_sent = messages_sent + 1,
                    last_contacted_at = ?,
                    updated_at = ?
                WHERE id=?
            """, (now, now, contact_id))

    def record_received(self, contact_id: str) -> None:
        """记录接收消息"""
        now = datetime.utcnow().isoformat()
        with self._cursor() as cur:
            cur.execute("""
                UPDATE contacts
                SET messages_received = messages_received + 1,
                    last_contacted_at = ?,
                    updated_at = ?
                WHERE id=?
            """, (now, now, contact_id))

    # ── Segment Query ────────────────────────────────────

    def segment_query(
        self,
        tags: List[str] = None,
        groups: List[str] = None,
        channels: List[str] = None,
        min_messages: int = None,
        inactive_days: int = None,
        active_days: int = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """
        分段查询 - 按多条件组合筛选联系人

        Args:
            tags: 必须包含的标签 (AND)
            groups: 必须属于的分组 (OR)
            channels: 必须有的渠道 (OR)
            min_messages: 最少消息数
            inactive_days: 超过N天未互动
            active_days: 最近N天内有互动
        """
        conditions = ["c.opted_out=0"]
        params: list = []
        joins = []

        if tags:
            placeholders = ",".join("?" * len(tags))
            joins.append("JOIN contact_tags ct ON c.id = ct.contact_id")
            conditions.append(f"ct.tag IN ({placeholders})")
            params.extend(tags)

        if groups:
            placeholders = ",".join("?" * len(groups))
            joins.append("JOIN contact_groups cg ON c.id = cg.contact_id")
            conditions.append(f"cg.group_id IN ({placeholders})")
            params.extend(groups)

        if channels:
            placeholders = ",".join("?" * len(channels))
            joins.append("JOIN contact_channels cc ON c.id = cc.contact_id")
            conditions.append(f"cc.channel IN ({placeholders}) AND cc.opted_out=0")
            params.extend(channels)

        if min_messages is not None:
            conditions.append("(c.messages_sent + c.messages_received) >= ?")
            params.append(min_messages)

        if inactive_days is not None:
            cutoff = (datetime.utcnow() - timedelta(days=inactive_days)).isoformat()
            conditions.append("(c.last_contacted_at IS NULL OR c.last_contacted_at < ?)")
            params.append(cutoff)

        if active_days is not None:
            cutoff = (datetime.utcnow() - timedelta(days=active_days)).isoformat()
            conditions.append("c.last_contacted_at >= ?")
            params.append(cutoff)

        join_clause = " ".join(joins)
        where_clause = " AND ".join(conditions)
        params.append(limit)

        with self._cursor() as cur:
            sql = f"""
                SELECT DISTINCT c.* FROM contacts c
                {join_clause}
                WHERE {where_clause}
                ORDER BY c.name LIMIT ?
            """
            cur.execute(sql, params)
            results = []
            for row in cur.fetchall():
                r = dict(row)
                r["metadata"] = json.loads(r.get("metadata") or "{}")
                results.append(r)
            return results

    # ── Search ───────────────────────────────────────────

    def search(self, query: str, limit: int = 50) -> List[Dict[str, Any]]:
        """搜索联系人 (name/email/phone)"""
        pattern = f"%{query}%"
        with self._cursor() as cur:
            cur.execute("""
                SELECT * FROM contacts
                WHERE (name LIKE ? OR email LIKE ? OR phone LIKE ?)
                AND opted_out=0
                ORDER BY name LIMIT ?
            """, (pattern, pattern, pattern, limit))
            results = []
            for row in cur.fetchall():
                r = dict(row)
                r["metadata"] = json.loads(r.get("metadata") or "{}")
                results.append(r)
            return results

    # ── Import / Export ──────────────────────────────────

    def export_contacts(self, format: str = "json") -> str:
        """导出联系人"""
        contacts = self.list_contacts(limit=100000, include_opted_out=True)

        if format == "csv":
            lines = ["id,name,email,phone,preferred_channel,opted_out,messages_sent,messages_received"]
            for c in contacts:
                lines.append(
                    f"{c['id']},{c['name']},{c.get('email','')},{c.get('phone','')},"
                    f"{c.get('preferred_channel','')},{c['opted_out']},"
                    f"{c['messages_sent']},{c['messages_received']}"
                )
            return "\n".join(lines)

        return json.dumps(contacts, indent=2, ensure_ascii=False)

    def import_contacts(self, data: List[Dict[str, Any]]) -> Dict[str, int]:
        """批量导入联系人"""
        created = 0
        updated = 0
        errors = 0

        for item in data:
            try:
                existing = self.get_contact(item["id"])
                if existing:
                    self.update_contact(item["id"], **{
                        k: v for k, v in item.items()
                        if k in ("name", "email", "phone", "preferred_channel", "metadata")
                    })
                    updated += 1
                else:
                    self.create_contact(
                        contact_id=item["id"],
                        name=item["name"],
                        email=item.get("email"),
                        phone=item.get("phone"),
                        preferred_channel=item.get("preferred_channel"),
                        metadata=item.get("metadata"),
                    )
                    created += 1
            except Exception:
                errors += 1

        return {"created": created, "updated": updated, "errors": errors}

    # ── Stats ────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """获取联系人统计"""
        with self._cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM contacts")
            total = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM contacts WHERE opted_out=1")
            opted_out = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM groups")
            groups = cur.fetchone()[0]

            cur.execute("SELECT COUNT(DISTINCT tag) FROM contact_tags")
            tags = cur.fetchone()[0]

            cur.execute("""
                SELECT channel, COUNT(*) as cnt
                FROM contact_channels WHERE opted_out=0
                GROUP BY channel
            """)
            by_channel = {r["channel"]: r["cnt"] for r in cur.fetchall()}

            cur.execute("""
                SELECT SUM(messages_sent) as sent, SUM(messages_received) as received
                FROM contacts
            """)
            msg_row = cur.fetchone()
            total_sent = msg_row["sent"] or 0
            total_received = msg_row["received"] or 0

            return {
                "total_contacts": total,
                "active_contacts": total - opted_out,
                "opted_out": opted_out,
                "groups": groups,
                "unique_tags": tags,
                "by_channel": by_channel,
                "total_messages_sent": total_sent,
                "total_messages_received": total_received,
            }

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
