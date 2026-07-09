"""
星枢 AI — SOUL.md 管理系统

SOUL.md 是 AI 的核心人格定义文件，地位高于 system_prompt。
铁律（ironclad_rules）由用户写入，AI 不可修改，优先级最高。

合成提示词顺序（在 _build_system_prompt 中使用）：
  1. 【铁律（锁死，用户写）】
  2. 【SOUL.md 正文（≥5000 字，定义角色身份）】
  3. 【用户编辑的提示词（可选补充）】
  4. 【工具感知（自动生成）】
  5. 【记忆注入（自动生成）】
"""

import logging
from typing import Any, Dict, Optional

from store.db import get_db

logger = logging.getLogger(__name__)

# ── SOUL.md 最小长度要求 ────────────────────────────────────────
_SOUL_MIN_CHARS = 5000


class SoulManager:
    """SOUL.md 管理类。

    功能：
      - get_soul(agent_id)           → 返回 soul_content + ironclad_rules
      - set_soul(agent_id, content)  → 更新/创建 SOUL.md
      - set_ironclad(agent_id, rules) → 设置铁律
      - compose_prompt(agent_id, user_edits, memory_block)
        → 合成完整提示词
    """

    def __init__(self):
        self._db = get_db()

    # ── 读取 ──────────────────────────────────────────────────

    def get_soul(self, agent_id: str) -> Dict[str, Any]:
        """获取 Agent 的 SOUL.md 记录。

        Returns:
            dict: {
                "agent_id": str,
                "content": str,          # SOUL.md 正文
                "ironclad_rules": str,   # 铁律
                "version": int,
                "created_at": str,
                "updated_at": str,
            }
            如果不存在返回空字典。
        """
        row = self._db.get_agent_soul(agent_id)
        if row:
            return dict(row)
        return {
            "agent_id": agent_id,
            "content": "",
            "ironclad_rules": "",
            "version": 0,
        }

    def get_soul_content(self, agent_id: str) -> str:
        """仅获取 SOUL.md 正文。"""
        row = self._db.get_agent_soul(agent_id)
        return row["content"] if row else ""

    def get_ironclad(self, agent_id: str) -> str:
        """仅获取铁律。"""
        row = self._db.get_agent_soul(agent_id)
        return row["ironclad_rules"] if row else ""

    # ── 写入 ──────────────────────────────────────────────────

    def set_soul(self, agent_id: str, content: str) -> bool:
        """设置/更新 SOUL.md 正文。

        Args:
            agent_id: Agent ID。
            content: SOUL.md 正文（建议 ≥5000 字符）。

        Returns:
            是否成功。
        """
        return self._db.upsert_agent_soul(agent_id, content=content)

    def set_ironclad(self, agent_id: str, rules: str) -> bool:
        """设置铁律（用户写入，AI 不可修改）。

        Args:
            agent_id: Agent ID。
            rules: 铁律文本。

        Returns:
            是否成功。
        """
        return self._db.update_agent_soul_ironclad(agent_id, rules)

    # ── 提示词合成 ────────────────────────────────────────────

    def compose_prompt(
        self,
        agent_id: str,
        user_edits: str = "",
        memory_block: str = "",
        tool_awareness: str = "",
    ) -> str:
        """合成完整系统提示词。

        合成顺序（从最不可覆盖到最可补充）：
          1. 铁律（锁死，优先级最高，AI 不可反驳）
          2. SOUL.md 正文（定义角色身份）
          3. 用户编辑的提示词（可补充不可覆盖）
          4. 工具感知（自动生成）
          5. 记忆注入（自动生成）

        Args:
            agent_id:     Agent ID。
            user_edits:   用户手动编辑的补充提示词。
            memory_block: 注入的记忆块（热记忆 + 温记忆）。
            tool_awareness: 工具感知文本。

        Returns:
            合成后的完整 system_prompt。
        """
        soul = self.get_soul(agent_id)
        ironclad = (soul.get("ironclad_rules") or "").strip()
        soul_content = (soul.get("content") or "").strip()

        parts = []

        # ── 1. 铁律（锁死） ──
        if ironclad:
            parts.append(f"【铁律 — 不可违反，优先级最高】\n{ironclad}\n")

        # ── 2. SOUL.md 正文 ──
        if soul_content:
            parts.append(f"【底层人格 — 不可更改】\n{soul_content}\n")
        else:
            parts.append("【底层人格 — 未设定】\n（你是一个通用 AI Agent，没有特殊的角色设定。）\n")

        # ── 3. 用户编辑的提示词 ──
        if user_edits:
            parts.append(f"【用户补充设定】\n{user_edits}\n")

        # ── 4. 工具感知 ──
        if tool_awareness:
            parts.append(tool_awareness)

        # ── 5. 记忆注入 ──
        if memory_block:
            parts.append(memory_block)

        return "\n".join(parts)
