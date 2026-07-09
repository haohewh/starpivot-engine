"""兼容性检测 (Integration Test) — 测试工具能否通过星枢引擎正确调用。

测试流程：
1. MCP Server 启动 — 验证服务器能否正常启动
2. 工具列表 — 验证工具是否在注册表中正确注册
3. 工具调用 — 验证工具能接收参数并返回结果
4. 结果返回 — 验证返回格式正确

评分标准：
- 100: 全部四项测试通过
- 75:  工具调用成功但返回数据格式有问题
- 50:  工具能找到但调用失败
- 25:  工具未注册
- 0:   服务器无法启动
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

from tool_args import TOOL_ARGS


class IntegrationTest:
    """兼容性检测器。

    测试工具能否通过星枢引擎正确对接和调用。
    从注册表查询、服务器连接、工具调用三个层面验证。
    """

    def __init__(self, engine=None, registry=None) -> None:
        self._engine = engine
        self._registry = registry
        self._results: dict[str, Any] = {}

    async def evaluate(self, tool_name: str, arguments: dict | None = None) -> dict:
        """评估工具的兼容性。

        Args:
            tool_name: 工具名称。
            arguments: 测试参数。

        Returns:
            dict: {score, sub_tests, detail}
        """
        result: dict[str, Any] = {
            "name": "integration_test",
            "tool_name": tool_name,
            "score": 0,
            "sub_tests": {},
            "detail": "",
            "error": None,
        }

        if not self._engine:
            result["score"] = 50
            result["detail"] = "无引擎连接，使用默认评分"
            self._results[tool_name] = result
            return result

        sub_tests = {}

        # 1. 注册表检测
        reg_result = self._check_registry(tool_name)
        sub_tests["registry"] = reg_result

        if reg_result["status"] == "fail":
            # 工具未注册，跳过后续测试
            result["sub_tests"] = sub_tests
            result["score"] = 25
            result["detail"] = "工具未在注册表中找到"
            self._results[tool_name] = result
            return result

        # 2. 服务器连接检测
        server_result = await self._check_server(tool_name)
        sub_tests["server"] = server_result

        if server_result["status"] == "fail":
            result["sub_tests"] = sub_tests
            result["score"] = 0
            result["detail"] = "服务器无法连接"
            self._results[tool_name] = result
            return result

        # 3. 工具调用检测
        call_args = arguments or dict(TOOL_ARGS.get(tool_name, {}))
        call_result = await self._test_call(tool_name, call_args)
        sub_tests["call"] = call_result

        # 4. 格式检测（只有调用成功时）
        format_result = {"status": "pass", "score": 100}
        if call_result.get("status") == "pass":
            format_result = self._check_format(call_result.get("response", {}))
            sub_tests["format"] = format_result
        else:
            format_result = {"status": "skip", "score": 0, "detail": "调用失败，跳过格式检测"}
            sub_tests["format"] = format_result

        # 综合评分
        result["sub_tests"] = sub_tests
        result["score"] = self._compute_score(sub_tests)
        result["detail"] = f"注册表: {reg_result['status']}, 服务器: {server_result['status']}, 调用: {call_result.get('status')}, 格式: {format_result.get('status')}"

        self._results[tool_name] = result
        return result

    # ── 子测试 1: 注册表检测 ────────────────────────────

    def _check_registry(self, tool_name: str) -> dict:
        """检查工具是否在注册表中。"""
        result: dict[str, Any] = {"status": "pass", "score": 100, "detail": ""}

        try:
            if self._registry:
                tool_def = self._registry.get_tool(tool_name)
            elif hasattr(self._engine, "registry"):
                tool_def = self._engine.registry.get_tool(tool_name)
            else:
                result["status"] = "warn"
                result["score"] = 50
                result["detail"] = "无法访问注册表"
                return result

            if tool_def:
                result["detail"] = f"工具已注册: {tool_def.name}"
            else:
                # 尝试从引擎的 execute 方法获取
                result["status"] = "warn"
                result["score"] = 50
                result["detail"] = "工具未在注册表中直接找到，可能为内部工具"
        except Exception as e:
            result["status"] = "warn"
            result["score"] = 50
            result["detail"] = f"注册表检测异常: {e}"

        return result

    # ── 子测试 2: 服务器连接检测 ────────────────────────

    async def _check_server(self, tool_name: str) -> dict:
        """检查 MCP Server 连接。"""
        result: dict[str, Any] = {"status": "pass", "score": 100, "detail": "服务器可连接"}

        try:
            # 尝试执行一次简单调用
            ping_args = dict(TOOL_ARGS.get(tool_name, {"query": "ping"}))
            resp = await self._engine.execute(tool_name, ping_args)
            if resp.get("circuit_open"):
                result["status"] = "fail"
                result["score"] = 0
                result["detail"] = "服务器已熔断"
            elif resp.get("success") is False:
                error_msg = resp.get("error", "")
                if "超时" in error_msg:
                    result["status"] = "warn"
                    result["score"] = 50
                    result["detail"] = f"服务器响应超时: {error_msg[:100]}"
                else:
                    result["status"] = "warn"
                    result["score"] = 50
                    result["detail"] = f"服务器响应异常: {error_msg[:100]}"
        except Exception as e:
            result["status"] = "fail"
            result["score"] = 0
            result["detail"] = f"服务器连接失败: {e}"

        return result

    # ── 子测试 3: 工具调用检测 ──────────────────────────

    async def _test_call(self, tool_name: str, arguments: dict) -> dict:
        """测试工具调用。"""
        result: dict[str, Any] = {"status": "pass", "score": 100, "response": {}, "detail": ""}

        try:
            resp = await self._engine.execute(tool_name, arguments)
            result["response"] = resp

            if resp.get("success"):
                result["detail"] = "工具调用成功"
                # 检查是否有实际输出
                output = resp.get("output", "")
                if output and len(str(output).strip()) > 5:
                    result["detail"] += "，有有效输出"
                else:
                    result["status"] = "warn"
                    result["score"] = 75
                    result["detail"] += "，但输出为空或过短"
            else:
                result["status"] = "fail"
                result["score"] = 25
                result["detail"] = f"调用失败: {resp.get('error', '未知错误')[:100]}"
        except Exception as e:
            result["status"] = "fail"
            result["score"] = 0
            result["detail"] = f"调用异常: {e}"

        return result

    # ── 子测试 4: 格式检测 ──────────────────────────────

    def _check_format(self, response: dict) -> dict:
        """检查返回格式是否正确。"""
        result: dict[str, Any] = {"status": "pass", "score": 100, "detail": ""}

        issues = []

        # 检查必要字段
        if "success" not in response:
            issues.append("缺少 success 字段")
        if "output" not in response and "content" not in response and "result" not in response:
            issues.append("缺少输出字段")

        if issues:
            result["status"] = "warn"
            result["score"] = 75
            result["detail"] = "; ".join(issues)
        else:
            result["detail"] = "返回格式正确"

        return result

    # ── 综合评分 ──────────────────────────────────────────

    def _compute_score(self, sub_tests: dict) -> int:
        """综合各子测试评分。"""
        # 各子测试权重
        weights = {
            "registry": 0.1,   # 10%
            "server": 0.2,     # 20%
            "call": 0.4,       # 40%
            "format": 0.3,     # 30%
        }

        total_score = 0.0
        for name, test in sub_tests.items():
            weight = weights.get(name, 0.2)
            score = test.get("score", 0)
            total_score += score * weight

        return round(total_score)
