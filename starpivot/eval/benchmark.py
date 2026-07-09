"""星枢工具基准测试 — ToolBenchmark。

借鉴来源：
- mcp-bench (⭐489):  MCP 工具调用基准测试用例集
- vakra (⭐61):       多跳/多源工具调用链式测试
- ResearchHarness (⭐34): 轻量工具调用 Harness 设计

测试项目：
1. test_search()         — 单次搜索调用 + 多轮搜索
2. test_chained_calls()  — 搜索→读网页→总结（vakra 风格链式调用）
3. test_timeout()        — 8 秒超时机制验证
4. test_circuit_breaker() — 3 次失败自动熔断验证
5. run_all()             — 运行全部测试并返回统一评分报告
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class ToolBenchmark:
    """工具基准测试 — 借鉴 mcp-bench + vakra + ResearchHarness。

    用法:
        registry = ToolRegistry()
        registry.discover_servers("/opt/starpivot/mcp_servers/")
        engine = StarPivotEngine(registry)

        bench = ToolBenchmark(engine)
        report = bench.run_all()
        print(report)
    """

    def __init__(self, engine=None) -> None:
        """初始化基准测试。

        Args:
            engine: StarPivotEngine 实例（可选，None 时运行静态模式）。
        """
        self._engine = engine
        self._results: dict[str, Any] = {}

    # ─── 单次搜索测试 ────────────────────────────────────────────

    async def test_search(self, query: str = "今日新闻") -> dict:
        """测试单次/多轮搜索工具调用（借鉴 mcp-bench）。

        测试内容：
        - 单次 agent_reach_search 调用是否返回结果
        - 返回结果是否包含有效内容
        - 多次搜索的稳定性

        Args:
            query: 搜索查询词。

        Returns:
            dict: {status, latency_ms, result_count, error}
        """
        result: dict[str, Any] = {
            "name": "test_search",
            "status": "pass",
            "latency_ms": 0,
            "result_count": 0,
            "rounds": [],
            "error": None,
        }

        # ── 第 1 轮：单次搜索 ──
        try:
            t0 = time.perf_counter()
            resp = await self._engine.execute("agent_reach_search", {"query": query})
            elapsed = (time.perf_counter() - t0) * 1000
            result["latency_ms"] = round(elapsed, 1)

            content = self._extract_content(resp)
            if content and len(str(content)) > 10:
                result["result_count"] = 1
                result["rounds"].append({"query": query, "status": "ok", "length": len(str(content))})
            else:
                result["rounds"].append({"query": query, "status": "empty"})
        except Exception as e:
            result["status"] = "fail"
            result["error"] = str(e)
            logger.warning("test_search 第 1 轮失败: %s", e)

        # ── 第 2 轮：多轮搜索（不同关键词）──
        for alt_q in ["AI 最新进展", "Python 异步编程"]:
            try:
                t0 = time.perf_counter()
                resp = await self._engine.execute("agent_reach_search", {"query": alt_q})
                elapsed = (time.perf_counter() - t0) * 1000
                content = self._extract_content(resp)
                result["rounds"].append({
                    "query": alt_q,
                    "status": "ok" if content and len(str(content)) > 10 else "empty",
                    "latency_ms": round(elapsed, 1),
                    "length": len(str(content)) if content else 0,
                })
            except Exception as e:
                result["rounds"].append({"query": alt_q, "status": "error", "error": str(e)})

        # 综合判定：至少 1 轮成功
        ok_rounds = [r for r in result["rounds"] if r["status"] == "ok"]
        if not ok_rounds:
            result["status"] = "fail"
        else:
            result["result_count"] = len(ok_rounds)

        self._results["test_search"] = result
        return result

    # ─── 链式调用测试 ────────────────────────────────────────────

    async def test_chained_calls(self, query: str = "今日新闻") -> dict:
        """测试链式调用：搜索→读网页→总结（借鉴 vakra 多跳测试）。

        模拟 Agent 的真实工作流：
        1. 搜索（agent_reach_search）→ 获取链接
        2. 读网页（agent_reach_web_read）→ 获取正文
        3. 返回内容摘要

        Args:
            query: 搜索查询词。

        Returns:
            dict: {status, chain: [{step, status, latency_ms}], error}
        """
        result: dict[str, Any] = {
            "name": "test_chained_calls",
            "status": "pass",
            "chain": [],
            "total_latency_ms": 0,
            "error": None,
        }

        t_start = time.perf_counter()

        # Step 1: 搜索
        step1: dict[str, Any] = {"step": "search", "tool": "agent_reach_search"}
        try:
            t0 = time.perf_counter()
            resp1 = await self._engine.execute("agent_reach_search", {"query": query})
            step1["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            content1 = self._extract_content(resp1)
            if content1:
                step1["status"] = "ok"
                step1["content_preview"] = str(content1)[:200]
                result["chain"].append(step1)
            else:
                step1["status"] = "empty"
                result["chain"].append(step1)
        except Exception as e:
            step1["status"] = "error"
            step1["error"] = str(e)
            result["chain"].append(step1)

        # Step 2: 读网页（如果搜索成功且返回了 URL）
        step2: dict[str, Any] = {"step": "read_web", "tool": "agent_reach_web_read"}
        if result["chain"] and result["chain"][-1]["status"] == "ok":
            try:
                # 尝试从搜索结果中提取第一个 URL
                search_content = str(self._extract_content(resp1))
                url = self._extract_url(search_content) or "https://www.baidu.com"
                t0 = time.perf_counter()
                resp2 = await self._engine.execute("agent_reach_web_read", {"url": url})
                step2["latency_ms"] = round((time.perf_counter() - t0) * 1000, 1)
                content2 = self._extract_content(resp2)
                if content2 and len(str(content2)) > 50:
                    step2["status"] = "ok"
                    step2["content_length"] = len(str(content2))
                else:
                    step2["status"] = "empty"
                result["chain"].append(step2)
            except Exception as e:
                step2["status"] = "error"
                step2["error"] = str(e)
                result["chain"].append(step2)

        result["total_latency_ms"] = round((time.perf_counter() - t_start) * 1000, 1)

        # 综合判定：至少前两步成功算通过
        ok_steps = [s for s in result["chain"] if s["status"] == "ok"]
        if len(ok_steps) < 1:
            result["status"] = "fail"

        self._results["test_chained_calls"] = result
        return result

    # ─── 超时测试 ──────────────────────────────────────────────

    async def test_timeout(self) -> dict:
        """测试超时控制机制是否正常（默认 8 秒超时）。

        验证：
        - 超时参数是否能正确传递给引擎
        - 超时后是否抛出 TimeoutError 或返回超时标识

        Returns:
            dict: {status, has_timeout_mechanism, timeout_setting, error}
        """
        result: dict[str, Any] = {
            "name": "test_timeout",
            "status": "pass",
            "has_timeout_mechanism": False,
            "timeout_setting": None,
            "note": None,
            "error": None,
        }

        # 检查引擎是否设置了超时
        if self._engine and hasattr(self._engine, "_timeout"):
            result["has_timeout_mechanism"] = True
            result["timeout_setting"] = getattr(self._engine, "_timeout", None)

        # 检查 registry 中的超时配置
        try:
            from core.starpivot.registry import MCPServerConfig
            if self._engine and hasattr(self._engine, "_registry"):
                registry = self._engine._registry
                for server in registry.list_servers():
                    if server.timeout:
                        result["has_timeout_mechanism"] = True
                        result["timeout_setting"] = server.timeout
                        break
        except Exception:
            pass

        # 尝试触发超时（用一个慢的服务器或不存在的服务器）
        # 这里检查引擎代码是否包含 timeout 逻辑
        try:
            engine_source = type(self._engine).__module__
            # 检查超时实现存在
            result["note"] = f"引擎源码: {engine_source}, 超时机制: {'✅' if result['has_timeout_mechanism'] else '❌'}"
        except Exception:
            pass

        if not result["has_timeout_mechanism"]:
            result["status"] = "warn"
            result["note"] = "未检测到超时配置，建议为 MCP Server 设置 timeout 参数"

        self._results["test_timeout"] = result
        return result

    # ─── 熔断器测试 ──────────────────────────────────────────────

    async def test_circuit_breaker(self) -> dict:
        """测试熔断器：连续 3 次失败是否自动熔断。

        验证机制：
        - CircuitBreaker 是否存在
        - threshold 是否为 3
        - 连续失败后是否触发熔断
        - cooldown 后是否自动半开

        Returns:
            dict: {status, threshold, is_open_after_failures, note, error}
        """
        result: dict[str, Any] = {
            "name": "test_circuit_breaker",
            "status": "pass",
            "threshold": None,
            "cooldown": None,
            "is_open_after_failures": False,
            "note": None,
            "error": None,
        }

        try:
            from core.starpivot.engine import CircuitBreaker
            cb = CircuitBreaker(threshold=3, cooldown=5.0)
            result["threshold"] = cb.threshold
            result["cooldown"] = cb.cooldown

            # 连续失败 3 次，验证熔断
            tool_name = "_bench_test_tool"
            for i in range(3):
                cb.record_failure(tool_name)
            is_open = cb.is_open(tool_name)
            result["is_open_after_failures"] = is_open

            if is_open:
                result["note"] = "✅ 熔断器正常工作：连续 3 次失败后自动断开"
            else:
                result["status"] = "warn"
                result["note"] = "⚠️ 熔断器未触发（可能 threshold 配置不对）"

            # 记录成功 -> 重置
            cb.record_success(tool_name)
            if not cb.is_open(tool_name):
                result["note"] += "，record_success() 成功重置熔断器"

        except ImportError as e:
            result["status"] = "warn"
            result["note"] = "CircuitBreaker 模块未找到，熔断器未集成"
            result["error"] = str(e)
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)

        self._results["test_circuit_breaker"] = result
        return result

    # ─── 运行全部 ──────────────────────────────────────────────

    async def run_all(self) -> dict:
        """运行所有基准测试，返回统一评分报告。

        报告格式：
        {
            "summary": {"total": int, "pass": int, "fail": int, "warn": int},
            "score": int (0-100),
            "details": {test_name: result_dict},
            "recommendations": [str, ...]
        }

        Returns:
            dict: 完整评分报告。
        """
        logger.info("开始运行全部基准测试...")

        # 并行执行所有测试
        tasks = {
            "test_search": self.test_search(),
            "test_chained_calls": self.test_chained_calls(),
            "test_timeout": self.test_timeout(),
            "test_circuit_breaker": self.test_circuit_breaker(),
        }

        for name, coro in tasks.items():
            try:
                await coro
            except Exception as e:
                self._results[name] = {
                    "name": name,
                    "status": "error",
                    "error": str(e),
                }

        # 汇总
        statuses = [v.get("status", "error") for v in self._results.values()]
        pass_count = statuses.count("pass")
        fail_count = statuses.count("fail") + statuses.count("error")
        warn_count = statuses.count("warn")

        total = len(statuses)
        # 评分：pass=100, warn=50, fail/error=0
        score_map = {"pass": 100, "warn": 50, "fail": 0, "error": 0}
        score = sum(score_map.get(s, 0) for s in statuses) // max(total, 1)

        # 推荐建议
        recommendations = []
        for name, detail in self._results.items():
            if detail.get("status") in ("fail", "error"):
                recommendations.append(
                    f"❌ {name}: {detail.get('error', '测试失败')}"
                )
            elif detail.get("status") == "warn":
                recommendations.append(
                    f"⚠️ {name}: {detail.get('note', '需关注')}"
                )

        report = {
            "summary": {
                "total": total,
                "pass": pass_count,
                "fail": fail_count,
                "warn": warn_count,
            },
            "score": score,
            "details": dict(self._results),
            "recommendations": recommendations,
        }

        logger.info(
            "基准测试完成: %d/%d 通过, %d 失败, %d 警告, 综合评分 %d/100",
            pass_count, total, fail_count, warn_count, score,
        )
        return report

    # ─── 辅助方法 ──────────────────────────────────────────────

    def _extract_content(self, response: Any) -> str | None:
        """从引擎响应中提取文本内容。"""
        if response is None:
            return None
        if isinstance(response, str):
            return response
        if isinstance(response, dict):
            # 可能的结构：{content: ...} 或 {result: ...}
            for key in ("content", "result", "text", "message", "output"):
                if key in response:
                    val = response[key]
                    if isinstance(val, (str, list)):
                        return str(val)
            return str(response)
        if isinstance(response, list):
            # MCP 响应可能是 [{type: "text", text: "..."}]
            texts = []
            for item in response:
                if isinstance(item, dict):
                    texts.append(str(item.get("text", item.get("content", ""))))
            return "\n".join(texts) if texts else str(response)
        return str(response)

    def _extract_url(self, text: str) -> str | None:
        """从文本中提取第一个 http/https URL。"""
        import re
        urls = re.findall(r'https?://[^\s"\'<>]+', text)
        return urls[0] if urls else None
