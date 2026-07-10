"""StarPivot Engine - Database services mixin"""
import sqlite3
import uuid
import json
import time
import os
from datetime import datetime, timedelta
from typing import Any, Optional


class ServicesMixin:
    """Mixin providing services-related database operations."""
    
    # All methods in this mixin access self.conn, self._execute_write, etc.
    # from the parent Database class.
    
    def create_service(self, agent_id: str, name: str, description: str = "",
                       price_cents: float = 0.0) -> str:
        """创建服务，返回新服务 ID。"""
        sid = self._short_id("FW")
        sql = """INSERT INTO services (id, agent_id, name, description, price_cents)
                 VALUES (?, ?, ?, ?, ?)"""
        self._execute_write(sql, (sid, agent_id, name, description, price_cents))
        return sid


    def get_service(self, service_id: str):
        """按 ID 查询服务。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute(
                    "SELECT * FROM services WHERE id = ?", (service_id,)
                ).fetchone()
            )


    def get_service_by_agent(self, agent_id: str):
        """按所属 Agent ID 查询服务列表。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM services WHERE agent_id = ? ORDER BY created_at DESC",
                (agent_id,),
            ).fetchall()
            return [dict(r) for r in rows]


    def list_services(self, status: Optional[str] = None,
                      limit: int = 100, offset: int = 0):
        """列出服务，可按状态过滤。"""
        with self.conn() as conn:
            conditions = []
            params = []
            if status:
                conditions.append("status = ?")
                params.append(status)
            where = " AND ".join(conditions) if conditions else "1=1"
            rows = conn.execute(
                f"SELECT * FROM services WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                tuple(params) + (limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]


    def update_service(self, service_id: str, **kwargs) -> bool:
        """按 ID 更新服务字段。"""
        if not kwargs:
            return False
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        sql = f"UPDATE services SET {sets} WHERE id = ?"
        params = tuple(kwargs.values()) + (service_id,)
        self._execute_write(sql, params)
        return True


    def delete_service(self, service_id: str) -> bool:
        """按 ID 删除服务。"""
        self._execute_write("DELETE FROM services WHERE id = ?", (service_id,))
        return True

