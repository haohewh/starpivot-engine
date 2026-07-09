"""
星枢 AI 持久记忆 / 跨会话上下文 — AgentMemory 类

功能：
  1. remember()       — 保存单条记忆（自动去重/更新）
  2. recall()          — 检索记忆（全部或按 key）
  3. search_memories() — 按关键词搜索历史记忆
  4. summarize_conversation() — 自动提取会话摘要并存储
  5. inject_memories() — 将相关记忆注入 system_prompt
  6. list_conversations() — 列出历史会话
"""

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from store.db import get_db

logger = logging.getLogger(__name__)

# ── 可自动提取的记忆模式 ────────────────────────────────────────
_MEMORY_PATTERNS = [
    # "我叫张三" / "我是张三"
    (r"(?:我(?:叫|是))(\S{2,8})(?=[，,。.\s]|$)", "user_name"),
    # "我是做计算机的" / "我是程序员" / "我是一名教师"
    (r"(?:我(?:是|是一名?)(?:做|干|搞)?)(\S{2,10}(?:的)?(?:工作|行业|职业)?)(?=[，,。.\s]|$)", "occupation"),
    # "我喜欢简洁的风格" / "我喜欢红色"
    (r"(?:我(?:喜欢|偏好|习惯)(?:于)?)(\S{2,20}(?:风格|颜色|样式|方式)?)(?=[，,。.\s]|$)", "preference"),
    # "叫我老王就行" / "叫我阿星"
    (r"(?:叫[我]?)(\S{2,8})(?:就行|就好|吧|即可)?(?=[，,。.\s]|$)", "nickname"),
]


class AgentMemory:
    """AI 持久记忆管理器。

    封装 store/db.py 中 ai_memories / ai_conversations 表的操作，
    并提供注入 system_prompt 的高层接口。
    """

    def __init__(self, agent_id: str, user_id: str):
        self.agent_id = agent_id
        self.user_id = user_id
        self._db = get_db()

    # ── 记忆存取 ──────────────────────────────────────────────

    def remember(self, key: str, value: str, source: str = "",
                 confidence: int = 1) -> str:
        """保存一条记忆（自动 upsert）。"""
        return self._db.create_memory(
            agent_id=self.agent_id,
            user_id=self.user_id,
            key=key,
            value=value,
            source=source,
            confidence=confidence,
        )

    def recall(self, key: Optional[str] = None) -> List[Dict[str, Any]]:
        """检索记忆。

        Args:
            key: 记忆类型（user_name / preference / occupation / fact 等）。
                 为 None 时返回所有记忆。

        Returns:
            记忆字典列表。
        """
        if key:
            row = self._db.get_memory_by_key(self.agent_id, self.user_id, key)
            return [row] if row else []
        return self._db.list_memories(self.agent_id, self.user_id)

    def search(self, keyword: str) -> List[Dict[str, Any]]:
        """按关键词搜索记忆。"""
        return self._db.search_memories(self.agent_id, self.user_id, keyword)

    def forget(self, key: str) -> bool:
        """按 key 删除记忆。"""
        row = self._db.get_memory_by_key(self.agent_id, self.user_id, key)
        if row:
            self._db.delete_memory(row["id"])
            return True
        return False

    # ── 注入 system_prompt ────────────────────────────────────

    def inject_memories(self, system_prompt: str) -> str:
        """将相关记忆注入系统提示词，返回增强后的 system_prompt。

        用法（在 agent_loop.py 中）：
            system_prompt = agent_memory.inject_memories(system_prompt)
        """
        memories = self._db.list_memories(self.agent_id, self.user_id)
        if not memories:
            return system_prompt

        # 格式化记忆文本
        lines = []
        for m in memories:
            key_label = {
                "user_name": "用户姓名",
                "nickname": "用户昵称/称呼",
                "occupation": "用户职业/行业",
                "preference": "用户偏好",
                "fact": "用户相关事实",
            }.get(m["key"], m["key"])
            lines.append(f"  - {key_label}：{m['value']}")

        memory_block = (
            "\n\n【跨会话记忆 — 以下是你对这个用户已知的信息】\n"
            + "\n".join(lines)
            + "\n（这些是你在之前会话中了解到的信息，请据此提供更个性化的服务）\n"
        )

        return system_prompt + memory_block

    # ── 对话总结 ──────────────────────────────────────────────

    def summarize_conversation(self, messages: List[Dict[str, str]],
                               conversation_id: Optional[str] = None) -> str:
        """自动总结刚刚结束的对话。

        流程：
          1. 调用 LLM 提取摘要和关键信息
          2. 保存到 ai_conversations 表
          3. 从用户消息中自动提取可记住的信息（姓名/偏好/职业等）

        Args:
            messages: 本轮对话的完整消息列表（含 system/user/assistant）。
            conversation_id: 已有对话 ID（否则新建）。

        Returns:
            对话记录 ID。
        """
        # 过滤出 user 和 assistant 消息
        chat_messages = [
            m for m in messages
            if m.get("role") in ("user", "assistant")
        ]

        if not chat_messages:
            return conversation_id or ""

        # 提取用户消息文本
        user_texts = [
            m["content"] for m in chat_messages
            if m["role"] == "user" and m.get("content")
        ]
        full_user_text = "\n".join(user_texts)

        # ── 自动提取可记住的信息 ──
        self._auto_extract_memories(full_user_text)

        # ── 生成摘要（简单拼接前几条消息） ──
        # 保持轻量：用用户的前 2 条消息做摘要
        key_points_lines = []
        for m in chat_messages[:6]:
            prefix = "用户" if m["role"] == "user" else "助手"
            content = m["content"][:100] if m.get("content") else ""
            key_points_lines.append(f"[{prefix}] {content}")

        key_points = "\n".join(key_points_lines)
        summary = full_user_text[:200] if full_user_text else "(空对话)"

        # ── 保存 ──
        if conversation_id:
            self._db.finish_conversation(
                conversation_id, summary=summary, key_points=key_points,
            )
        else:
            conversation_id = self._db.create_conversation(
                self.agent_id, self.user_id, summary=summary, key_points=key_points,
            )

        logger.info(
            "Agent %s 对话已总结: %s (%d 条消息)",
            self.agent_id, conversation_id, len(chat_messages),
        )
        return conversation_id

    def list_conversations(self, limit: int = 10) -> List[Dict[str, Any]]:
        """列出最近的历史对话记录。"""
        return self._db.list_conversations(self.agent_id, self.user_id, limit)

    def start_conversation(self) -> str:
        """显式开始一次新对话（返回对话 ID）。"""
        return self._db.create_conversation(self.agent_id, self.user_id)

    # ── 内部方法 ──────────────────────────────────────────────

    def _auto_extract_memories(self, text: str) -> int:
        """从用户文本中自动提取可记住的信息并保存。

        Returns:
            新增/更新的记忆数量。
        """
        count = 0
        for pattern, key in _MEMORY_PATTERNS:
            match = re.search(pattern, text)
            if match:
                value = match.group(1).strip()
                existing = self._db.get_memory_by_key(self.agent_id, self.user_id, key)
                if existing and existing["value"] == value:
                    continue  # 已存在且相同，跳过
                self._db.create_memory(
                    agent_id=self.agent_id,
                    user_id=self.user_id,
                    key=key,
                    value=value,
                    source=f"auto_extract_{key}",
                    confidence=3,
                )
                count += 1
                logger.info("自动提取记忆 [%s] = %s", key, value)
        return count
