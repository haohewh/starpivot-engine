"""好评率 + 星数管理 (Review System) — 用户反馈、点赞、评分。

功能：
1. 用户评分 1-5 星
2. 用户点赞/点踩
3. 用户标记星数（类 GitHub Stars）
4. 统计好评率

评分标准（好评率）：
- 100: 好评率 ≥95%
- 90:  好评率 ≥85%
- 70:  好评率 ≥70%
- 50:  好评率 ≥50%
- 20:  好评率 <50%
- 0:   无评价

评分标准（星数）：
- 100: 星数 ≥100
- 80:  星数 ≥50
- 60:  星数 ≥20
- 40:  星数 ≥10
- 20:  星数 ≥1
- 0:   星数 = 0
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ReviewSystem:
    """好评率 + 星数管理器。

    直接操作数据库 spark_reviews 和 spark_stars 表。
    不需要引擎连接，只需要数据库访问。
    """

    def __init__(self, db=None) -> None:
        self._db = db
        self._results: dict[str, Any] = {}

    def evaluate(self, tool_name: str) -> dict:
        """评估工具的好评率和星数。

        Args:
            tool_name: 工具名称。

        Returns:
            dict: {
                review: {score, avg_rating, count, good_rate},
                star: {score, count},
                detail
            }
        """
        result: dict[str, Any] = {
            "name": "review_system",
            "tool_name": tool_name,
            "review_score": 0,
            "star_score": 0,
            "review": {},
            "star": {},
            "detail": "",
            "error": None,
        }

        db = self._get_db()
        if not db:
            result["review_score"] = 0
            result["star_score"] = 0
            result["detail"] = "无数据库连接，使用默认评分"
            self._results[tool_name] = result
            return result

        try:
            # 获取评价汇总
            summary = db.get_spark_review_summary(tool_name)
            result["review"] = summary
            result["review_score"] = self._score_review(summary)

            # 获取星数
            star_count = db.get_star_count(tool_name)
            result["star"] = {"count": star_count}
            result["star_score"] = self._score_stars(star_count)

            result["detail"] = (
                f"评价: 平均 {summary.get('avg_rating', 0)}分, "
                f"共 {summary.get('count', 0)} 条, "
                f"好评率 {summary.get('good_rate', 0)}%, "
                f"星数: {star_count}"
            )

        except Exception as e:
            result["review_score"] = 50
            result["star_score"] = 50
            result["detail"] = f"数据查询异常: {e}"
            result["error"] = str(e)
            logger.warning("好评率/星数检测异常: %s", e)

        self._results[tool_name] = result
        return result

    # ── 用户操作 ──────────────────────────────────────────

    def submit_review(self, tool_name: str, user_id: str, rating: int,
                      comment: str = "", thumbs_up: int = 0,
                      thumbs_down: int = 0) -> dict | None:
        """提交用户评价。

        Args:
            tool_name: 工具名称。
            user_id:   用户 ID。
            rating:    评分 1-5。
            comment:   评论文本。
            thumbs_up: 点赞数。
            thumbs_down: 点踩数。

        Returns:
            dict: 评价信息，失败返回 None。
        """
        db = self._get_db()
        if not db:
            return None
        try:
            return db.create_spark_review(
                tool_name=tool_name,
                user_id=user_id,
                rating=rating,
                comment=comment,
                thumbs_up=thumbs_up,
                thumbs_down=thumbs_down,
            )
        except Exception as e:
            logger.error("提交评价失败: %s", e)
            return None

    def star_tool(self, tool_name: str, user_id: str) -> bool:
        """标记星数。返回 True 表示新增标记。"""
        db = self._get_db()
        if not db:
            return False
        return db.star_tool(tool_name, user_id)

    def unstar_tool(self, tool_name: str, user_id: str) -> bool:
        """取消星数标记。"""
        db = self._get_db()
        if not db:
            return False
        db.unstar_tool(tool_name, user_id)
        return True

    def list_reviews(self, tool_name: str, limit: int = 50) -> list:
        """列出工具的评价。"""
        db = self._get_db()
        if not db:
            return []
        return db.list_spark_reviews(tool_name, limit)

    def get_summary(self, tool_name: str) -> dict:
        """获取汇总信息。"""
        db = self._get_db()
        if not db:
            return {"avg_rating": 0, "count": 0, "good_rate": 0}
        summary = db.get_spark_review_summary(tool_name)
        summary["star_count"] = db.get_star_count(tool_name)
        return summary

    # ── 评分辅助 ──────────────────────────────────────────

    @staticmethod
    def _score_review(summary: dict) -> int:
        """根据好评率评分。"""
        good_rate = summary.get("good_rate", 0)
        if good_rate >= 95:
            return 100
        if good_rate >= 85:
            return 90
        if good_rate >= 70:
            return 70
        if good_rate >= 50:
            return 50
        if summary.get("count", 0) > 0:
            return 20
        return 0

    @staticmethod
    def _score_stars(count: int) -> int:
        """根据星数评分。"""
        if count >= 100:
            return 100
        if count >= 50:
            return 80
        if count >= 20:
            return 60
        if count >= 10:
            return 40
        if count >= 1:
            return 20
        return 0

    # ── 辅助 ──────────────────────────────────────────────

    def _get_db(self):
        """获取数据库实例。"""
        if self._db:
            return self._db
        try:
            from store.db import get_db
            return get_db()
        except ImportError:
            return None
