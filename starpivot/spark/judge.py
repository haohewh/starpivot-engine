"""星火鉴主引擎 (SparkJudge) — 运行全部 9 项检测，生成综合报告。

用法:
    from core.starpivot.spark import SparkJudge

    judge = SparkJudge(engine=engine, registry=registry)
    report = await judge.evaluate("agent_reach_search")
    print(report)
    # {utility: 85, industrial: 70, stability: 100, speed: 92, ...,
    #  total: 87.5, grade: "A"}
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .utility_test import UtilityTest
from .stability_test import StabilityTest
from .speed_test import SpeedTest
from .update_monitor import UpdateMonitor
from .security_test import SparkSecurityTest
from .integration_test import IntegrationTest
from .review_system import ReviewSystem

logger = logging.getLogger(__name__)


# ── 权重配置 ──────────────────────────────────────────────

WEIGHTS = {
    "utility": 0.20,         # 实用性 20%
    "stability": 0.15,       # 稳定性 15%
    "compatibility": 0.12,   # 兼容性 12%
    "speed": 0.10,           # 时速性 10%
    "security": 0.10,        # 安全性 10%
    "review": 0.10,          # 好评率 10%（含用户评分+星数）
    "industrial": 0.10,      # 工业性 10%
    "revolution": 0.08,      # 革命性 8%
    "update": 0.05,          # 更新力 5%
}

GRADE_THRESHOLDS = [
    ("S", 95),
    ("A", 85),
    ("B", 70),
    ("C", 55),
    ("D", 40),
]


class SparkJudge:
    """星火鉴主引擎。

    运行全部 9 项质量检测，按权重计算总分，
    生成等级评定并存入数据库。
    """

    def __init__(self, engine=None, registry=None, shield=None, db=None,
                 repo_path: str | None = None) -> None:
        self._engine = engine
        self._registry = registry
        self._shield = shield
        self._db = db
        self._repo_path = repo_path

        # 初始化各检测器
        self.utility = UtilityTest(engine=engine)
        self.stability = StabilityTest(engine=engine)
        self.speed = SpeedTest(engine=engine)
        self.update = UpdateMonitor(repo_path=repo_path)
        self.security = SparkSecurityTest(shield=shield)
        self.integration = IntegrationTest(engine=engine, registry=registry)
        self.review = ReviewSystem(db=db)

        self._results: dict[str, Any] = {}

    async def evaluate(self, tool_name: str, arguments: dict | None = None,
                       save_to_db: bool = True) -> dict:
        """运行全部 9 项检测，生成综合报告。

        Args:
            tool_name:   工具名称。
            arguments:   测试参数（可选）。
            save_to_db:  是否将结果存入 spark_scores 表（默认 True）。

        Returns:
            dict: {
                tool_name, utility, industrial, stability,
                speed, update, security, compatibility,
                review, star, total, grade,
                details: {每项检测的详细结果},
                evaluated_at
            }
        """
        logger.info("🔍 星火鉴启动: 评估工具 '%s'", tool_name)

        args = arguments or {}

        # ── 并行执行前 7 项检测 ──
        # 注: update_monitor 和 review_system 是同步的，可以一起做
        tasks = {
            "utility": self.utility.evaluate(tool_name, args),
            "stability": self.stability.evaluate(tool_name, args),
            "speed": self.speed.evaluate(tool_name, args),
            "security": asyncio.to_thread(self.security.evaluate, tool_name),
            "compatibility": self.integration.evaluate(tool_name, args),
        }

        results = {}
        for name, coro in tasks.items():
            try:
                results[name] = await coro
            except Exception as e:
                logger.error("检测 '%s' 异常: %s", name, e)
                results[name] = {"score": 0, "error": str(e)}

        # 同步检测
        try:
            results["update"] = self.update.evaluate(tool_name)
        except Exception as e:
            logger.error("检测 'update' 异常: %s", e)
            results["update"] = {"score": 0, "error": str(e)}

        try:
            results["review"] = self.review.evaluate(tool_name)
        except Exception as e:
            logger.error("检测 'review' 异常: %s", e)
            results["review"] = {"review_score": 0, "error": str(e)}

        # ── 提取各维度分数 ──
        utility_score = results["utility"].get("score", 0)
        stability_score = results["stability"].get("score", 0)
        speed_score = results["speed"].get("score", 0)
        update_score = results["update"].get("score", 0)
        security_score = results["security"].get("score", 0)
        compatibility_score = results["compatibility"].get("score", 0)

        review_data = results["review"]
        # 好评率得分（已含星数）
        review_score = review_data.get("review_score", 0)

        # 革命性评分（暂无数据，默认 50 分）
        revolution_score = 50

        # 工业性（industrial）— 综合评估
        # 取安全性、兼容性和时速性的平均作为工业性参考
        industrial_score = round(
            (security_score + compatibility_score + speed_score) / 3
        )

        # ── 计算总分 ──
        weighted = (
            utility_score * WEIGHTS["utility"]
            + industrial_score * WEIGHTS["industrial"]
            + stability_score * WEIGHTS["stability"]
            + speed_score * WEIGHTS["speed"]
            + update_score * WEIGHTS["update"]
            + security_score * WEIGHTS["security"]
            + compatibility_score * WEIGHTS["compatibility"]
            + review_score * WEIGHTS["review"]  # 好评率（含星数）
            + revolution_score * WEIGHTS["revolution"]
        )
        total_score = round(weighted, 1)

        # ── 等级评定 ──
        grade = self._calculate_grade(total_score)

        # ── 组装报告 ──
        report = {
            "tool_name": tool_name,
            "utility": utility_score,
            "industrial": industrial_score,
            "stability": stability_score,
            "speed": speed_score,
            "update": update_score,
            "security": security_score,
            "compatibility": compatibility_score,
            "review": review_score,
            "revolution": int(revolution_score),
            "total": total_score,
            "grade": grade,
            "details": results,
            "evaluated_at": __import__("datetime").datetime.now().isoformat(),
        }

        # ── 存入数据库 ──
        if save_to_db:
            try:
                db = self._get_db()
                if db:
                    db.save_spark_score(
                        tool_name=tool_name,
                        utility_score=float(utility_score),
                        industrial_score=float(industrial_score),
                        stability_score=float(stability_score),
                        speed_score=float(speed_score),
                        update_score=float(update_score),
                        security_score=float(security_score),
                        compatibility_score=float(compatibility_score),
                        review_score=float(review_score),
                        revolution_score=float(revolution_score),
                        total_score=float(total_score),
                        grade=grade,
                    )
                    logger.info("✅ 星火鉴评分已存入数据库: %s = %.1f 分 [%s]", tool_name, total_score, grade)
            except Exception as e:
                logger.warning("存入数据库失败: %s", e)

        # 彩虹输出
        self._print_report(report)

        self._results[tool_name] = report
        return report

    # ── 批量评估 ──────────────────────────────────────────

    async def batch_evaluate(self, tool_names: list[str],
                             save_to_db: bool = True) -> list[dict]:
        """批量评估多个工具。

        Args:
            tool_names: 工具名称列表。
            save_to_db: 是否存入数据库。

        Returns:
            list[dict]: 每个工具的评估报告。
        """
        tasks = [self.evaluate(name, save_to_db=save_to_db) for name in tool_names]
        return await asyncio.gather(*tasks)

    # ── 等级计算 ──────────────────────────────────────────

    @staticmethod
    def _calculate_grade(total_score: float) -> str:
        """根据总分计算等级。"""
        for grade, threshold in GRADE_THRESHOLDS:
            if total_score >= threshold:
                return grade
        return "F"

    # ── 报告输出 ──────────────────────────────────────────

    def _print_report(self, report: dict) -> None:
        """打印彩色评估报告。"""
        grade_emoji = {
            "S": "🏆", "A": "⭐", "B": "✅",
            "C": "⚠️", "D": "🔻", "F": "❌",
        }
        emoji = grade_emoji.get(report["grade"], "❓")

        lines = [
            f"\n{'='*50}",
            f"  {emoji} 星火鉴评估报告: {report['tool_name']}",
            f"{'='*50}",
            f"  实用性 (x{WEIGHTS['utility']:.0%}):     {report['utility']:>3d}",
            f"  工业性 (x{WEIGHTS['industrial']:.0%}):   {report['industrial']:>3d}",
            f"  稳定性 (x{WEIGHTS['stability']:.0%}):     {report['stability']:>3d}",
            f"  时速性 (x{WEIGHTS['speed']:.0%}):       {report['speed']:>3d}",
            f"  更新力 (x{WEIGHTS['update']:.0%}):       {report['update']:>3d}",
            f"  安全性 (x{WEIGHTS['security']:.0%}):     {report['security']:>3d}",
            f"  兼容性 (x{WEIGHTS['compatibility']:.0%}): {report['compatibility']:>3d}",
            f"  好评率 (x{WEIGHTS['review']:.0%}):       {report['review']:>3d}",
            f"  革命性 (x{WEIGHTS['revolution']:.0%}):  {report['revolution']:>3d}",
            f"{'─'*50}",
            f"  总分: {report['total']:.1f}  等级: {emoji} {report['grade']}",
            f"{'='*50}\n",
        ]
        logger.info("\n".join(lines))

    # ── 数据库 ────────────────────────────────────────────

    def _get_db(self):
        """获取数据库实例。"""
        if self._db:
            return self._db
        try:
            from store.db import get_db
            return get_db()
        except ImportError:
            return None

    # ── 工具方法 ──────────────────────────────────────────

    def get_last_report(self, tool_name: str) -> dict | None:
        """获取某工具的最后一次评估报告。"""
        return self._results.get(tool_name)

    def get_all_reports(self) -> dict[str, dict]:
        """获取所有已评估的报告。"""
        return dict(self._results)
