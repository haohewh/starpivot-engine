"""StarPivot Engine - Database marketplace mixin"""
import sqlite3
import uuid
import json
import time
import os
from datetime import datetime, timedelta
from typing import Any, Optional


class MarketplaceMixin:
    """Mixin providing marketplace-related database operations."""
    
    # All methods in this mixin access self.conn, self._execute_write, etc.
    # from the parent Database class.
    
    def create_marketplace_tool(self, name: str, description: str = "",
                                author_id: str = "", category: str = "",
                                mcp_server_code: str = "",
                                config_json: str = "") -> dict:
        """发布工具到市场，返回工具信息字典。"""
        tool_id = self._short_id("MP")
        now = "datetime('now','localtime')"
        from datetime import datetime
        ts = datetime.now().isoformat()
        sql = """INSERT INTO marketplace_tools
                 (id, name, description, author_id, category, stars, downloads,
                  status, mcp_server_code, config_json, created_at, updated_at)
                 VALUES (?, ?, ?, ?, ?, 0, 0, 'pending', ?, ?, ?, ?)"""
        self._execute_write(sql, (tool_id, name, description, author_id, category,
                                  mcp_server_code, config_json, ts, ts))
        return self.get_marketplace_tool(tool_id)


    def get_marketplace_tool(self, tool_id: str):
        """按 ID 查询市场工具。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute("SELECT * FROM marketplace_tools WHERE id = ?", (tool_id,)).fetchone()
            )


    def list_marketplace_tools(self, status: str = "approved", category: str = "",
                                limit: int = 50, offset: int = 0) -> list:
        """列出市场工具，可按状态和分类过滤。"""
        with self.conn() as conn:
            conditions = []
            params = []
            if status:
                conditions.append("status = ?")
                params.append(status)
            if category:
                conditions.append("category = ?")
                params.append(category)
            where = " AND ".join(conditions) if conditions else "1=1"
            rows = conn.execute(
                f"SELECT * FROM marketplace_tools WHERE {where} ORDER BY stars DESC, downloads DESC LIMIT ? OFFSET ?",
                tuple(params) + (limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]


    def search_marketplace_tools(self, keyword: str, category: str = "",
                                 sort_by: str = "stars", limit: int = 50) -> list:
        """搜索市场工具，按关键词匹配名称和描述。"""
        with self.conn() as conn:
            conditions = ["status = 'approved'"]
            params = []
            if keyword:
                conditions.append("(name LIKE ? OR description LIKE ?)")
                kw = f"%{keyword}%"
                params.extend([kw, kw])
            if category:
                conditions.append("category = ?")
                params.append(category)
            where = " AND ".join(conditions)
            order = "stars DESC"
            if sort_by == "downloads":
                order = "downloads DESC"
            elif sort_by == "newest":
                order = "created_at DESC"
            rows = conn.execute(
                f"SELECT * FROM marketplace_tools WHERE {where} ORDER BY {order} LIMIT ?",
                tuple(params) + (limit,),
            ).fetchall()
            return [dict(r) for r in rows]


    def update_marketplace_tool(self, tool_id: str, **kwargs) -> bool:
        """按 ID 更新市场工具字段。"""
        if not kwargs:
            return False
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        sql = f"UPDATE marketplace_tools SET {sets}, updated_at = datetime('now','localtime') WHERE id = ?"
        params = tuple(kwargs.values()) + (tool_id,)
        self._execute_write(sql, params)
        return True


    def increment_tool_downloads(self, tool_id: str) -> None:
        """原子地将工具下载数加 1。"""
        with self._lock:
            with self.conn() as conn:
                conn.execute(
                    "UPDATE marketplace_tools SET downloads = downloads + 1 WHERE id = ?",
                    (tool_id,),
                )


    def create_marketplace_review(self, tool_id: str, user_id: str,
                                  rating: int, comment: str = "") -> dict:
        """给工具添加评价，同时更新工具的 stars 均值。返回评价信息。"""
        if rating < 1 or rating > 5:
            raise ValueError("评分必须在 1-5 之间")
        review_id = self._short_id("RV")
        from datetime import datetime
        ts = datetime.now().isoformat()
        sql = """INSERT INTO marketplace_reviews (id, tool_id, user_id, rating, comment, created_at)
                 VALUES (?, ?, ?, ?, ?, ?)"""
        self._execute_write(sql, (review_id, tool_id, user_id, rating, comment, ts))
        # 重新计算该工具的平均评分
        with self.conn() as conn:
            row = conn.execute(
                "SELECT AVG(rating) as avg_rating, COUNT(*) as count FROM marketplace_reviews WHERE tool_id = ?",
                (tool_id,),
            ).fetchone()
            avg_rating = round(row["avg_rating"]) if row and row["avg_rating"] else 0
            conn.execute(
                "UPDATE marketplace_tools SET stars = ? WHERE id = ?",
                (avg_rating, tool_id),
            )
        return self.get_marketplace_review(review_id)


    def get_marketplace_review(self, review_id: str):
        """按 ID 查询评价。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute("SELECT * FROM marketplace_reviews WHERE id = ?", (review_id,)).fetchone()
            )


    def list_marketplace_reviews(self, tool_id: str, limit: int = 50) -> list:
        """列出某工具的评分记录。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM marketplace_reviews WHERE tool_id = ? ORDER BY created_at DESC LIMIT ?",
                (tool_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]


    def get_tool_rating_summary(self, tool_id: str) -> dict:
        """获取工具评分汇总。"""
        with self.conn() as conn:
            row = conn.execute(
                "SELECT AVG(rating) as avg_rating, COUNT(*) as count FROM marketplace_reviews WHERE tool_id = ?",
                (tool_id,),
            ).fetchone()
            return {
                "avg_rating": round(row["avg_rating"], 1) if row and row["avg_rating"] else 0.0,
                "count": row["count"] if row else 0,
            }


    def save_spark_score(self, tool_name: str, utility_score: float = 0,
                         industrial_score: float = 0, stability_score: float = 0,
                         speed_score: float = 0, update_score: float = 0,
                         security_score: float = 0, compatibility_score: float = 0,
                         review_score: float = 0, revolution_score: float = 0,
                         total_score: float = 0, grade: str = "F") -> None:
        """保存或更新星火鉴评分。"""
        sql = """INSERT INTO spark_scores
                 (tool_name, utility_score, industrial_score, stability_score,
                  speed_score, update_score, security_score, compatibility_score,
                  review_score, revolution_score, total_score, grade, evaluated_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))
                 ON CONFLICT(tool_name) DO UPDATE SET
                     utility_score = excluded.utility_score,
                     industrial_score = excluded.industrial_score,
                     stability_score = excluded.stability_score,
                     speed_score = excluded.speed_score,
                     update_score = excluded.update_score,
                     security_score = excluded.security_score,
                     compatibility_score = excluded.compatibility_score,
                     review_score = excluded.review_score,
                     star_score = excluded.revolution_score,
                     total_score = excluded.total_score,
                     grade = excluded.grade,
                     evaluated_at = datetime('now','localtime')"""
        self._execute_write(sql, (tool_name, utility_score, industrial_score,
                                   stability_score, speed_score, update_score,
                                   security_score, compatibility_score,
                                   review_score, star_score, total_score, grade))


    def get_spark_score(self, tool_name: str) -> dict:
        """获取工具星火鉴评分。"""
        with self.conn() as conn:
            row = self._row_to_dict(
                conn.execute("SELECT * FROM spark_scores WHERE tool_name = ?", (tool_name,)).fetchone()
            )
            if row:
                return row
            return {"tool_name": tool_name, "total_score": 0, "grade": "N/A"}


    def list_spark_scores(self, limit: int = 50, offset: int = 0) -> list:
        """列出所有星火鉴评分，按总分降序。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM spark_scores ORDER BY total_score DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]


    def create_spark_review(self, tool_name: str, user_id: str,
                            rating: int, comment: str = "",
                            thumbs_up: int = 0, thumbs_down: int = 0) -> dict:
        """提交用户评价。返回评价信息。"""
        if rating < 1 or rating > 5:
            raise ValueError("评分必须在 1-5 之间")
        review_id = self._short_id("SR")
        sql = """INSERT INTO spark_reviews (id, tool_name, user_id, rating, comment, thumbs_up, thumbs_down)
                 VALUES (?, ?, ?, ?, ?, ?, ?)"""
        self._execute_write(sql, (review_id, tool_name, user_id, rating, comment, thumbs_up, thumbs_down))
        return self.get_spark_review(review_id)


    def get_spark_review(self, review_id: str) -> dict:
        """按 ID 查询评价。"""
        with self.conn() as conn:
            return self._row_to_dict(
                conn.execute("SELECT * FROM spark_reviews WHERE id = ?", (review_id,)).fetchone()
            )


    def list_spark_reviews(self, tool_name: str, limit: int = 50) -> list:
        """列出某工具的所有评价。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM spark_reviews WHERE tool_name = ? ORDER BY created_at DESC LIMIT ?",
                (tool_name, limit),
            ).fetchall()
            return [dict(r) for r in rows]


    def get_spark_review_summary(self, tool_name: str) -> dict:
        """获取工具评价汇总：平均评分、总评价数、好评率。"""
        with self.conn() as conn:
            row = conn.execute(
                "SELECT AVG(rating) as avg_rating, COUNT(*) as count FROM spark_reviews WHERE tool_name = ?",
                (tool_name,),
            ).fetchone()
            avg = round(row["avg_rating"], 2) if row and row["avg_rating"] else 0.0
            count = row["count"] if row else 0
            # 好评率：评分 >= 4 的比例
            if count > 0:
                good = conn.execute(
                    "SELECT COUNT(*) FROM spark_reviews WHERE tool_name = ? AND rating >= 4",
                    (tool_name,),
                ).fetchone()[0]
                good_rate = round(good / count * 100, 1)
            else:
                good_rate = 0.0
            return {"avg_rating": avg, "count": count, "good_rate": good_rate}


    def star_tool(self, tool_name: str, user_id: str) -> bool:
        """用户标记星数（点赞工具）。返回是否新增标记。"""
        with self._lock:
            with self.conn() as conn:
                existing = conn.execute(
                    "SELECT 1 FROM spark_stars WHERE tool_name = ? AND user_id = ?",
                    (tool_name, user_id),
                ).fetchone()
                if existing:
                    return False  # 已标记过
                conn.execute(
                    "INSERT INTO spark_stars (tool_name, user_id) VALUES (?, ?)",
                    (tool_name, user_id),
                )
                return True


    def unstar_tool(self, tool_name: str, user_id: str) -> bool:
        """用户取消星数标记。"""
        self._execute_write(
            "DELETE FROM spark_stars WHERE tool_name = ? AND user_id = ?",
            (tool_name, user_id),
        )
        return True


    def get_star_count(self, tool_name: str) -> int:
        """获取工具星数。"""
        with self.conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM spark_stars WHERE tool_name = ?",
                (tool_name,),
            ).fetchone()
            return row[0] if row else 0


    def has_user_starred(self, tool_name: str, user_id: str) -> bool:
        """检查用户是否已标记星数。"""
        with self.conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM spark_stars WHERE tool_name = ? AND user_id = ?",
                (tool_name, user_id),
            ).fetchone()
            return row is not None


    def list_starred_tools(self, user_id: str, limit: int = 50) -> list:
        """列出用户标记过的工具。"""
        with self.conn() as conn:
            rows = conn.execute(
                """SELECT s.*, t.name as tool_display_name
                   FROM spark_stars s
                   LEFT JOIN marketplace_tools t ON s.tool_name = t.name
                   WHERE s.user_id = ? ORDER BY s.starred_at DESC LIMIT ?""",
                (user_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]


    def save_repo_stars(self, tool_name: str, repo_url: str,
                        github_stars: int = 0) -> None:
        """保存或更新工具的 GitHub 星数。"""
        from datetime import datetime
        sql = """INSERT INTO spark_repo_stars (tool_name, repo_url, github_stars, last_synced)
                 VALUES (?, ?, ?, ?)
                 ON CONFLICT(tool_name) DO UPDATE SET
                     repo_url = excluded.repo_url,
                     github_stars = excluded.github_stars,
                     last_synced = excluded.last_synced"""
        self._execute_write(sql, (tool_name, repo_url,
                                  github_stars, datetime.now().isoformat()))


    def get_repo_stars(self, tool_name: str) -> dict:
        """获取工具的 GitHub 星数信息。"""
        with self.conn() as conn:
            row = self._row_to_dict(
                conn.execute("SELECT * FROM spark_repo_stars WHERE tool_name = ?",
                             (tool_name,)).fetchone()
            )
            if row:
                return row
            return {"tool_name": tool_name, "repo_url": "",
                    "github_stars": 0, "last_synced": None}


    def list_repo_stars(self, limit: int = 50, offset: int = 0) -> list:
        """列出所有 GitHub 星数记录。"""
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT * FROM spark_repo_stars ORDER BY github_stars DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [dict(r) for r in rows]


