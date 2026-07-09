"""时速性检测 (Speed Test) — 测量工具调用延迟。

国内目标：<5ms 满分
国际：<50ms 满分

评分标准（国内延迟）：
- ≤5ms:    100 分（旗舰级）
- ≤20ms:   85 分（优秀）
- ≤50ms:   70 分（良好）
- ≤100ms:  50 分（一般）
- ≤200ms:  30 分（较慢）
- >200ms:  10 分（很慢）
- 超时/失败: 0 分
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

from tool_args import TOOL_ARGS


class SpeedTest:
    """时速性检测器。

    测量工具从调用到返回的端到端延迟。
    支持多次测量取中位数，避免偶发波动。
    """

    def __init__(self, engine=None) -> None:
        self._engine = engine
        self._results: dict[str, Any] = {}

    async def evaluate(self, tool_name: str, arguments: dict | None = None, rounds: int = 5) -> dict:
        """评估工具的时速性。

        Args:
            tool_name: 工具名称。
            arguments: 测试参数。
            rounds:    测量次数（默认 5 次取中位数）。

        Returns:
            dict: {score, latency_ms, min_ms, max_ms, avg_ms, median_ms, detail}
        """
        result: dict[str, Any] = {
            "name": "speed_test",
            "tool_name": tool_name,
            "score": 0,
            "latency_ms": 0,
            "min_ms": 0,
            "max_ms": 0,
            "avg_ms": 0,
            "median_ms": 0,
            "rounds": [],
            "error": None,
        }

        if not self._engine:
            result["score"] = 50
            result["latency_ms"] = -1
            result["detail"] = "无引擎连接，使用默认评分"
            self._results[tool_name] = result
            return result

        args = arguments or dict(TOOL_ARGS.get(tool_name, {}))
        latencies: list[float] = []

        for i in range(rounds):
            try:
                t0 = time.perf_counter()
                resp = await self._engine.execute(tool_name, args)
                elapsed = (time.perf_counter() - t0) * 1000

                round_info = {
                    "round": i + 1,
                    "latency_ms": round(elapsed, 2),
                    "success": resp.get("success", False),
                }

                if resp.get("success"):
                    latencies.append(elapsed)
                else:
                    round_info["error"] = resp.get("error", "执行失败")
                result["rounds"].append(round_info)

            except Exception as e:
                result["rounds"].append({
                    "round": i + 1,
                    "latency_ms": -1,
                    "success": False,
                    "error": str(e),
                })

        if not latencies:
            result["score"] = 0
            result["latency_ms"] = -1
            result["error"] = "所有调用均失败"
            self._results[tool_name] = result
            return result

        # 统计数据
        sorted_lat = sorted(latencies)
        n = len(sorted_lat)
        result["min_ms"] = round(sorted_lat[0], 2)
        result["max_ms"] = round(sorted_lat[-1], 2)
        result["avg_ms"] = round(sum(sorted_lat) / n, 2)
        result["median_ms"] = round(sorted_lat[n // 2], 2)
        result["latency_ms"] = result["median_ms"]

        # 评分（国内标准）
        median = result["median_ms"]
        result["score"] = self._score_latency(median)
        result["detail"] = f"中位延迟 {median:.1f}ms (最小 {result['min_ms']:.1f}ms, 最大 {result['max_ms']:.1f}ms)"

        self._results[tool_name] = result
        return result

    # ── 辅助 ─────────────────────────────────────────────────

    @staticmethod
    def _score_latency(latency_ms: float) -> int:
        """根据延迟评分。"""
        if latency_ms <= 5:
            return 100
        if latency_ms <= 20:
            return 85
        if latency_ms <= 50:
            return 70
        if latency_ms <= 100:
            return 50
        if latency_ms <= 200:
            return 30
        return 10
