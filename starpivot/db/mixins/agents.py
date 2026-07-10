"""StarPivot Engine - Database agents mixin"""
import sqlite3
import uuid
import json
import time
import os
from datetime import datetime, timedelta
from typing import Any, Optional


class AgentsMixin:
    """Mixin providing agents-related database operations."""
    
    # All methods in this mixin access self.conn, self._execute_write, etc.
    # from the parent Database class.
    
    def create_agent(self, user_id: str, name: str, system_prompt: str = "",
                     tier: str = "一级", status: str = "running",
                     balance_cents: float | None = None,
                     is_system: int = 0,
                     api_provider: str = "",
                     api_key: str = "",
                     api_model: str = "") -> str:
        """创建 Agent，返回新 Agent ID。"""
        aid = self._generate_id("AI")
        balance_cents = balance_cents if balance_cents is not None else settings.starting_credits
        sql = """INSERT INTO agents (id, user_id, name, system_prompt, tier, status, balance_cents, is_system, api_provider, api_key, api_model)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        self._execute_write(sql, (aid, user_id, name, system_prompt, tier, status, balance_cents, is_system, api_provider, api_key, api_model))
        return aid


    def create_system_agent(self, st_id: str, user_id: str, name: str,
                            system_prompt: str = "",
                            balance_cents: float = 1000.0) -> str:
        """创建系统内置管理 Agent，使用 ST 前缀 ID。

        Args:
            st_id: 系统 Agent ID（如 'ST01', 'ST02' 等）。
            user_id: 关联的用户 ID。
            name: Agent 名称。
            system_prompt: 系统提示词/职责描述。
            balance_cents: 初始积分余额（默认 1000）。

        Returns:
            创建的 Agent ID。
        """
        sql = """INSERT OR IGNORE INTO agents
                 (id, user_id, name, system_prompt, tier, status, balance_cents, is_system)
                 VALUES (?, ?, ?, ?, 'admin', 'paused', ?, 1)"""
        self._execute_write(sql, (st_id, user_id, name, system_prompt, balance_cents))
        return st_id


    def get_agent(self, agent_id: str):
        """按 ID 查询 Agent。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
            )


    def list_agents_by_user(self, user_id: str):
        """列出某用户的所有 Agent。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM agents WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
            return [dict(r) for r in rows]


    def list_agents(self, limit: int = 100, offset: int = 0):
        """分页列出所有 Agent。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM agents ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]


    def list_agents_for_sale(self):
        """列出所有待售的 AI 智能体（for_sale_price 不为空）。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT a.*, u.username as owner_name FROM agents a LEFT JOIN users u ON a.user_id=u.id WHERE a.for_sale_price IS NOT NULL AND a.is_system=0 ORDER BY a.for_sale_price ASC"
            ).fetchall()
            return [dict(r) for r in rows]


    def list_agents_for_rent(self):
        """列出所有可租的 AI 智能体（for_rent_price 不为空）。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT a.*, u.username as owner_name FROM agents a LEFT JOIN users u ON a.user_id=u.id WHERE a.for_rent_price IS NOT NULL AND a.is_system=0 ORDER BY a.for_rent_price ASC"
            ).fetchall()
            return [dict(r) for r in rows]


    def update_agent(self, agent_id: str, **kwargs) -> bool:
        """按 ID 更新 Agent 字段。"""
        if not kwargs:
            return False
        if "updated_at" not in kwargs:
            kwargs["updated_at"] = "datetime('now','localtime')"
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        sql = f"UPDATE agents SET {sets} WHERE id = ?"
        params = tuple(kwargs.values()) + (agent_id,)
        self._execute_write(sql, params)
        return True


    def delete_agent(self, agent_id: str) -> bool:
        """按 ID 删除 Agent。"""
        self._execute_write("DELETE FROM agents WHERE id = ?", (agent_id,))
        return True


    def create_agent_skill(self, agent_id: str, skill_id: str,
                           source: str = "gift",
                           is_equipped: int = 1) -> str:
        """为Agent添加一个技能，返回记录ID。"""
        sid = self._new_id()
        sql = """INSERT INTO agent_skills (id, agent_id, skill_id, source, is_equipped)
                 VALUES (?, ?, ?, ?, ?)"""
        self._execute_write(sql, (sid, agent_id, skill_id, source, is_equipped))
        return sid


    def get_agent_skills(self, agent_id: str,
                         equipped_only: bool = False) -> list[dict]:
        """获取Agent拥有的技能列表。

        Args:
            agent_id: Agent ID。
            equipped_only: 如果为True，只返回已装备的技能。

        Returns:
            技能记录字典列表（含技能详情，从registry获取）。
        """
        from core.skills.registry import SKILLS
        with self.conn() as conn:
            if equipped_only:
                rows = conn.execute(
                    "SELECT * FROM agent_skills WHERE agent_id = ? AND is_equipped = 1 ORDER BY acquired_at DESC",
                    (agent_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM agent_skills WHERE agent_id = ? ORDER BY acquired_at DESC",
                    (agent_id,),
                ).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                # 附加技能详情
                skill_info = SKILLS.get(d["skill_id"])
                if skill_info:
                    d["skill_name"] = skill_info["name"]
                    d["star_level"] = skill_info["star_level"]
                    d["category"] = skill_info["category"]
                    d["description"] = skill_info["description"]
                results.append(d)
            return results


    def get_agent_skill_ids(self, agent_id: str,
                            equipped_only: bool = False) -> list[str]:
        """获取Agent拥有的技能ID列表。"""
        with self.conn() as conn:
            if equipped_only:
                rows = conn.execute(
                    "SELECT skill_id FROM agent_skills WHERE agent_id = ? AND is_equipped = 1",
                    (agent_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT skill_id FROM agent_skills WHERE agent_id = ?",
                    (agent_id,),
                ).fetchall()
            return [r["skill_id"] for r in rows]


    def delete_agent_skill(self, agent_id: str, skill_id: str) -> bool:
        """删除Agent的某个技能记录。"""
        self._execute_write(
            "DELETE FROM agent_skills WHERE agent_id = ? AND skill_id = ?",
            (agent_id, skill_id),
        )
        return True


    def update_agent_skill_equipped(self, agent_id: str, skill_id: str,
                                    is_equipped: int) -> bool:
        """更新Agent技能的装备状态。"""
        self._execute_write(
            "UPDATE agent_skills SET is_equipped = ? WHERE agent_id = ? AND skill_id = ?",
            (is_equipped, agent_id, skill_id),
        )
        return True


    def has_agent_skill(self, agent_id: str, skill_id: str) -> bool:
        """检查Agent是否拥有某个技能。"""
        with self.conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM agent_skills WHERE agent_id = ? AND skill_id = ?",
                (agent_id, skill_id),
            ).fetchone()
            return row is not None


    def count_agent_skills(self, agent_id: str) -> int:
        """统计Agent拥有的技能数量。"""
        with self.conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM agent_skills WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
            return row["cnt"] if row else 0


    def list_agents_by_skill(self, skill_id: str) -> list[str]:
        """列出拥有指定技能的所有Agent ID。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT agent_id FROM agent_skills WHERE skill_id = ?",
                (skill_id,),
            ).fetchall()
            return [r["agent_id"] for r in rows]



    def get_agent_soul(self, agent_id: str):
        """按 agent_id 查询 SOUL.md 记录。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute("SELECT * FROM agent_souls WHERE agent_id = ?", (agent_id,)).fetchone()
            )


    def upsert_agent_soul(self, agent_id: str, content: str = "",
                          ironclad_rules: str = "") -> bool:
        """创建或更新 SOUL.md 记录。返回是否成功。"""
        existing = self.get_agent_soul(agent_id)
        if existing:
            sql = """UPDATE agent_souls SET
                     content = ?, ironclad_rules = ?,
                     version = version + 1,
                     updated_at = datetime('now','localtime')
                     WHERE agent_id = ?"""
            self._execute_write(sql, (content, ironclad_rules, agent_id))
        else:
            sql = """INSERT INTO agent_souls (agent_id, content, ironclad_rules)
                     VALUES (?, ?, ?)"""
            self._execute_write(sql, (agent_id, content, ironclad_rules))
        return True


    def update_agent_soul_content(self, agent_id: str, content: str) -> bool:
        """仅更新 SOUL.md 正文内容。"""
        sql = """UPDATE agent_souls SET content = ?, version = version + 1,
                 updated_at = datetime('now','localtime') WHERE agent_id = ?"""
        self._execute_write(sql, (content, agent_id))
        return True


    def update_agent_soul_ironclad(self, agent_id: str, rules: str) -> bool:
        """仅更新铁律（用户专属，AI 不可修改）。"""
        sql = """UPDATE agent_souls SET ironclad_rules = ?,
                 updated_at = datetime('now','localtime') WHERE agent_id = ?"""
        self._execute_write(sql, (rules, agent_id))
        return True

