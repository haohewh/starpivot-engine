"""StarPivot Engine - Database audit mixin"""
import sqlite3
import uuid
import json
import time
import os
from datetime import datetime, timedelta
from typing import Any, Optional


class AuditMixin:
    """Mixin providing audit-related database operations."""
    
    # All methods in this mixin access self.conn, self._execute_write, etc.
    # from the parent Database class.
    
    def create_audit_log(self, agent_id: str, action: str, detail: str = "") -> int:
        """创建审计日志，返回日志 ID（自增）。"""
        sql = """INSERT INTO audit_log (agent_id, action, detail)
                 VALUES (?, ?, ?)"""
        cursor = self._execute_write(sql, (agent_id, action, detail))
        return cursor.lastrowid


    def get_audit_log(self, log_id):
        """按 ID 查询审计日志。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute(
                    "SELECT * FROM audit_log WHERE id = ?", (log_id,)
                ).fetchone()
            )


    def list_audit_logs_by_agent(self, agent_id: str, limit: int = 100, offset: int = 0):
        """列出某 Agent 的审计日志（按时间倒序）。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_log WHERE agent_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (agent_id, limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]


    def list_audit_logs(self, limit: int = 100, offset: int = 0):
        """分页列出所有审计日志。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_log ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]

