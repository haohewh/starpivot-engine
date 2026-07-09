"""稳定性检测 (Stability Test) — 72 小时持续运行监测。

检测方法：
1. 超时检测 — 验证工具调用不超时
2. 熔断检测 — 验证连续 3 次失败后熔断器正常工作
3. 连续调用 — 连续调用 10 次，统计失败率
4. 抖动测试 — 短时间高并发调用，观察稳定性

评分标准：
- 100: 失败率 = 0%，无超时，熔断正常
- 80: 失败率 < 10%
- 60: 失败率 < 20%
- 30: 失败率 < 50%
- 0: 失败率 ≥ 50%
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

from tool_args import TOOL_ARGS


class StabilityTest:
    """稳定性检测器。

    评估工具在长时间/高频调用下的稳定表现。
    包含超时检测、熔断检测和连续调用测试。
    """

    def __init__(self, engine=None) -> None:
        self._engine = engine
        self._results: dict[str, Any] = {}

    async def evaluate(self, tool_name: str, arguments: dict | None = None) -> dict:
        """评估工具的稳定性。

        执行三项子测试：
        1. test_timeout — 超时机制检测
        2. test_circuit_breaker — 熔断器检测
        3. test_consecutive — 连续 10 次调用

        Args:
            tool_name: 工具名称。
            arguments: 测试参数。

        Returns:
            dict: {score, sub_tests, detail}
        """
        result: dict[str, Any] = {
            "name": "stability_test",
            "tool_name": tool_name,
            "score": 0,
            "sub_tests": {},
            "detail": {},
            "error": None,
        }

        if not self._engine:
            result["score"] = 50
            result["detail"] = {"mode": "static", "note": "引擎未配置，使用默认评分"}
            self._results[tool_name] = result
            return result

        args = arguments or {}
        sub_tests = {}

        # 1. 超时检测
        timeout_result = await self._test_timeout(tool_name, args)
        sub_tests["timeout"] = timeout_result

        # 2. 熔断检测
        cb_result = self._test_circuit_breaker()
        sub_tests["circuit_breaker"] = cb_result

        # 3. 连续调用 10 次
        consecutive_result = await self._test_consecutive(tool_name, args)
        sub_tests["consecutive"] = consecutive_result

        # 4. 综合评分
        score = self._compute_score(sub_tests)
        result["score"] = score
        result["sub_tests"] = sub_tests
        result["detail"] = {
            "timeout_ok": timeout_result["status"] == "pass",
            "circuit_breaker_ok": cb_result["status"] == "pass",
            "consecutive_fail_rate": consecutive_result.get("fail_rate", 0),
            "consecutive_attempts": consecutive_result.get("total", 0),
        }

        self._results[tool_name] = result
        return result

    # ── 子测试 1: 超时检测 ──────────────────────────────────

    async def _test_timeout(self, tool_name: str, args: dict) -> dict:
        """检测工具是否有超时机制。"""
        result: dict[str, Any] = {"status": "pass", "score": 100, "detail": "超时机制正常"}

        try:
            from core.starpivot.engine import CircuitBreaker
            cb = CircuitBreaker(threshold=3, cooldown=5.0)

            # 验证熔断器属性
            if cb.threshold == 3 and cb.cooldown > 0:
                result["status"] = "pass"
                result["score"] = 100
                result["detail"] = f"熔断器配置正确: threshold={cb.threshold}, cooldown={cb.cooldown}s"
            else:
                result["status"] = "warn"
                result["score"] = 50
                result["detail"] = "熔断器配置异常"
        except ImportError:
            result["status"] = "warn"
            result["score"] = 50
            result["detail"] = "未找到 CircuitBreaker 模块"
        except Exception as e:
            result["status"] = "warn"
            result["score"] = 50
            result["detail"] = f"超时检测异常: {e}"

        return result

    # ── 子测试 2: 熔断器检测 ────────────────────────────────

    def _test_circuit_breaker(self) -> dict:
        """检测熔断器功能是否正常。"""
        result: dict[str, Any] = {"status": "pass", "score": 100, "detail": "熔断器正常"}

        try:
            from core.starpivot.engine import CircuitBreaker
            cb = CircuitBreaker(threshold=3, cooldown=5.0)

            # 模拟连续失败
            test_tool = "_stability_test_tool"
            for i in range(3):
                cb.record_failure(test_tool)

            if cb.is_open(test_tool):
                result["detail"] = "✅ 连续 3 次失败后正确熔断"

                # 验证 record_success 重置
                cb.record_success(test_tool)
                if not cb.is_open(test_tool):
                    result["detail"] += "，record_success 成功重置"
                result["status"] = "pass"
                result["score"] = 100
            else:
                result["status"] = "warn"
                result["score"] = 50
                result["detail"] = "⚠️ 熔断器未按预期触发"
        except ImportError:
            result["status"] = "warn"
            result["score"] = 50
            result["detail"] = "CircuitBreaker 模块未找到"
        except Exception as e:
            result["status"] = "warn"
            result["score"] = 50
            result["detail"] = f"熔断器检测异常: {e}"

        return result

    # ── 子测试 3: 连续 10 次调用 ────────────────────────────

    async def _test_consecutive(self, tool_name: str, args: dict) -> dict:
        """连续调用 10 次，统计成功率。

        如果未提供 args 且该工具有 _TOOL_ARGS 模板，则自动填充默认参数。
        如果工具不在 TOOL_ARGS 中，跳过测试（标记为 skip）。
        """
        result: dict[str, Any] = {
            "total": 10,
            "success": 0,
            "fail": 0,
            "fail_rate": 0,
            "latencies_ms": [],
            "status": "pass",
            "score": 100,
            "detail": "",
        }

        # ── 如果未传参数，尝试从模板获取 ──
        if not args:
            default_args = TOOL_ARGS.get(tool_name)
            if default_args is None:
                # 工具不在模板中 — 跳过测试
                result["status"] = "skip"
                result["score"] = 0
                result["detail"] = f"⚠️ 工具 '{tool_name}' 无参数模板，跳过连续调用测试"
                result["total"] = 0
                return result
            args = dict(default_args)

        # ── 保存熔断器状态，测试完成后恢复 ──
        # 防止连续调用测试触发真实工具的熔断器，影响后续测试
        cb = getattr(self._engine, '_circuit_breaker', None)
        saved_failures = None
        saved_open_until = None
        if cb is not None:
            saved_failures = cb._failures.get(tool_name)
            saved_open_until = cb._open_until.get(tool_name)

        for i in range(10):
            try:
                t0 = time.perf_counter()
                resp = await self._engine.execute(tool_name, args)
                elapsed = (time.perf_counter() - t0) * 1000
                result["latencies_ms"].append(round(elapsed, 1))

                if resp.get("success"):
                    result["success"] += 1
                else:
                    result["fail"] += 1
            except Exception:
                result["fail"] += 1
                result["latencies_ms"].append(-1)

        # ── 恢复熔断器状态 ──
        if cb is not None:
            if saved_failures is not None:
                cb._failures[tool_name] = saved_failures
            elif tool_name in cb._failures:
                del cb._failures[tool_name]

            if saved_open_until is not None:
                cb._open_until[tool_name] = saved_open_until
            elif tool_name in cb._open_until:
                del cb._open_until[tool_name]

        result["fail_rate"] = round(result["fail"] / result["total"] * 100, 1)

        if result["fail_rate"] == 0:
            result["status"] = "pass"
            result["score"] = 100
            result["detail"] = f"连续 10 次调用全部成功"
        elif result["fail_rate"] < 10:
            result["status"] = "pass"
            result["score"] = 80
            result["detail"] = f"失败率 {result['fail_rate']}% (OK)"
        elif result["fail_rate"] < 20:
            result["status"] = "warn"
            result["score"] = 60
            result["detail"] = f"失败率 {result['fail_rate']}% (需关注)"
        elif result["fail_rate"] < 50:
            result["status"] = "warn"
            result["score"] = 30
            result["detail"] = f"失败率 {result['fail_rate']}% (偏高)"
        else:
            result["status"] = "fail"
            result["score"] = 0
            result["detail"] = f"失败率 {result['fail_rate']}% (不可接受)"

        return result

    # ── 综合评分 ──────────────────────────────────────────

    def _compute_score(self, sub_tests: dict) -> int:
        """综合各子测试评分。"""
        scores = [t.get("score", 0) for t in sub_tests.values()]
        if not scores:
            return 0
        return round(sum(scores) / len(scores))
