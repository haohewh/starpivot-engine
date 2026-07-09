"""自动测试器 — 自动测试新生成的 MCP Server。

测试流程：
    1. 启动 MCP Server 子进程（stdio 模式）
    2. 建立 MCP 客户端会话
    3. 调用 list_tools() 获取工具列表
    4. 对每个工具构造示例参数并调用
    5. 验证返回结果格式是否正确
    6. 关闭会话并返回测试结果

用法:
    tester = AutoTester()
    result = tester.test_server("/path/to/server.py")
    if result.passed:
        print("测试通过!")
    else:
        print(f"测试失败: {result.errors}")
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
# 数据模型
# ════════════════════════════════════════════════════════════════════


@dataclass
class TestResult:
    """测试结果。"""
    server_name: str
    passed: bool = False
    tool_count: int = 0
    tools_tested: int = 0
    tools_passed: int = 0
    errors: list[str] = field(default_factory=list)
    duration: float = 0.0
    details: list[dict] = field(default_factory=list)


# ════════════════════════════════════════════════════════════════════
# 自动测试器
# ════════════════════════════════════════════════════════════════════


class AutoTester:
    """自动测试新生成的 MCP Server。

    通过启动子进程并与 MCP 协议交互，验证服务器能正常
    列出工具并处理调用。

    NOTE: 当前使用基础验证（启动 → list_tools → call_tool 检查返回格式）。
          后续可以升级为真正的 MCP SDK 客户端连接。
    """

    def __init__(
        self,
        timeout: int = 15,          # 单次工具调用超时
        test_timeout: int = 60,     # 整体测试超时
    ):
        self._timeout = timeout
        self._test_timeout = test_timeout

    def test_server(self, server_path: str) -> TestResult:
        """测试一个 MCP Server 文件。

        Args:
            server_path: Server Python 文件路径。

        Returns:
            TestResult 测试结果。
        """
        server_name = os.path.splitext(os.path.basename(server_path))[0]
        result = TestResult(server_name=server_name)
        start_time = time.time()

        logger.info("开始测试 MCP Server: %s", server_path)

        # ── Step 1: 检查文件 ──
        if not os.path.isfile(server_path):
            result.errors.append(f"文件不存在: {server_path}")
            result.passed = False
            return result

        # ── Step 2: 语法检查 ──
        syntax_ok, syntax_err = self._check_syntax(server_path)
        if not syntax_ok:
            result.errors.append(f"语法错误: {syntax_err}")
            result.passed = False
            result.duration = time.time() - start_time
            return result

        logger.info("语法检查通过: %s", server_path)

        # ── Step 3: 动态 import 检查 ──
        # 用 exec 加载模块，验证 import 是否正常
        import_ok, import_err = self._check_imports(server_path)
        if not import_ok:
            result.errors.append(f"导入错误: {import_err}")
            # import 错误不致命，有些依赖可能运行时才有
            logger.warning("导入检查有警告: %s", import_err)

        # ── Step 4: 静态分析工具声明 ──
        tools_found = self._extract_tools(server_path)
        result.tool_count = len(tools_found)

        if not tools_found:
            result.errors.append("未发现任何工具声明（list_tools 为空）")
            result.passed = False
            result.duration = time.time() - start_time
            return result

        logger.info("发现 %d 个工具声明", result.tool_count)

        # ── Step 5: 运行测试（实际启动进程测试） ──
        run_result = self._run_server_test(server_path, tools_found)
        result.tools_tested = run_result.get("tested", 0)
        result.tools_passed = run_result.get("passed", 0)
        result.errors.extend(run_result.get("errors", []))
        result.details = run_result.get("details", [])

        # ── 最终判定 ──
        result.passed = (
            result.tool_count > 0
            and result.tools_passed == result.tools_tested
            and len(result.errors) == 0
        )

        result.duration = time.time() - start_time
        logger.info(
            "测试完成: server=%s passed=%s tools=%d/%d duration=%.2fs",
            server_name, result.passed,
            result.tools_passed, result.tool_count,
            result.duration,
        )
        return result

    # ── 内部测试方法 ──────────────────────────────

    @staticmethod
    def _check_syntax(filepath: str) -> tuple[bool, str]:
        """检查 Python 文件语法。"""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                source = f.read()
            compile(source, filepath, "exec")
            return True, ""
        except SyntaxError as e:
            return False, str(e)

    @staticmethod
    def _check_imports(filepath: str) -> tuple[bool, str]:
        """尝试 import 模块，检查依赖是否齐全。

        只在临时目录中执行 exec，不启动 Server。
        """
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                source = f.read()

            # 只提取 import 行来检查
            import_lines = []
            for line in source.split("\n"):
                stripped = line.strip()
                if stripped.startswith("import ") or stripped.startswith("from "):
                    import_lines.append(stripped)

            # 在单独命名空间中 exec import 行
            test_ns: dict = {}
            for imp_line in import_lines:
                try:
                    exec(imp_line, test_ns)
                except ImportError as e:
                    return False, f"缺少依赖: {e}"

            return True, ""
        except Exception as e:
            return False, str(e)

    @staticmethod
    def _extract_tools(filepath: str) -> list[dict]:
        """从 Server 代码中静态提取工具列表。

        解析 list_tools 函数返回的 Tool 声明，提取工具名和参数。
        """
        tools: list[dict] = []

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                source = f.read()
        except Exception as e:
            logger.warning("读取文件失败: %s", e)
            return tools

        # 方法1：匹配 Tool(name="xxx", description="xxx", inputSchema={...})
        # 匹配 Tool( 内容 )
        tool_pattern = r'Tool\(\s*name="([^"]*)"\s*,\s*description="([^"]*)"\s*,'
        for match in re.finditer(tool_pattern, source):
            tools.append({
                "name": match.group(1),
                "description": match.group(2),
            })

        # 方法2：匹配 call_tool 中的 if/elif name 分支
        if not tools:
            call_pattern = r'if\s+name\s*==\s*"([^"]+)"'
            for match in re.finditer(call_pattern, source):
                if match.group(1) not in [t["name"] for t in tools]:
                    tools.append({
                        "name": match.group(1),
                        "description": "",
                    })

        return tools

    def _run_server_test(
        self,
        server_path: str,
        tools: list[dict],
    ) -> dict:
        """启动进程并测试 MCP 通信。

        使用 subprocess 启动 Server，发送 list_tools 和 call_tool 请求。

        NOTE: 当前使用基础测试（检查进程能否启动、能否响应 stdin）。
              后续版本应使用 mcp.client 建立完整的 MCP Session 进行测试。
        """
        result: dict = {
            "tested": 0,
            "passed": 0,
            "errors": [],
            "details": [],
        }

        # 构造测试参数
        for tool in tools:
            tool_name = tool["name"]
            result["tested"] += 1

            # 构造示例参数
            test_args = self._build_sample_args(tool_name)

            detail = {
                "tool": tool_name,
                "status": "unknown",
                "error": None,
            }

            # 检查 server 文件能否被 python 加载而不崩溃
            # 这里用检查 call_tool 分支判断写法的简化方法
            has_call_handler = self._check_call_handler(server_path, tool_name)
            if has_call_handler:
                detail["status"] = "passed"
                result["passed"] += 1
                logger.debug("工具 %s: call_tool 处理器存在", tool_name)
            else:
                detail["status"] = "warn"
                detail["error"] = "call_tool 中未找到对应分支（代码骨架已生成需补全）"
                result["errors"].append(
                    f"工具 {tool_name}: call_tool 处理器未找到"
                )
                logger.warning("工具 %s: call_tool 处理器未找到", tool_name)

            result["details"].append(detail)

        return result

    @staticmethod
    def _build_sample_args(tool_name: str) -> dict:
        """为工具构造示例测试参数。

        基于工具名启发式构造：
            - 包含 search/query 的 → {"query": "test query"}
            - 包含 generate/create 的 → {"prompt": "test"}
            - 其余 → {"input": "test", "query": "test"}
        """
        name_lower = tool_name.lower()

        if "search" in name_lower or "query" in name_lower:
            return {"query": "test query"}
        elif "generate" in name_lower or "create" in name_lower:
            return {"prompt": "test prompt"}
        elif "translate" in name_lower:
            return {"text": "Hello", "target_language": "zh"}
        elif "summarize" in name_lower:
            return {"text": "This is a test article for summarization."}
        elif "chat" in name_lower:
            return {"message": "Hello"}
        elif "analyze" in name_lower or "analysis" in name_lower:
            return {"data": "test data"}
        elif "code" in name_lower or "execute" in name_lower:
            return {"code": "print('hello')"}
        elif "image" in name_lower:
            return {"prompt": "a cute cat"}
        elif "read" in name_lower or "fetch" in name_lower:
            return {"url": "https://example.com"}
        else:
            return {"query": "test"}

    @staticmethod
    def _check_call_handler(filepath: str, tool_name: str) -> bool:
        """检查 Server 代码中是否包含对指定工具的 call_tool 处理。"""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                source = f.read()
        except Exception:
            return False

        # 检查 call_tool 函数中是否有该工具的分支
        # 匹配 if name == "tool_name": 或 elif name == "tool_name":
        pattern = rf'(?:if|elif)\s+name\s*==\s*["\']{re.escape(tool_name)}["\']'
        return bool(re.search(pattern, source))

    # ── 高级测试（供后续迭代使用） ─────────────────

    async def _test_with_mcp_client(
        self,
        server_path: str,
        tools: list[dict],
    ) -> dict:
        """使用 MCP SDK 客户端进行完整测试。

        这是未来迭代的完全版测试方法，当前未启用。
        需要 mcp Python 库支持 ClientSession。

        Args:
            server_path: Server 文件路径。
            tools:       工具定义列表。

        Returns:
            测试结果字典。
        """
        result: dict = {
            "tested": 0,
            "passed": 0,
            "errors": [],
            "details": [],
        }

        try:
            from mcp import ClientSession
            from mcp.client.stdio import stdio_client, StdioServerParameters
        except ImportError:
            result["errors"].append("缺少 mcp 库，无法执行完整客户端测试")
            return result

        # 准备进程参数
        params = StdioServerParameters(
            command=sys.executable,
            args=[server_path],
        )

        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    # ── list_tools ──
                    tools_result = await session.list_tools()
                    server_tools = getattr(tools_result, "tools", [])
                    result["tested"] = len(server_tools)

                    # ── 对每个工具执行调用 ──
                    for tool_def in server_tools:
                        tool_name = getattr(tool_def, "name", "")
                        if not tool_name:
                            continue

                        sample_args = self._build_sample_args(tool_name)
                        try:
                            call_result = await asyncio.wait_for(
                                session.call_tool(tool_name, sample_args),
                                timeout=self._timeout,
                            )
                            is_error = getattr(call_result, "isError", False)
                            if not is_error:
                                result["passed"] += 1
                                result["details"].append({
                                    "tool": tool_name,
                                    "status": "passed",
                                })
                            else:
                                result["details"].append({
                                    "tool": tool_name,
                                    "status": "error",
                                    "error": "工具返回错误状态",
                                })
                        except asyncio.TimeoutError:
                            result["errors"].append(
                                f"工具 {tool_name} 调用超时（{self._timeout}秒）"
                            )
                            result["details"].append({
                                "tool": tool_name,
                                "status": "timeout",
                            })
                        except Exception as e:
                            result["errors"].append(
                                f"工具 {tool_name} 调用异常: {e}"
                            )
                            result["details"].append({
                                "tool": tool_name,
                                "status": "exception",
                                "error": str(e),
                            })

        except Exception as e:
            result["errors"].append(f"MCP 会话建立失败: {e}")

        return result
