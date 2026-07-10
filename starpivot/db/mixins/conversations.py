"""StarPivot Engine - Database conversations mixin"""
import sqlite3
import uuid
import json
import time
import os
from datetime import datetime, timedelta
from typing import Any, Optional


class ConversationsMixin:
    """Mixin providing conversations-related database operations."""
    
    # All methods in this mixin access self.conn, self._execute_write, etc.
    # from the parent Database class.
    
    def create_conversation(self, agent_id: str, user_id: str,
                            summary: str = "", key_points: str = "") -> str:
        """创建一条对话记录，返回对话 ID。"""
        cid = self._new_id()
        sql = """INSERT INTO ai_conversations (id, agent_id, user_id, summary, key_points)
                 VALUES (?, ?, ?, ?, ?)"""
        self._execute_write(sql, (cid, agent_id, user_id, summary, key_points))
        return cid


    def get_conversation(self, conversation_id: str):
        """按 ID 查询对话记录。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute("SELECT * FROM ai_conversations WHERE id = ?", (conversation_id,)).fetchone()
            )


    def list_conversations(self, agent_id: str, user_id: str, limit: int = 20) -> list:
        """列出某 agent 和某用户的最近对话记录。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM ai_conversations WHERE agent_id = ? AND user_id = ? ORDER BY started_at DESC LIMIT ?",
                (agent_id, user_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]


    def update_conversation(self, conversation_id: str, **kwargs) -> bool:
        """按 ID 更新对话记录。"""
        if not kwargs:
            return False
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        sql = f"UPDATE ai_conversations SET {sets} WHERE id = ?"
        params = tuple(kwargs.values()) + (conversation_id,)
        self._execute_write(sql, params)
        return True


    def finish_conversation(self, conversation_id: str, summary: str = "",
                            key_points: str = "") -> bool:
        """结束对话：设置 ended_at、summary、key_points。"""
        sql = """UPDATE ai_conversations SET
                 ended_at = datetime('now','localtime'),
                 summary = ?,
                 key_points = ?
                 WHERE id = ?"""
        self._execute_write(sql, (summary, key_points, conversation_id))
        return True


    def create_message(self, agent_id: str, role: str, content: str = "",
                       turn_seq: int = 0) -> int:
        """创建消息记录，返回消息 ID（自增）。"""
        sql = """INSERT INTO messages (agent_id, role, content, turn_seq)
                 VALUES (?, ?, ?, ?)"""
        cursor = self._execute_write(sql, (agent_id, role, content, turn_seq))
        return cursor.lastrowid


    def get_message(self, msg_id):
        """按 ID 查询消息。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute(
                    "SELECT * FROM messages WHERE id = ?", (msg_id,)
                ).fetchone()
            )


    def list_messages_by_agent(self, agent_id: str, limit: int = 100, offset: int = 0):
        """列出某 Agent 对话的消息（按时间倒序）。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE agent_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (agent_id, limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]


    def delete_message(self, msg_id: int) -> bool:
        """按 ID 删除消息。"""
        self._execute_write("DELETE FROM messages WHERE id = ?", (int(msg_id),))
        return True

