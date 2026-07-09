""""
星枢 AI — 关系图谱记忆（参考 cognee / memvid）

不存"文本"，存"关系"三元组：
  "张三" → "职业" → "会计"
  "张三" → "偏好" → "简洁风格"

memvid 风格：按需检索，不一次性注入所有关系。
检索时通过关系推理找到相关信息。
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from store.db import get_db

logger = logging.getLogger(__name__)

# ── 关系抽取模式 ─────────────────────────────────────────────
_RELATION_PATTERNS = [
    # "我叫张三" → entity="张三", relation="称呼"
    (r'(?:我(?:叫|是))(\\S{2,8})(?=[，,。.\\s]|$)', "称呼"),
    # "我是做计算机的" → entity="用户", relation="职业"
    (r'(?:我(?:是|是一名?)(?:做|干|搞)?)(\\S{2,10}(?:的)?(?:工作|行业|职业)?)(?=[，,。.\\s]|$)', "职业"),
    # "我喜欢简洁的风格" → entity="用户", relation="偏好"
    (r'(?:我(?:喜欢|偏好|习惯)(?:于)?)(\\S{2,20}(?:风格|颜色|样式|方式)?)(?=[，,。.\\s]|$)', "偏好"),
    # "叫我老王" → entity="用户", relation="昵称"
    (r'(?:叫[我]?)(\\S{2,8})(?:就行|就好|吧|即可)?(?=[，,。.\\s]|$)', "昵称"),
    # "我今年25岁" → entity="用户", relation="年龄"
    (r'(?:我今年|我)(\\d{1,3}|[一二三四五六七八九十百千]+)\\s*岁', "年龄"),
    # "家在深圳" → entity="用户", relation="所在地"
    (r'(?:家(?:在|住)|我住|我来自)(\\S{2,10}(?:市|区|县|省)?)(?=[，,。.\\s]|$)', "所在地"),
    # "我的名字是张三" → entity="张三", relation="姓名"
    (r'(?:我的名字(?:是|叫))([\\u4e00-\\u9fff]{2,8})(?=[，,。.\\s]|$)', "姓名"),
]


class RelationGraph:
    """关系图谱管理器（cognee 模式）。

    功能：
      - add_relation(entity, relation, target) → 存储三元组
      - extract_from_text(text) → 自动提取关系
      - find_by_entity(entity) → 找到关于某实体的所有信息
      - find_by_relation(relation) → 找到某类型的所有关系
      - find_by_keyword(keyword) → 全文搜索关系
    """

    def __init__(self, agent_id: str, user_id: str):
        self.agent_id = agent_id
        self.user_id = user_id
        self._db = get_db()

    # ── 添加关系 ─────────────────────────────────────────────

    def add_relation(self, entity: str, relation: str, target: str) -> str:
        """添加一条关系三元组，返回 ID。

        自动去重：如果相同的 (entity, relation, target) 已存在，直接返回已有 ID。
        """
        # 检查是否已存在
        existing = self._db.search_memory_relations_all(
            self.agent_id, self.user_id, entity,
        )
        for r in existing:
            if r["entity"] == entity and r["relation"] == relation and r["target"] == target:
                return r["id"]

        rid = self._db.create_memory_relation(
            self.agent_id, self.user_id, entity, relation, target,
        )
        logger.debug("关系已添加: %s → %s → %s", entity, relation, target)
        return rid

    def add_relations_batch(self, triples: List[tuple]) -> List[str]:
        """批量添加关系三元组。

        Args:
            triples: [(entity, relation, target), ...]

        Returns:
            新增的关系 ID 列表。
        """
        ids = []
        for entity, relation, target in triples:
            rid = self.add_relation(entity, relation, target)
            ids.append(rid)
        return ids

    # ── memvid 风格：按需检索（完善版） ─────────────────────

    def query(self, entity: str) -> list:
        """查询某个实体的所有关系（memvid 风格）。

        Args:
            entity: 实体名称（如 "张三"、"用户"）。

        Returns:
            该实体的所有关系列表。
        """
        return self.find_by_entity(entity)

    def search_by_keyword(self, keyword: str) -> list:
        """按关键词检索相关实体和关系（memvid 风格）。

        搜索 entity、relation、target 三个字段，
        返回匹配程度最高的结果（上限 10 条）。

        Args:
            keyword: 关键词。

        Returns:
            匹配的关系列表（按相关度排序，上限 10 条）。
        """
        results = self.find_by_keyword(keyword)
        # 按关键词出现位置排序：entity > relation > target
        kw = keyword.lower()

        def _relevance(r: dict) -> int:
            score = 0
            if kw in r.get("entity", "").lower():
                score += 3
            if kw in r.get("relation", "").lower():
                score += 2
            if kw in r.get("target", "").lower():
                score += 1
            return score

        results.sort(key=_relevance, reverse=True)
        return results[:10]

    # ── 查询 ─────────────────────────────────────────────────

    def find_by_entity(self, entity: str) -> List[Dict[str, Any]]:
        """找到关于某个实体的所有关系。

        Args:
            entity: 实体名称（如 "张三"、"用户"）。

        Returns:
            匹配的关系列表。
        """
        return self._db.search_memory_relations_by_entity(
            self.agent_id, self.user_id, entity,
        )

    def find_by_relation(self, relation: str) -> List[Dict[str, Any]]:
        """找到某种类型的所有关系。

        Args:
            relation: 关系类型（如 "职业"、"偏好"）。

        Returns:
            匹配的关系列表。
        """
        return self._db.search_memory_relations_by_relation(
            self.agent_id, self.user_id, relation,
        )

    def find_by_target(self, target: str) -> List[Dict[str, Any]]:
        """按目标值查询。

        Args:
            target: 目标值（如 "会计"）。

        Returns:
            匹配的关系列表。
        """
        return self._db.search_memory_relations_by_target(
            self.agent_id, self.user_id, target,
        )

    def find_by_keyword(self, keyword: str) -> List[Dict[str, Any]]:
        """全文搜索关系（搜索 entity/relation/target 三个字段）。

        Args:
            keyword: 关键词。

        Returns:
            匹配的关系列表。
        """
        return self._db.search_memory_relations_all(
            self.agent_id, self.user_id, keyword,
        )

    def find_all(self, limit: int = 100) -> List[Dict[str, Any]]:
        """列出所有关系。"""
        return self._db.list_memory_relations(
            self.agent_id, self.user_id, limit=limit,
        )

    # ── 删除 ─────────────────────────────────────────────────

    def delete_relation(self, relation_id: str) -> bool:
        """按 ID 删除一条关系。"""
        return self._db.delete_memory_relation(relation_id)

    def clear_all(self) -> int:
        """清空当前 agent+user 的所有关系，返回删除条数。"""
        all_rels = self.find_all(limit=9999)
        for r in all_rels:
            self._db.delete_memory_relation(r["id"])
        logger.info("关系图谱已清空: 删除了 %d 条关系", len(all_rels))
        return len(all_rels)

    # ── 自动提取 ─────────────────────────────────────────────

    def extract_from_text(self, text: str) -> int:
        """从用户文本中自动提取关系并存储。

        使用正则模式匹配实体-关系-目标三元组。

        Args:
            text: 用户输入的文本。

        Returns:
            新增的关系数量。
        """
        import re

        count = 0
        for pattern, relation_type in _RELATION_PATTERNS:
            match = re.search(pattern, text)
            if match:
                value = match.group(1).strip()
                # 判断是实体名还是用户属性
                if relation_type in ("称呼", "姓名", "昵称"):
                    entity = value
                else:
                    entity = "用户"

                # 检查是否已存在
                existing = self._db.search_memory_relations_all(
                    self.agent_id, self.user_id, entity,
                )
                already_exists = any(
                    r["entity"] == entity and r["relation"] == relation_type and r["target"] == value
                    for r in existing
                )
                if already_exists:
                    continue

                self.add_relation(entity, relation_type, value)
                count += 1
                logger.info("自动提取关系 [%s] %s → %s", relation_type, entity, value)

        return count

    # ── 格式化输出 ───────────────────────────────────────────

    def format_as_inject_block(self) -> str:
        """将关系图谱格式化为结构化注入块（letta 风格）。

        Returns:
            格式化的关系图谱字符串，如：
            【关于你】
            姓名：张三 | 职业：会计 | 偏好：简洁风格
        """
        all_rels = self.find_all(limit=50)
        if not all_rels:
            return ""

        # 按实体分组
        groups: Dict[str, List[str]] = {}
        for r in all_rels:
            entity = r["entity"]
            if entity not in groups:
                groups[entity] = []
            groups[entity].append(f"{r['relation']}：{r['target']}")

        lines = []
        for entity, attrs in groups.items():
            lines.append(f"{entity}：{' | '.join(attrs)}")

        if lines:
            return "【关于你】\n" + "\n".join(lines) + "\n"
        return ""
