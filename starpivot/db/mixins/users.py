"""StarPivot Engine - Database users mixin"""
import sqlite3
import uuid
import json
import time
import os
from datetime import datetime, timedelta
from typing import Any, Optional


class UsersMixin:
    """Mixin providing users-related database operations."""
    
    # All methods in this mixin access self.conn, self._execute_write, etc.
    # from the parent Database class.
    
    def create_user(self, username: str, password_hash: str,
                    balance_cents: float = 0.0, is_admin: int = 0) -> str:
        """创建用户，返回新用户 ID。"""
        uid = self._generate_id("ZH")
        sql = """INSERT INTO users (id, username, password_hash, balance_cents, is_admin)
                 VALUES (?, ?, ?, ?, ?)"""
        self._execute_write(sql, (uid, username, password_hash, balance_cents, is_admin))
        return uid


    def get_user(self, user_id: str):
        """按 ID 查询用户，返回 sqlite3.Row 或 None。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            )


    def get_user_by_username(self, username: str):
        """按用户名查询用户。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            )


    def list_users(self, limit: int = 100, offset: int = 0):
        """分页列出用户。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM users ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]


    def update_user(self, user_id: str, **kwargs) -> bool:
        """按 ID 更新用户字段。返回是否成功。"""
        if not kwargs:
            return False
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        sql = f"UPDATE users SET {sets} WHERE id = ?"
        params = tuple(kwargs.values()) + (user_id,)
        self._execute_write(sql, params)
        return True


    def delete_user(self, user_id: str) -> bool:
        """按 ID 删除用户。"""
        self._execute_write("DELETE FROM users WHERE id = ?", (user_id,))
        return True


    def upsert_user_profile(self, user_id: str, company_name: str = "",
                            industry: str = "", role: str = "",
                            preferences: str = "", notes: str = "") -> bool:
        """创建或更新用户画像。"""
        sql = """INSERT INTO user_profiles (user_id, company_name, industry, role, preferences, notes, updated_at)
                 VALUES (?, ?, ?, ?, ?, ?, datetime('now','localtime'))
                 ON CONFLICT(user_id) DO UPDATE SET
                     company_name = excluded.company_name,
                     industry = excluded.industry,
                     role = excluded.role,
                     preferences = excluded.preferences,
                     notes = excluded.notes,
                     updated_at = datetime('now','localtime')"""
        self._execute_write(sql, (user_id, company_name, industry, role, preferences, notes))
        return True


    def get_user_profile(self, user_id: str):
        """获取用户画像，不存在则返回空 dict。"""
        with self.conn() as conn:
            row = self._row_to_dict(
                conn.execute("SELECT * FROM user_profiles WHERE user_id = ?", (user_id,)).fetchone()
            )
            if row:
                return row
            return {"user_id": user_id, "company_name": "", "industry": "",
                    "role": "", "preferences": "", "notes": ""}


    def save_user_output(self, user_id: str, agent_id: str,
                         title: str = "", content: str = "") -> str:
        """保存 AI 产出物，返回记录 ID。"""
        oid = self._new_id()
        self._execute_write(
            "INSERT INTO user_outputs (id, user_id, agent_id, title, content) VALUES (?, ?, ?, ?, ?)",
            (oid, user_id, agent_id, title, content)
        )
        return oid


    def list_user_outputs(self, user_id: str, limit: int = 50, offset: int = 0):
        """列出用户的所有产出物，按时间倒序。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM user_outputs WHERE user_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (user_id, limit, offset)
            ).fetchall()
            return [dict(r) for r in rows]

