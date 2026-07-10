"""StarPivot Engine - Database memory mixin"""
import sqlite3
import uuid
import json
import time
import os
from datetime import datetime, timedelta
from typing import Any, Optional


class MemoryMixin:
    """Mixin providing memory-related database operations."""
    
    # All methods in this mixin access self.conn, self._execute_write, etc.
    # from the parent Database class.
    
    def create_agent_memory(self, agent_id: str, user_id: str, content: str,
                            tier: int = 1, keywords: str = "",
                            importance: float = 0.5,
                            source: str = "",
                            access_count: int = 0) -> str:
        """创建一条分级记忆，返回记忆 ID。"""
        mid = self._new_id()
        sql = """INSERT INTO agent_memories (id, agent_id, user_id, tier, content,
                 keywords, importance, source, access_count)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        self._execute_write(sql, (mid, agent_id, user_id, tier, content,
                                  keywords, importance, source, access_count))
        return mid


    def list_agent_memories_by_tier(self, agent_id: str, user_id: str,
                                    tier: int, limit: int = 50) -> list:
        """按级别查询记忆，按重要度/最近访问排序。"""
        with self.conn() as conn:
            rows = conn.execute(
                """SELECT * FROM agent_memories
                   WHERE agent_id = ? AND user_id = ? AND tier = ?
                   ORDER BY importance DESC, accessed_at DESC
                   LIMIT ?""",
                (agent_id, user_id, tier, limit),
            ).fetchall()
            return [dict(r) for r in rows]


    def list_all_agent_memories(self, agent_id: str, user_id: str,
                                limit: int = 100) -> list:
        """列出某 agent 对某用户的所有分级记忆（按级别、重要度排序）。"""
        with self.conn() as conn:
            rows = conn.execute(
                """SELECT * FROM agent_memories
                   WHERE agent_id = ? AND user_id = ?
                   ORDER BY tier ASC, importance DESC, accessed_at DESC
                   LIMIT ?""",
                (agent_id, user_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]


    def search_agent_memories(self, agent_id: str, user_id: str,
                              keyword: str, limit: int = 20) -> list:
        """按关键词搜索分级记忆。"""
        with self.conn() as conn:
            rows = conn.execute(
                """SELECT * FROM agent_memories
                   WHERE agent_id = ? AND user_id = ?
                   AND (content LIKE ? OR keywords LIKE ?)
                   ORDER BY importance DESC, tier ASC, accessed_at DESC
                   LIMIT ?""",
                (agent_id, user_id, f"%{keyword}%", f"%{keyword}%", limit),
            ).fetchall()
            return [dict(r) for r in rows]


    def touch_agent_memory(self, memory_id: str) -> bool:
        """更新记忆的最近访问时间。"""
        sql = """UPDATE agent_memories SET accessed_at = datetime('now','localtime')
                 WHERE id = ?"""
        self._execute_write(sql, (memory_id,))
        return True


    def demote_agent_memory(self, memory_id: str, new_tier: int) -> bool:
        """降级某条记忆的级别。"""
        sql = """UPDATE agent_memories SET tier = ?,
                 accessed_at = datetime('now','localtime') WHERE id = ?"""
        self._execute_write(sql, (new_tier, memory_id))
        return True


    def delete_agent_memory(self, memory_id: str) -> bool:
        """按 ID 删除记忆。"""
        self._execute_write("DELETE FROM agent_memories WHERE id = ?", (memory_id,))
        return True


    def count_agent_memories(self, agent_id: str, user_id: str,
                             tier: int = 0) -> int:
        """统计某 agent 对某用户的记忆数量。tier=0 表示全部级别。"""
        with self.conn() as conn:
            if tier:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM agent_memories WHERE agent_id = ? AND user_id = ? AND tier = ?",
                    (agent_id, user_id, tier),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM agent_memories WHERE agent_id = ? AND user_id = ?",
                    (agent_id, user_id),
                ).fetchone()
            return row["cnt"] if row else 0


    def total_agent_memories_chars(self, agent_id: str, user_id: str,
                                   tier: int = 0) -> int:
        """统计某 agent 对某用户的记忆总字符数。tier=0 表示全部级别。"""
        with self.conn() as conn:
            if tier:
                row = conn.execute(
                    "SELECT COALESCE(SUM(LENGTH(content)), 0) as total FROM agent_memories WHERE agent_id = ? AND user_id = ? AND tier = ?",
                    (agent_id, user_id, tier),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COALESCE(SUM(LENGTH(content)), 0) as total FROM agent_memories WHERE agent_id = ? AND user_id = ?",
                    (agent_id, user_id),
                ).fetchone()
            return row["total"] if row else 0


    def increment_agent_memory_access(self, memory_id: str) -> bool:
        """原子递增记忆访问次数并更新最后访问时间。"""
        sql = """UPDATE agent_memories
                 SET access_count = access_count + 1,
                     accessed_at = datetime('now','localtime')
                 WHERE id = ?"""
        self._execute_write(sql, (memory_id,))
        return True


    def get_agent_memory_by_id(self, memory_id: str) -> dict | None:
        """按 ID 查询单条分级记忆。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute("SELECT * FROM agent_memories WHERE id = ?", (memory_id,)).fetchone()
            )


    def create_memory_relation(self, agent_id: str, user_id: str,
                               entity: str, relation: str, target: str) -> str:
        """创建一条关系三元组，返回 ID。"""
        rid = self._new_id()
        sql = """INSERT INTO memory_relations (id, agent_id, user_id, entity, relation, target)
                 VALUES (?, ?, ?, ?, ?, ?)"""
        self._execute_write(sql, (rid, agent_id, user_id, entity, relation, target))
        return rid


    def search_memory_relations_by_entity(self, agent_id: str, user_id: str,
                                          entity: str) -> list:
        """按实体名查询所有关联的关系。"""
        with self.conn() as conn:
            rows = conn.execute(
                """SELECT * FROM memory_relations
                   WHERE agent_id = ? AND user_id = ? AND entity LIKE ?
                   ORDER BY created_at DESC""",
                (agent_id, user_id, f"%{entity}%"),
            ).fetchall()
            return [dict(r) for r in rows]


    def search_memory_relations_by_relation(self, agent_id: str, user_id: str,
                                            relation: str) -> list:
        """按关系类型查询（如 '职业'）。"""
        with self.conn() as conn:
            rows = conn.execute(
                """SELECT * FROM memory_relations
                   WHERE agent_id = ? AND user_id = ? AND relation LIKE ?
                   ORDER BY created_at DESC""",
                (agent_id, user_id, f"%{relation}%"),
            ).fetchall()
            return [dict(r) for r in rows]


    def search_memory_relations_by_target(self, agent_id: str, user_id: str,
                                          target: str) -> list:
        """按目标值查询（如 '会计'）。"""
        with self.conn() as conn:
            rows = conn.execute(
                """SELECT * FROM memory_relations
                   WHERE agent_id = ? AND user_id = ? AND target LIKE ?
                   ORDER BY created_at DESC""",
                (agent_id, user_id, f"%{target}%"),
            ).fetchall()
            return [dict(r) for r in rows]


    def search_memory_relations_all(self, agent_id: str, user_id: str,
                                    keyword: str) -> list:
        """按关键词搜索所有关系字段（entity/relation/target）。"""
        with self.conn() as conn:
            rows = conn.execute(
                """SELECT * FROM memory_relations
                   WHERE agent_id = ? AND user_id = ?
                   AND (entity LIKE ? OR relation LIKE ? OR target LIKE ?)
                   ORDER BY created_at DESC""",
                (agent_id, user_id, f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"),
            ).fetchall()
            return [dict(r) for r in rows]


    def delete_memory_relation(self, relation_id: str) -> bool:
        """按 ID 删除关系。"""
        self._execute_write("DELETE FROM memory_relations WHERE id = ?", (relation_id,))
        return True


    def list_memory_relations(self, agent_id: str, user_id: str,
                              limit: int = 100) -> list:
        """列出某 agent 对某用户的所有关系。"""
        with self.conn() as conn:
            rows = conn.execute(
                """SELECT * FROM memory_relations
                   WHERE agent_id = ? AND user_id = ?
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (agent_id, user_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]


    def create_memory(self, agent_id: str, user_id: str, key: str,
                      value: str, source: str = "",
                      confidence: int = 1) -> str:
        """创建或更新一条 AI 记忆，返回记忆 ID。

        如果同 agent_id + user_id + key 已存在，则更新 value 和 confidence。
        """
        mid = self._new_id()
        sql = """INSERT INTO ai_memories (id, agent_id, user_id, key, value, source, confidence)
                 VALUES (?, ?, ?, ?, ?, ?, ?)
                 ON CONFLICT(id) DO NOTHING"""
        existing = self.get_memory_by_key(agent_id, user_id, key)
        if existing:
            self.update_memory(existing["id"], value=value, confidence=confidence, source=source)
            return existing["id"]
        self._execute_write(sql, (mid, agent_id, user_id, key, value, source, confidence))
        return mid


    def get_memory(self, memory_id: str):
        """按 ID 查询记忆。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute("SELECT * FROM ai_memories WHERE id = ?", (memory_id,)).fetchone()
            )


    def get_memory_by_key(self, agent_id: str, user_id: str, key: str):
        """按 agent_id + user_id + key 查询记忆。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute(
                    "SELECT * FROM ai_memories WHERE agent_id = ? AND user_id = ? AND key = ?",
                    (agent_id, user_id, key),
                ).fetchone()
            )


    def list_memories(self, agent_id: str, user_id: str) -> list:
        """列出某 agent 对某用户的所有记忆。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM ai_memories WHERE agent_id = ? AND user_id = ? ORDER BY updated_at DESC",
                (agent_id, user_id),
            ).fetchall()
            return [dict(r) for r in rows]


    def update_memory(self, memory_id: str, **kwargs) -> bool:
        """按 ID 更新记忆字段。"""
        if not kwargs:
            return False
        kwargs["updated_at"] = "datetime('now','localtime')"
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        sql = f"UPDATE ai_memories SET {sets} WHERE id = ?"
        params = tuple(kwargs.values()) + (memory_id,)
        self._execute_write(sql, params)
        return True


    def delete_memory(self, memory_id: str) -> bool:
        """按 ID 删除记忆。"""
        self._execute_write("DELETE FROM ai_memories WHERE id = ?", (memory_id,))
        return True


    def search_memories(self, agent_id: str, user_id: str, keyword: str) -> list:
        """按关键词搜索记忆。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM ai_memories WHERE agent_id = ? AND user_id = ? AND (key LIKE ? OR value LIKE ?) ORDER BY confidence DESC, updated_at DESC",
                (agent_id, user_id, f"%{keyword}%", f"%{keyword}%"),
            ).fetchall()
            return [dict(r) for r in rows]

