""""
星枢 AI — 三级记忆系统（融合 mem0 / letta / cognee / agentmemory / memvid / Memori）

三级记忆架构：
  - 热记忆（Tier 1）：最近 10 条对话记忆，每次对话自动注入 ~500 字
  - 温记忆（Tier 2）：用户重要信息（姓名、职业、偏好等），按重要度排序，注入 ~2000 字
  - 冷记忆（Tier 3）：历史对话总结，不自动注入，关键词检索后按需加载

融合六大 AI 记忆系统：
  - mem0 (⭐60k)：记忆重要性评分算法，根据访问频次+新鲜度+显式保存计算
  - letta (⭐24k)：结构化记忆注入，告别拼字符串
  - cognee (⭐26k)：关系图谱存储，存"关系"不存"文本"
  - agentmemory (⭐24k)：真实交互记忆持久化 + 自动摘要（auto_summarize）
  - memvid (⭐16k)：轻量记忆层替代复杂 RAG，按需检索
  - Memori (⭐15k)：模型无关的记忆基础设施 + 自动过期清理（cleanup_expired）

自动压缩阈值：
  - 记忆总字符 > 5000 时，将最久未访问的温记忆降级为冷记忆
"""

import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from store.db import get_db

logger = logging.getLogger(__name__)

# ── 压缩阈值 ────────────────────────────────────────────────────
_MAX_TOTAL_CHARS = 5000      # 超过此值触发降级
_MAX_HOT_COUNT = 10          # 热记忆最多保留条数
_MAX_WARM_CHARS = 2000       # 温记忆最大字符
_MAX_COLD_CHARS = 5000       # 冷记忆最大字符

# ── 自动提取记忆的正则模式 ─────────────────────────────────────
_MEMORY_PATTERNS = [
    # "我叫张三" / "我是张三"
    (r'(?:我(?:叫|是))(\S{2,8})(?=[，,。.\s]|$)', "user_name", "用户姓名"),
    # "我是做计算机的" / "我是程序员" / "我是一名教师"
    (r'(?:我(?:是|是一名?)(?:做|干|搞)?)(\S{2,10}(?:的)?(?:工作|行业|职业)?)(?=[，,。.\s]|$)', "occupation", "用户职业/行业"),
    # "我喜欢简洁的风格" / "我喜欢红色"
    (r'(?:我(?:喜欢|偏好|习惯)(?:于)?)(\S{2,20}(?:风格|颜色|样式|方式)?)(?=[，,。.\s]|$)', "preference", "用户偏好"),
    # "叫我老王就行" / "叫我阿星"
    (r'(?:叫[我]?)(\S{2,8})(?:就行|就好|吧|即可)?(?=[，,。.\s]|$)', "nickname", "用户昵称/称呼"),
    # "我今年25岁" / "我今年二十五岁"
    (r'(?:我今年|我)(\d{1,3}|[一二三四五六七八九十百千]+)\s*岁', "age", "用户年龄"),
    # "家在深圳" / "我住北京"
    (r'(?:家(?:在|住)|我住|我来自)(\S{2,10}(?:市|区|县|省)?)(?=[，,。.\s]|$)', "location", "用户所在地"),
]


def calculate_importance(
    access_count: int = 0,
    days_since_last_access: float = 999,
    is_explicit: bool = False,
    is_user_info: bool = False,
) -> float:
    """计算记忆重要性（mem0 算法）。

    Args:
        access_count:          访问频次。
        days_since_last_access: 距上次访问的天数。
        is_explicit:           是否用户明确保存的。
        is_user_info:          是否是用户个人信息（姓名/职业等）。

    Returns:
        重要性分数 0.0-1.0。
    """
    score = 0.5  # 基础分

    # 访问频次：每访问一次 +0.1，最多 +0.3
    score += min(access_count * 0.1, 0.3)

    # 新鲜度：最近 7 天内访问的 +0.2
    if days_since_last_access <= 7:
        score += 0.2

    # 用户明确保存
    if is_explicit:
        score += 0.3

    # 用户个人信息
    if is_user_info:
        score += 0.2

    return min(1.0, score)


