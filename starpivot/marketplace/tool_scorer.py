"""星枢工具评分系统 — ToolScorer。

借鉴来源：
- ai-agent-benchmark-compendium (⭐165): 50+ 基准测试分类体系

评分维度（0-100 各维度独立评分）：
1. accuracy       — 功能准确性：工具是否按预期工作
2. reliability    — 稳定性：失败率 / 熔断频率
3. security       — 安全性：注入防护 / 安全扫描结果
4. performance    — 性能：响应时间 / 延迟
5. compatibility  — 兼容性：多输入格式 / 多平台兼容

综合评分规则：
- 加权平均（accuracy 25%, reliability 20%, security 25%, performance 20%, compatibility 10%）
- 安全分权重最高（考虑到 AI Agent 工具的特殊风险）

用法:
    scorer = ToolScorer(engine, shield)
    result = scorer.score("agent_reach_search")
    print(result)
    ranking = scorer.rank_tools()
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# ── 评分权重 ──────────────────────────────────────
_WEIGHTS = {
    "accuracy": 0.25,
    "reliability": 0.20,
    "security": 0.25,
    "performance": 0.20,
    "compatibility": 0.10,
}


class ToolScorer:
    """工具评分系统（0-100） — 借鉴 ai-agent-benchmark-compendium。

    提供两个核心方法：
    - score(tool_name)    → 工具的 5 维评分详情
    - rank_tools()        → 工具排行榜（按综合评分排序）

    集成 eval 系统的 benchmark + security + qa 进评分数据源。
    """

    def __init__(self, engine=None, shield=None) -> None:
        """初始化评分系统。

        Args:
            engine: StarPivotEngine 实例（用于执行测试）。
            shield: SecurityShield 实例（用于安全检测）。
        """
        self._engine = engine
        self._shield = shield
        self._cache: dict[str, dict] = {}

    # ─── 单工具评分 ──────────────────────────────────────────────

    def score(self, tool_name: str) -> dict:
        """对单个工具进行综合评分（5 维）。

        评分流程：
        1. 准确性(accuracy) — 功能测试通过率
        2. 稳定性(reliability) — 熔断次数 / 失败率
        3. 安全性(security) — 安全测试拦截率
        4. 性能(performance) — 平均响应时间
        5. 兼容性(compatibility) — 多输入兼容测试通过率

        Args:
            tool_name: 工具名称（如 "agent_reach_search"）。

        Returns:
            dict: {
                tool_name, score_at, dimensions: {...},
                overall: int (0-100), weight: {...}, grade: str
            }
        """
        # 检查缓存
        cached = self._cache.get(tool_name)
        if cached:
            return cached

        dimensions = {
            "accuracy": self._score_accuracy(tool_name),
            "reliability": self._score_reliability(tool_name),
            "security": self._score_security(tool_name),
            "performance": self._score_performance(tool_name),
            "compatibility": self._score_compatibility(tool_name),
        }

        # 加权综合评分
        overall = sum(
            dimensions[d].get("score", 0) * _WEIGHTS[d]
            for d in _WEIGHTS
        )
        overall = round(overall)

        # 等级
        if overall >= 90:
            grade = "S"
        elif overall >= 80:
            grade = "A"
        elif overall >= 70:
            grade = "B"
        elif overall >= 60:
            grade = "C"
        elif overall >= 40:
            grade = "D"
        else:
            grade = "F"

        result = {
            "tool_name": tool_name,
            "score_at": datetime.utcnow().isoformat() + "Z",
            "dimensions": dimensions,
            "overall": overall,
            "grade": grade,
            "weights": dict(_WEIGHTS),
        }

        self._cache[tool_name] = result
        logger.info("工具评分完成: %s → %d/100 (等级 %s)", tool_name, overall, grade)
        return result

    # ─── 各维度评分 ──────────────────────────────────────────────

    def _score_accuracy(self, tool_name: str) -> dict:
        """准确性评分（0-100）：基于功能测试通过率。

        方法：
        - 连续执行 3 次基本调用
        - 通过率 = 成功数 / 总调用数 × 100
        """
        score: int = 50  # 默认中等
        detail: dict[str, Any] = {"method": "functional_test", "score": score}

        if not self._engine:
            detail["note"] = "引擎未配置，使用默认分"
            return detail

        import asyncio

        success = 0
        total = 3
        errors: list[str] = []

        for i in range(total):
            try:
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        fut = asyncio.run_coroutine_threadsafe(
                            self._engine.execute(tool_name, {"query": f"test_{i}"}), loop
                        )
                        resp = fut.result(timeout=10)
                    else:
                        resp = asyncio.run(self._engine.execute(tool_name, {"query": f"test_{i}"}))
                except RuntimeError:
                    resp = asyncio.run(self._engine.execute(tool_name, {"query": f"test_{i}"}))

                if resp is not None:
                    success += 1
                else:
                    errors.append(f"第{i+1}次返回空")
            except Exception as e:
                errors.append(f"第{i+1}次失败: {e}")

        score = round(success / max(total, 1) * 100)
        detail["score"] = score
        detail["success_rate"] = f"{success}/{total}"
        detail["errors"] = errors if errors else None
        return detail

    def _score_reliability(self, tool_name: str) -> dict:
        """稳定性评分（0-100）：基于熔断记录和失败率。

        方法：
        - 检查 CircuitBreaker 的失败计数
        - 检查是否有熔断历史
        - 无失败 = 100, 有熔断 ≤ 30
        """
        score: int = 100
        detail: dict[str, Any] = {
            "method": "circuit_breaker_check",
            "score": score,
            "failure_count": 0,
            "circuit_open": False,
        }

        # 检查引擎熔断器
        if self._engine and hasattr(self._engine, "_circuit_breaker"):
            cb = self._engine._circuit_breaker
            fail_count = getattr(cb, "_failures", {}).get(tool_name, 0)
            is_open = getattr(cb, "is_open", lambda x: False)(tool_name)
            open_until = getattr(cb, "_open_until", {}).get(tool_name)

            detail["failure_count"] = fail_count
            detail["circuit_open"] = is_open

            if is_open:
                score = 10
                detail["note"] = f"熔断器已断开（持续到 {open_until}）"
            elif fail_count >= 2:
                score = 40
                detail["note"] = f"已失败 {fail_count} 次（阈值 3 次）"
            elif fail_count > 0:
                score = 70
                detail["note"] = f"有 {fail_count} 次失败记录"
            else:
                score = 100
                detail["note"] = "无失败记录"
        else:
            # 无熔断器：按引擎检测
            detail["note"] = "未检测到熔断器"
            score = 80

        detail["score"] = score
        return detail

    def _score_security(self, tool_name: str) -> dict:
        """安全性评分（0-100）：基于安全测试拦截率。

        方法：
        - 使用 SecurityTestSuite 运行安全测试
        - 拦截率 × 100 = 安全分
        """
        score: int = 80
        detail: dict[str, Any] = {"method": "security_test", "score": score}

        if self._shield:
            try:
                from core.starpivot.eval.security_test import SecurityTestSuite
                suite = SecurityTestSuite(self._shield)
                report = suite.run_all()
                block_rate = report.get("overall_block_rate", 80)
                score = round(block_rate)
                detail["score"] = score
                detail["block_rate"] = block_rate
                detail["detail"] = report.get("details", {})
            except Exception as e:
                detail["note"] = f"安全测试执行异常: {e}"
                detail["score"] = 50
        else:
            detail["note"] = "SecurityShield 未配置，使用默认分 80"
            detail["score"] = 80

        return detail

    def _score_performance(self, tool_name: str) -> dict:
        """性能评分（0-100）：基于响应时间。

        标准：
        - < 500ms:  100（极快）
        - < 1s:     90（快）
        - < 2s:     75（良好）
        - < 4s:     50（一般）
        - >= 4s:    20（慢）
        """
        score: int = 75
        detail: dict[str, Any] = {"method": "latency_check", "score": score}

        if not self._engine:
            detail["note"] = "引擎未配置，使用默认分"
            return detail

        import asyncio

        latencies: list[float] = []
        for _ in range(3):
            try:
                t0 = time.perf_counter()
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        fut = asyncio.run_coroutine_threadsafe(
                            self._engine.execute(tool_name, {"query": "test"}), loop
                        )
                        fut.result(timeout=10)
                    else:
                        asyncio.run(self._engine.execute(tool_name, {"query": "test"}))
                except RuntimeError:
                    asyncio.run(self._engine.execute(tool_name, {"query": "test"}))
                elapsed = (time.perf_counter() - t0) * 1000
                latencies.append(elapsed)
            except Exception:
                pass

        if latencies:
            avg_latency = sum(latencies) / len(latencies)
            detail["avg_latency_ms"] = round(avg_latency, 1)
            detail["samples_ms"] = [round(l, 1) for l in latencies]

            if avg_latency < 500:
                score = 100
            elif avg_latency < 1000:
                score = 90
            elif avg_latency < 2000:
                score = 75
            elif avg_latency < 4000:
                score = 50
            else:
                score = 20
        else:
            detail["note"] = "性能采样失败"
            score = 30

        detail["score"] = score
        return detail

    def _score_compatibility(self, tool_name: str) -> dict:
        """兼容性评分（0-100）：多输入格式通过率。

        方法：
        - 测试 5 种输入格式（空、数字、特殊字符、Unicode、超长）
        - 兼容率 = 通过数 / 总数 × 100
        """
        score: int = 80
        detail: dict[str, Any] = {"method": "input_compatibility", "score": score}

        if not self._engine:
            detail["note"] = "引擎未配置，使用默认分"
            return detail

        import asyncio

        test_inputs = [
            {"query": ""},
            {"query": "12345"},
            {"query": "!@#$%"},
            {"query": "你好世界🌍"},
            {"query": "a" * 500},
        ]

        passed = 0
        total = len(test_inputs)
        for inp in test_inputs:
            try:
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        fut = asyncio.run_coroutine_threadsafe(
                            self._engine.execute(tool_name, inp), loop
                        )
                        resp = fut.result(timeout=15)
                    else:
                        resp = asyncio.run(self._engine.execute(tool_name, inp))
                except RuntimeError:
                    resp = asyncio.run(self._engine.execute(tool_name, inp))

                if resp is not None:
                    passed += 1
            except Exception:
                pass

        score = round(passed / max(total, 1) * 100)
        detail["score"] = score
        detail["compatibility_rate"] = f"{passed}/{total}"

        return detail

    # ─── 工具排行榜 ──────────────────────────────────────────────

    def rank_tools(self, tool_names: list[str] | None = None) -> list[dict]:
        """工具排行榜（按综合评分降序排列）。

        对一组工具逐一评分并排序。

        Args:
            tool_names: 工具名列表（None 时从 registry 获取全部工具）。

        Returns:
            list[dict]: [
                {rank, tool_name, overall, grade, dimensions},
                ...
            ]
        """
        names = tool_names
        if names is None:
            names = self._discover_tools()

        if not names:
            return []

        logger.info("开始工具排名: %d 个工具", len(names))

        ranked = []
        for name in names:
            try:
                s = self.score(name)
                ranked.append(s)
            except Exception as e:
                logger.warning("工具 %s 评分失败: %s", name, e)

        # 按综合分降序排列
        ranked.sort(key=lambda x: x.get("overall", 0), reverse=True)

        # 添加排名
        for i, item in enumerate(ranked, 1):
            item["rank"] = i

        return ranked

    def _discover_tools(self) -> list[str]:
        """从 ToolRegistry 或 MCP 服务器配置发现工具列表。"""
        tools: list[str] = []

        # 尝试从引擎获取
        if self._engine and hasattr(self._engine, "_registry"):
            registry = self._engine._registry
            tool_defs = registry.list_tools()
            tools = [t.name for t in tool_defs]

        # 回退：扫描 mcp_servers/*.json
        if not tools:
            import glob
            import json
            import os
            config_dir = os.path.join(
                os.path.dirname(__file__), "..", "..", "..", "mcp_servers"
            )
            for json_file in sorted(glob.glob(os.path.join(config_dir, "*.json"))):
                try:
                    with open(json_file) as f:
                        config = json.load(f)
                    if config.get("enabled", True):
                        for t in config.get("tools", []):
                            tools.append(t)
                except Exception:
                    pass

        return sorted(set(tools))

    def clear_cache(self) -> None:
        """清除评分缓存。"""
        self._cache.clear()
        logger.info("评分缓存已清除")
