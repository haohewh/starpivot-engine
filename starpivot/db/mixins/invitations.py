"""StarPivot Engine - Database invitations mixin"""
import sqlite3
import uuid
import json
import time
import os
from datetime import datetime, timedelta
from typing import Any, Optional


class InvitationsMixin:
    """Mixin providing invitations-related database operations."""
    
    # All methods in this mixin access self.conn, self._execute_write, etc.
    # from the parent Database class.
    
    def generate_invitation_code(self) -> str:
        """生成唯一的 YQ+12位随机邀请码"""
        chars = string.ascii_letters + string.digits
        while True:
            code = "YQ" + ''.join(random.choices(chars, k=12))
            # 检查是否已存在
            existing = self.get_invitation_code(code)
            if existing is None:
                break
        return code


    def create_invitation_code(self, owner_id: str) -> str:
        """为用户创建邀请码，返回邀请码字符串"""
        code = self.generate_invitation_code()
        self._execute_write(
            "INSERT INTO invitation_codes (code, owner_id) VALUES (?, ?)",
            (code, owner_id),
        )
        return code


    def get_invitation_code(self, code: str):
        """按邀请码查询"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute(
                    "SELECT * FROM invitation_codes WHERE code = ?", (code,)
                ).fetchone()
            )


    def get_user_invitation_code(self, user_id: str):
        """查某个用户的邀请码"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute(
                    "SELECT * FROM invitation_codes WHERE owner_id = ? ORDER BY created_at DESC LIMIT 1",
                    (user_id,),
                ).fetchone()
            )


    def increment_invitation_use(self, code: str) -> None:
        """邀请码使用次数+1"""
        self._execute_write(
            "UPDATE invitation_codes SET use_count = use_count + 1 WHERE code = ?",
            (code,),
        )


    def record_invitation_use(self, code: str, inviter_id: str,
                              invitee_id: str) -> int:
        """记录邀请使用，返回记录ID"""
        with self._lock:
            with self.conn() as conn:
                conn.execute(
                    "INSERT INTO invitation_uses (code, inviter_id, invitee_id, bonus_given) VALUES (?, ?, ?, 1)",
                    (code, inviter_id, invitee_id),
                )
                return conn.lastrowid


    def get_invitation_stats(self) -> dict:
        """管理员查看邀请统计"""
        with self.conn() as conn:
            total_codes = conn.execute(
                "SELECT COUNT(*) FROM invitation_codes"
            ).fetchone()[0]
            total_uses = conn.execute(
                "SELECT COUNT(*) FROM invitation_uses"
            ).fetchone()[0]
            total_invitees = conn.execute(
                "SELECT COUNT(DISTINCT invitee_id) FROM invitation_uses"
            ).fetchone()[0]
            recent_uses = conn.execute(
                "SELECT iu.*, ic.owner_id as code_owner_id FROM invitation_uses iu "
                "LEFT JOIN invitation_codes ic ON iu.code = ic.code "
                "ORDER BY iu.created_at DESC LIMIT 20"
            ).fetchall()
        return {
            "total_codes": total_codes,
            "total_uses": total_uses,
            "total_invitees": total_invitees,
            "recent_uses": [dict(r) for r in recent_uses],
        }

