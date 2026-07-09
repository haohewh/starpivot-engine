"""星枢 QA 自动审核管道 — QAPipeline。

借鉴来源：
- agentic-qe (⭐404):  AI 驱动的 QA 自动化审核流程

审核流程（五步）：
1. 代码检查（code review）     — 语法 / 风格 / import 检查
2. 安全扫描（security scan）    — 调用 SecurityTestSuite 子集
3. 功能测试（functional test）  — 基本调用测试
4. 性能测试（performance test） — 响应时间基准
5. 兼容性测试（compatibility）  — 多输入格式兼容

用法:
    pipeline = QAPipeline(engine, shield)
    report = pipeline.review_tool("agent_reach_search")
    print(pipeline.generate_report())
"""

from __future__ import annotations

import ast
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class QAPipeline:
    """QA 自动审核管道 — 借鉴 agentic-qe。

    用于工具市场发布前的自动审核流程，
    也可用于引擎内置工具的定期审查。
    """

    def __init__(self, engine=None, shield=None) -> None:
        """初始化 QA 管道。

        Args:
            engine: StarPivotEngine 实例（可选）。
            shield: SecurityShield 实例（可选）。
        """
        self._engine = engine
        self._shield = shield
        self._reviews: dict[str, dict] = {}

    # ─── 完整审查 ──────────────────────────────────────────────

    def review_tool(self, tool_name: str, source_code: str = "") -> dict:
        """审计单个工具（五步审查）。

        流程：
        1. 代码检查         — 解析语法树、检查 import、命名规范
        2. 安全扫描          — Prompt/SQL/XSS/命令注入测试
        3. 功能测试          — 批量调用验证基本功能
        4. 性能测试          — 响应时间 / 成功率
        5. 兼容性测试        — 多种输入格式测试

        Args:
            tool_name: 工具名称（如 "agent_reach_search"）。
            source_code: 工具的源代码（可选，仅代码审查时需要）。

        Returns:
            dict: {
                tool_name, status (pass/warn/fail),
                code_review: {...},
                security_scan: {...},
                functional_test: {...},
                performance_test: {...},
                compatibility_test: {...},
                overall_score: int (0-100),
            }
        """
        logger.info("开始审核工具: %s", tool_name)
        review: dict[str, Any] = {
            "tool_name": tool_name,
            "status": "pass",
            "overall_score": 0,
            "stages": {},
        }

        # Stage 1: 代码审查
        review["stages"]["code_review"] = self._code_review(tool_name, source_code)

        # Stage 2: 安全扫描
        review["stages"]["security_scan"] = self._security_scan(tool_name)

        # Stage 3: 功能测试
        review["stages"]["functional_test"] = self._functional_test(tool_name)

        # Stage 4: 性能测试
        review["stages"]["performance_test"] = self._performance_test(tool_name)

        # Stage 5: 兼容性测试
        review["stages"]["compatibility_test"] = self._compatibility_test(tool_name)

        # 综合评分
        scores = [
            review["stages"]["code_review"].get("score", 0),
            review["stages"]["security_scan"].get("score", 0),
            review["stages"]["functional_test"].get("score", 0),
            review["stages"]["performance_test"].get("score", 0),
            review["stages"]["compatibility_test"].get("score", 0),
        ]
        # 安全分权重更高
        weighted = scores[0] * 0.15 + scores[1] * 0.35 + scores[2] * 0.25 + scores[3] * 0.15 + scores[4] * 0.10
        review["overall_score"] = round(weighted)

        # 综合状态：任何一项 fail 则整体 fail
        stage_statuses = [s.get("status", "pass") for s in review["stages"].values()]
        if "fail" in stage_statuses:
            review["status"] = "fail"
        elif "warn" in stage_statuses:
            review["status"] = "warn"

        self._reviews[tool_name] = review
        logger.info(
            "工具审核完成: %s, 评分 %d/100, 状态 %s",
            tool_name, review["overall_score"], review["status"],
        )
        return review

    # ─── 各阶段 ──────────────────────────────────────────────

    def _code_review(self, tool_name: str, source_code: str) -> dict:
        """代码审查（语法检查 + 风格检查 + import 分析）。

        Returns:
            dict: {status, score, issues: [...], warnings: [...]}
        """
        result: dict[str, Any] = {
            "status": "pass",
            "score": 100,
            "issues": [],
            "warnings": [],
        }

        if not source_code:
            result["warnings"].append("未提供源代码，代码审查跳过")
            result["score"] = 50
            result["status"] = "warn"
            return result

        # 1. Python 语法检查
        try:
            tree = ast.parse(source_code)
        except SyntaxError as e:
            result["issues"].append(f"语法错误: {e}")
            result["score"] = 0
            result["status"] = "fail"
            return result

        # 2. 检查 import 语句
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)

        dangerous_imports = ["os.system", "subprocess", "shutil", "ctypes"]
        for di in dangerous_imports:
            if any(di in imp for imp in imports):
                result["issues"].append(f"危险 import: {di}")
                result["score"] -= 20

        # 3. 检查危险函数调用
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    func_name = f"{self._get_attribute_base(node.func)}.{node.func.attr}"
                    dangerous_calls = ["eval", "exec", "compile", "__import__", "open"]
                    for dc in dangerous_calls:
                        if dc in func_name:
                            is_getattr = "getattr" in func_name
                            if not is_getattr:
                                result["issues"].append(f"危险函数调用: {func_name}")

        # 4. 检查函数/类命名规范
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                if not node.name.isidentifier():
                    result["warnings"].append(f"非标准函数名: {node.name}")
                    result["score"] -= 5
            elif isinstance(node, ast.ClassDef):
                if not node.name[0].isupper():
                    result["warnings"].append(f"类名应大写开头: {node.name}")
                    result["score"] -= 5

        # 5. 检查文件末尾空行
        if not source_code.endswith("\n"):
            result["warnings"].append("文件末尾缺少空行")
            result["score"] -= 5

        result["score"] = max(0, min(100, result["score"]))

        # 降级判定
        if result["issues"]:
            result["status"] = "warn"
        if result["score"] < 50:
            result["status"] = "fail"

        return result

    def _security_scan(self, tool_name: str) -> dict:
        """安全扫描（使用 SecurityTestSuite 的子集）。

        Returns:
            dict: {status, score, result, issues}
        """
        result: dict[str, Any] = {
            "status": "pass",
            "score": 100,
            "issues": [],
            "result": None,
        }

        if self._shield:
            from core.starpivot.eval.security_test import SecurityTestSuite
            suite = SecurityTestSuite(self._shield)
            secure_report = suite.run_all()
            result["result"] = secure_report

            block_rate = secure_report.get("overall_block_rate", 0)
            result["score"] = round(block_rate)
            if block_rate < 80:
                result["status"] = "fail"
                result["issues"].append(f"安全拦截率 {block_rate:.0f}% 低于阈值")
            elif block_rate < 95:
                result["status"] = "warn"
                result["issues"].append(f"安全拦截率 {block_rate:.0f}% 偏低")
        else:
            result["score"] = 50
            result["status"] = "warn"
            result["issues"].append("未配置 SecurityShield，安全扫描未执行")

        return result

    def _functional_test(self, tool_name: str) -> dict:
        """功能测试（基本调用验证）。

        Returns:
            dict: {status, score, call_count, success_count, failures, ...}
        """
        result: dict[str, Any] = {
            "status": "pass",
            "score": 100,
            "call_count": 0,
            "success_count": 0,
            "failures": [],
        }

        if not self._engine:
            result["status"] = "warn"
            result["score"] = 50
            return result

        # 尝试执行基本查询
        test_inputs = [
            {"query": "测试"},
            {"query": "AI"},
            {"query": "Python"},
        ]

        for inp in test_inputs:
            result["call_count"] += 1
            try:
                # 同步包装异步
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # 在已有事件循环中执行
                        fut = asyncio.run_coroutine_threadsafe(
                            self._engine.execute(tool_name, inp), loop
                        )
                        resp = fut.result(timeout=10)
                    else:
                        resp = asyncio.run(self._engine.execute(tool_name, inp))
                except RuntimeError:
                    resp = asyncio.run(self._engine.execute(tool_name, inp))

                if resp is not None:
                    result["success_count"] += 1
                else:
                    result["failures"].append({"input": inp, "error": "空响应"})
            except Exception as e:
                result["failures"].append({"input": inp, "error": str(e)})

        # 评分
        success_rate = result["success_count"] / max(result["call_count"], 1) * 100
        result["score"] = round(success_rate)

        if result["score"] < 50:
            result["status"] = "fail"
        elif result["failures"]:
            result["status"] = "warn"

        return result

    def _performance_test(self, tool_name: str) -> dict:
        """性能测试（响应时间基准）。

        测试标准（借鉴 mcp-bench）：
        - 优秀: < 1s
        - 良好: 1-3s
        - 一般: 3-5s
        - 慢:   > 5s

        Returns:
            dict: {status, score, avg_latency_ms, max_latency_ms, samples}
        """
        result: dict[str, Any] = {
            "status": "pass",
            "score": 100,
            "avg_latency_ms": 0,
            "max_latency_ms": 0,
            "samples": [],
        }

        if not self._engine:
            result["status"] = "warn"
            result["score"] = 50
            return result

        latencies = []
        for _ in range(3):
            try:
                import asyncio
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
            except Exception as e:
                result["samples"].append({"error": str(e)})

        if latencies:
            result["avg_latency_ms"] = round(sum(latencies) / len(latencies), 1)
            result["max_latency_ms"] = round(max(latencies), 1)
            result["samples"] = [round(l, 1) for l in latencies]

            # 评分
            avg = result["avg_latency_ms"]
            if avg < 1000:
                result["score"] = 100
            elif avg < 3000:
                result["score"] = 80
            elif avg < 5000:
                result["score"] = 60
                result["status"] = "warn"
            else:
                result["score"] = 30
                result["status"] = "warn"

        return result

    def _compatibility_test(self, tool_name: str) -> dict:
        """兼容性测试（多种输入格式）。

        测试工具对以下输入格式的兼容性：
        - 空参数
        - 不同数据类型
        - 超长字符串
        - Unicode/特殊字符

        Returns:
            dict: {status, score, tests, passed}
        """
        result: dict[str, Any] = {
            "status": "pass",
            "score": 100,
            "tests": [],
            "passed": 0,
            "total": 0,
        }

        if not self._engine:
            result["status"] = "warn"
            result["score"] = 50
            return result

        # 各种输入格式测试
        test_cases = [
            {"name": "空查询", "params": {"query": ""}},
            {"name": "数字字符串", "params": {"query": "12345"}},
            {"name": "特殊字符", "params": {"query": "!@#$%^&*()"}},
            {"name": "Unicode", "params": {"query": "你好世界🌍"}},
            {"name": "超长查询", "params": {"query": "a" * 500}},
        ]

        for tc in test_cases:
            result["total"] += 1
            try:
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        fut = asyncio.run_coroutine_threadsafe(
                            self._engine.execute(tool_name, tc["params"]), loop
                        )
                        resp = fut.result(timeout=15)
                    else:
                        resp = asyncio.run(self._engine.execute(tool_name, tc["params"]))
                except RuntimeError:
                    resp = asyncio.run(self._engine.execute(tool_name, tc["params"]))

                if resp is not None:
                    result["passed"] += 1
                    result["tests"].append({"name": tc["name"], "status": "ok"})
                else:
                    result["tests"].append({"name": tc["name"], "status": "empty"})
            except Exception as e:
                result["tests"].append({"name": tc["name"], "status": "error", "error": str(e)})

        pass_rate = result["passed"] / max(result["total"], 1) * 100
        result["score"] = round(pass_rate)

        if result["score"] < 60:
            result["status"] = "fail"
        elif result["score"] < 80:
            result["status"] = "warn"

        return result

    # ─── 报告生成 ──────────────────────────────────────────────

    def generate_report(self) -> dict:
        """生成审核报告汇总。

        Returns:
            dict: {
                summary: {total, pass, fail, warn},
                average_score: float,
                details: {tool_name: review},
                recommendations: [str, ...]
            }
        """
        if not self._reviews:
            return {"summary": {"total": 0, "pass": 0, "fail": 0, "warn": 0},
                    "average_score": 0, "details": {}, "recommendations": ["暂无审核记录"]}

        statuses = [r.get("status", "error") for r in self._reviews.values()]
        scores = [r.get("overall_score", 0) for r in self._reviews.values()]

        report = {
            "summary": {
                "total": len(self._reviews),
                "pass": statuses.count("pass"),
                "fail": statuses.count("fail"),
                "warn": statuses.count("warn"),
            },
            "average_score": round(sum(scores) / max(len(scores), 1)),
            "details": dict(self._reviews),
            "recommendations": [],
        }

        for tool_name, review in self._reviews.items():
            if review.get("status") == "fail":
                issues = []
                for stage, stage_result in review.get("stages", {}).items():
                    for issue in stage_result.get("issues", []):
                        issues.append(f"[{stage}] {issue}")
                report["recommendations"].append(
                    f"❌ {tool_name}: 审核未通过 - {'; '.join(issues[:3])}"
                )
            elif review.get("status") == "warn":
                report["recommendations"].append(
                    f"⚠️ {tool_name}: 评分 {review.get('overall_score', 0)}/100，建议改进"
                )

        return report

    # ─── 辅助方法 ──────────────────────────────────────────────

    @staticmethod
    def _get_attribute_base(node: ast.Attribute) -> str:
        """递归获取属性访问的基础名称。"""
        if isinstance(node.value, ast.Name):
            return node.value.id
        elif isinstance(node.value, ast.Attribute):
            return f"{_get_attribute_base(node.value)}.{node.value.attr}"
        return "?"