class MemoryManager:
    """分级记忆管理器。

    融合 mem0 重要性评分、letta 结构化注入、cognee 关系图谱。

    功能：
      - memorize(content, importance, tier, keywords, source) → 保存记忆
      - recall(keywords) → 检索冷记忆
      - inject(system_prompt) → 结构化注入热记忆 + 温记忆 + 关系图谱
      - compress() → 降级 + 合并
      - extract_from_text(text) → 自动提取温记忆 + 关系图谱
    """

    def __init__(self, agent_id: str, user_id: str):
        self.agent_id = agent_id
        self.user_id = user_id
        self._db = get_db()
        self._relation_graph = None  # 惰性初始化

    @property
    def relation_graph(self):
        """惰性初始化关系图谱（避免循环导入）。"""
        if self._relation_graph is None:
            from core.starpivot.memory.relations import RelationGraph
            self._relation_graph = RelationGraph(self.agent_id, self.user_id)
        return self._relation_graph

    # ── 保存记忆 ──────────────────────────────────────────────

    def memorize(self, content: str, importance: float = 0.5,
                 tier: int = 1, keywords: str = "",
                 source: str = "", is_explicit: bool = False,
                 is_user_info: bool = False) -> str:
        """保存一条记忆到指定级别。

        如果未指定 importance，会自动使用 calculate_importance() 计算。

        Args:
            content:     记忆内容。
            importance:  重要度 0.0-1.0（仅 Tier 2/3 生效）。如果为 None 则自动计算。
            tier:        级别（1=热记忆，2=温记忆，3=冷记忆）。
            keywords:    关键词（用于冷记忆检索，逗号分隔）。
            source:      来源描述。
            is_explicit: 是否用户明确保存的（影响重要性评分）。
            is_user_info:是否是用户个人信息（影响重要性评分）。

        Returns:
            记忆 ID。
        """
        # 自动计算重要性
        final_importance = importance
        if tier > 1:
            final_importance = calculate_importance(
                access_count=0,
                days_since_last_access=0,
                is_explicit=is_explicit,
                is_user_info=is_user_info,
            )

        mid = self._db.create_agent_memory(
            agent_id=self.agent_id,
            user_id=self.user_id,
            content=content,
            tier=tier,
            keywords=keywords,
            importance=final_importance,
            source=source,
        )
        logger.debug("记忆已保存 [Tier %d, imp=%.2f] %s: %s",
                     tier, final_importance, source, content[:50])

        # 自动触发压缩检查
        self._auto_compress_if_needed()

        return mid

    # ── 检索冷记忆 ────────────────────────────────────────────

    def recall(self, keywords: str) -> List[Dict[str, Any]]:
        """按关键词检索冷记忆（Tier 3）。

        也会搜索 Tier 2 作为补充。同时更新访问计数。

        Args:
            keywords: 逗号分隔的关键词。

        Returns:
            匹配的记忆字典列表。
        """
        results = []
        seen_ids = set()

        # 逐个关键词搜索
        for kw in re.split(r'[,，\s]+', keywords.strip()):
            if not kw or len(kw) < 1:
                continue
            rows = self._db.search_agent_memories(
                self.agent_id, self.user_id, kw, limit=10,
            )
            for row in rows:
                if row["id"] not in seen_ids:
                    seen_ids.add(row["id"])
                    # 更新访问计数
                    self._db.increment_agent_memory_access(row["id"])
                    results.append(row)

        # 按重要度排序
        results.sort(key=lambda r: r["importance"], reverse=True)

        logger.info("冷记忆检索 '%s': 找到 %d 条", keywords, len(results))
        return results

    # ── 结构化注入记忆到 system_prompt（letta 风格） ──────────

    def inject(self, system_prompt: str = "") -> str:
        """将热记忆 + 温记忆 + 关系图谱结构化注入到 system_prompt 中。

        mem0 风格：每条记忆包含重要性评分。
        letta 风格：结构化 JSON 块，不再拼字符串。
        cognee 风格：关系图谱注入。

        Returns:
            格式化的记忆块（不含外层 system_prompt）。
        """
        parts = []

        # ── 1. 关系图谱注入（cognee模式） ──
        try:
            rel_block = self.relation_graph.format_as_inject_block()
            if rel_block:
                parts.append(rel_block)
        except Exception as e:
            logger.warning("关系图谱注入失败（非致命）: %s", e)

        # ── 2. 温记忆注入（letta风格 — 结构化块） ──
        warm = self._db.list_agent_memories_by_tier(
            self.agent_id, self.user_id, tier=2, limit=50,
        )
        if warm:
            # 按重要度排序
            warm_sorted = sorted(warm, key=lambda m: m["importance"], reverse=True)

            # 分组：用户基本信息 vs 其他
            user_info_lines = []
            recent_topic_lines = []
            preference_lines = []

            for m in warm_sorted:
                kw = (m.get("keywords") or "").lower()
                content = m["content"]
                imp = m["importance"]
                imp_tag = f"（重要度 {imp:.1f}）" if imp > 0.7 else ""

                if any(k in kw for k in ("user_name", "occupation", "age", "location", "nickname")):
                    user_info_lines.append(f"  {content}{imp_tag}")
                elif "preference" in kw:
                    preference_lines.append(f"  {content}{imp_tag}")
                else:
                    recent_topic_lines.append(f"  {content}{imp_tag}")

            # 结构化注入块（letta风格）
            sub_blocks = []
            if user_info_lines:
                sub_blocks.append("基本信息：\n" + "\n".join(user_info_lines))
            if preference_lines:
                sub_blocks.append("偏好习惯：\n" + "\n".join(preference_lines))
            if recent_topic_lines:
                sub_blocks.append("最近话题：\n" + "\n".join(recent_topic_lines))

            if sub_blocks:
                parts.append("【用户档案 — 跨会话记忆】\n" + "\n\n".join(sub_blocks) + "\n")

        # ── 3. 热记忆注入 ──
        hot = self._db.list_agent_memories_by_tier(
            self.agent_id, self.user_id, tier=1, limit=_MAX_HOT_COUNT,
        )
        if hot:
            hot_lines = []
            for i, m in enumerate(hot, 1):
                hot_lines.append(f"  [{i}] {m['content']}")
            parts.append(
                "【近期对话记忆 — 刚发生的事情】\n"
                + "\n".join(hot_lines)
                + "\n"
            )

        if not parts:
            return system_prompt  # 无记忆，不增加额外内容

        memory_block = (
            "\n\n【记忆 — 跨会话信息】\n"
            + "\n".join(parts)
            + "（以上信息来自之前的对话，请据此提供个性化服务。"
            "如果信息与当前对话矛盾，以当前对话为准。）\n"
        )

        if system_prompt:
            return system_prompt + memory_block
        return memory_block

    # ── 压缩 ──────────────────────────────────────────────────

    def compress(self) -> int:
        """执行记忆压缩。

        规则：
          - Tier 1 → 保留 _MAX_HOT_COUNT 条最新的
          - Tier 2 → 总字符超过 _MAX_WARM_CHARS 时，按重要度保留前 80%
          - Tier 3 → 总字符超过 _MAX_COLD_CHARS 时，合并最旧的 3 条为 1 条摘要

        Returns:
            删除/合并的记录数。
        """
        ops = 0

        # ── Tier 1：只保留最近 N 条 ──
        all_hot = self._db.list_agent_memories_by_tier(
            self.agent_id, self.user_id, tier=1, limit=999,
        )
        if len(all_hot) > _MAX_HOT_COUNT:
            to_delete = all_hot[_MAX_HOT_COUNT:]
            for m in to_delete:
                self._db.delete_agent_memory(m["id"])
                ops += 1
            logger.info("压缩 Tier 1: 删除了 %d 条旧热记忆", len(to_delete))

        # ── Tier 2：超过字符限制时保留重要度高的 ──
        all_warm = self._db.list_agent_memories_by_tier(
            self.agent_id, self.user_id, tier=2, limit=999,
        )
        total_warm_chars = sum(len(m["content"]) for m in all_warm)
        if total_warm_chars > _MAX_WARM_CHARS:
            # 按重要度降序排序后保留前 80%
            sorted_warm = sorted(all_warm, key=lambda m: m["importance"], reverse=True)
            keep_count = max(1, int(len(sorted_warm) * 0.8))
            to_delete = sorted_warm[keep_count:]
            for m in to_delete:
                self._db.demote_agent_memory(m["id"], 3)
                ops += 1
            logger.info(
                "压缩 Tier 2: 降级了 %d 条低重要度温记忆到冷记忆",
                len(to_delete),
            )

        # ── Tier 3：超过字符限制时合并最旧的 3 条 ──
        all_cold = self._db.list_agent_memories_by_tier(
            self.agent_id, self.user_id, tier=3, limit=999,
        )
        total_cold_chars = sum(len(m["content"]) for m in all_cold)
        if total_cold_chars > _MAX_COLD_CHARS and len(all_cold) >= 3:
            # 按访问时间升序 = 最久未访问
            sorted_cold = sorted(all_cold, key=lambda m: m["accessed_at"])
            to_merge = sorted_cold[:3]
            merged_text = "; ".join(m["content"] for m in to_merge)
            merged_summary = f"[合并摘要] {merged_text[:300]}..."

            # 合并后的摘要作为新冷记忆，重要度取平均
            avg_importance = sum(m["importance"] for m in to_merge) / len(to_merge)
            merged_keywords = ";".join(
                m["keywords"] for m in to_merge if m["keywords"]
            )

            # 删除被合并的旧记忆
            for m in to_merge:
                self._db.delete_agent_memory(m["id"])
                ops += 1

            # 写入合并摘要
            self._db.create_agent_memory(
                agent_id=self.agent_id,
                user_id=self.user_id,
                content=merged_summary,
                tier=3,
                keywords=merged_keywords,
                importance=avg_importance,
                source="auto_compress_merge",
            )
            logger.info(
                "压缩 Tier 3: 合并了 %d 条冷记忆为 1 条摘要",
                len(to_merge),
            )

        if ops > 0:
            logger.info("记忆压缩完成: 共 %d 次操作", ops)
        return ops

    # ── 自动压缩检查 ──────────────────────────────────────────

    def _auto_compress_if_needed(self) -> None:
        """如果所有记忆总字符超过阈值，自动触发降级。"""
        total = self._db.total_agent_memories_chars(
            self.agent_id, self.user_id,
        )
        if total > _MAX_TOTAL_CHARS:
            logger.info("记忆总字符 %d > %d，触发自动降级", total, _MAX_TOTAL_CHARS)
            # 将最久未访问的温记忆降级为冷记忆
            warm = self._db.list_agent_memories_by_tier(
                self.agent_id, self.user_id, tier=2, limit=999,
            )
            if warm:
                # 按访问时间升序（最久未访问的排在前面）
                sorted_warm = sorted(warm, key=lambda m: m["accessed_at"])
                # 降级一半以满足阈值
                target_chars = _MAX_TOTAL_CHARS // 2
                current_chars = total
                demoted = 0
                for m in sorted_warm:
                    if current_chars <= target_chars:
                        break
                    self._db.demote_agent_memory(m["id"], 3)
                    current_chars -= len(m["content"])
                    demoted += 1
                if demoted:
                    logger.info("自动降级: %d 条温记忆 → 冷记忆", demoted)

    # ── 自动提取温记忆 + 关系图谱 ────────────────────────────

    def extract_from_text(self, text: str) -> int:
        """从用户文本中自动提取可记住的信息并保存为温记忆。

        同时同步到关系图谱（cognee 模式）。

        使用正则匹配姓名、职业、偏好等。

        Args:
            text: 用户输入的文本。

        Returns:
            新增/更新的温记忆数量。
        """
        count = 0
        for pattern, key, label in _MEMORY_PATTERNS:
            match = re.search(pattern, text)
            if match:
                value = match.group(1).strip()
                # 检查是否已存在同名关键词的温记忆
                existing = self._db.search_agent_memories(
                    self.agent_id, self.user_id, key, limit=5,
                )
                already_exists = any(
                    key in (m.get("keywords") or "") and value in m["content"]
                    for m in existing
                )
                if already_exists:
                    continue

                # 保存为温记忆（标记为 is_user_info=True → 影响重要性评分）
                self.memorize(
                    content=f"{label}：{value}",
                    tier=2,
                    keywords=key,
                    source=f"auto_extract_{key}",
                    is_user_info=True,
                )
                count += 1
                logger.info("自动提取温记忆 [%s] = %s", key, value)

                # 同步到关系图谱（cognee 模式）
                try:
                    self.relation_graph.extract_from_text(text)
                except Exception as e:
                    logger.warning("关系图谱提取失败（非致命）: %s", e)

        return count

    # ── auto_summarize（agentmemory 风格） ───────────────────

    def auto_summarize(self, messages: list) -> str:
        """生成对话摘要并保存为热记忆（agentmemory 风格）。

        调用 DeepSeek API 将对话总结为 100 字以内的摘要，
        然后保存为 Tier 1 热记忆，供后续对话注入。

        Args:
            messages: 本轮对话消息列表（含 system/user/assistant）。

        Returns:
            摘要文本（失败时返回空字符串）。
        """
        try:
            # 过滤出 user 和 assistant 消息
            chat_msgs = [
                m for m in messages
                if m.get("role") in ("user", "assistant") and m.get("content")
            ]
            if not chat_msgs:
                return ""

            # 拼接对话文本（收拢避免超长）
            dialog_text = "\n".join(
                f"{'用户' if m['role'] == 'user' else 'AI'}: {m['content'][:200]}"
                for m in chat_msgs[-6:]  # 最多取最近 6 条
            )

            # 调用 DeepSeek API 生成摘要
            from openai import OpenAI
            from config import settings

            client = OpenAI(
                api_key=settings.deepseek_api_key,
                base_url=settings.deepseek_base_url,
            )
            response = client.chat.completions.create(
                model=settings.default_model,
                messages=[
                    {
                        "role": "system",
                        "content": "你是一个对话摘要助手。请将以下对话总结为 100 字以内的中文摘要，"
                                   "保留核心信息和用户的关键需求。只输出摘要本身。",
                    },
                    {"role": "user", "content": dialog_text},
                ],
                temperature=0.3,
                max_tokens=200,
                timeout=10,
            )

            summary = response.choices[0].message.content or ""
            summary = summary.strip().strip('"').strip("'")[:150]

            if not summary:
                return ""

            # 保存为热记忆
            self.memorize(
                content=f"[对话摘要] {summary}",
                importance=0.3,
                tier=1,
                keywords="对话摘要,总结",
                source="auto_summarize",
            )

            logger.info("自动摘要已生成（%d 字）: %s", len(summary), summary[:60])
            return summary

        except Exception as e:
            logger.warning("auto_summarize 失败（非致命）: %s", e)
            return ""

    # ── cleanup_expired（Memori 风格） ────────────────────────

    def cleanup_expired(self) -> int:
        """每天清理过期记忆（Memori 风格）。

        规则：
          - 30 天未访问的冷记忆（Tier 3）→ 删除
          - 60 天未访问的温记忆（Tier 2）→ 降级为冷记忆

        Returns:
            执行的操作数（删除数 + 降级数）。
        """
        ops = 0
        from datetime import datetime, timedelta
        now = datetime.now()

        # ── 30 天未访问的冷记忆 → 删除 ──
        cold_all = self._db.list_agent_memories_by_tier(
            self.agent_id, self.user_id, tier=3, limit=9999,
        )
        for m in cold_all:
            try:
                accessed = datetime.strptime(m["accessed_at"], "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                continue
            days_since = (now - accessed).days
            if days_since >= 30:
                self._db.delete_agent_memory(m["id"])
                ops += 1
                logger.info("过期冷记忆已删除 [%dd 未访问]: %s", days_since, m["content"][:50])

        # ── 60 天未访问的温记忆 → 降级为冷记忆 ──
        warm_all = self._db.list_agent_memories_by_tier(
            self.agent_id, self.user_id, tier=2, limit=9999,
        )
        for m in warm_all:
            try:
                accessed = datetime.strptime(m["accessed_at"], "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                continue
            days_since = (now - accessed).days
            if days_since >= 60:
                self._db.demote_agent_memory(m["id"], 3)
                ops += 1
                logger.info("过期温记忆已降冷 [%dd 未访问]: %s", days_since, m["content"][:50])

        if ops > 0:
            logger.info("过期记忆清理完成: 共 %d 次操作", ops)
        else:
            logger.debug("过期记忆清理: 无过期记忆")
        return ops

    # ── 辅助方法 ──────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """获取记忆统计信息。"""
        hot_count = self._db.count_agent_memories(
            self.agent_id, self.user_id, tier=1,
        )
        warm_count = self._db.count_agent_memories(
            self.agent_id, self.user_id, tier=2,
        )
        cold_count = self._db.count_agent_memories(
            self.agent_id, self.user_id, tier=3,
        )
        rel_count = len(self.relation_graph.find_all(limit=9999)) if self._relation_graph else 0
        total_chars = self._db.total_agent_memories_chars(
            self.agent_id, self.user_id,
        )
        return {
            "hot_count": hot_count,
            "warm_count": warm_count,
            "cold_count": cold_count,
            "relation_count": rel_count,
            "total_count": hot_count + warm_count + cold_count,
            "total_chars": total_chars,
            "max_chars": _MAX_TOTAL_CHARS,
        }

    def get_hot_memories(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取最近的热记忆。"""
        return self._db.list_agent_memories_by_tier(
            self.agent_id, self.user_id, tier=1, limit=limit,
        )

    def get_warm_memories(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取温记忆（按重要度排序）。"""
        return self._db.list_agent_memories_by_tier(
            self.agent_id, self.user_id, tier=2, limit=limit,
        )

    def get_cold_memories(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取冷记忆。"""
        return self._db.list_agent_memories_by_tier(
            self.agent_id, self.user_id, tier=3, limit=limit,
        )
