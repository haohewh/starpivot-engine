"""星枢引擎 — 执行中枢 (StarPivotEngine)

核心执行引擎，负责:
  1. 连接 MCP Server 并保持会话复用
  2. 执行工具调用（超时控制 8 秒）
  3. 失败自动重试 1 次
  4. 熔断器（连续 3 次失败自动断开）
  5. 并行批量执行

用法:
    registry = ToolRegistry()
    registry.discover_servers("/opt/starpivot/mcp_servers/")

    engine = StarPivotEngine(registry)
    result = await engine.execute("search", {"query": "今日新闻"})
    results = await engine.batch_execute([("tool1", {}), ("tool2", {})])
    await engine.close()
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import time
from dataclasses import dataclass, field
from typing import Any

from .registry import ToolRegistry, ToolDefinition, MCPServerConfig
from .lifesupport.watchdog import Watchdog
from .scheduler import Scheduler

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
# 熔断器
# ════════════════════════════════════════════════════════════════════


class CircuitBreaker:
    """熔断器：连续失败 N 次后断开，不再执行。

    用于防止频频失败的耗操作反复执行。在 cooldown 冷却期
    过后自动半开，下次调用再试一次，成功则关闭熔断。

    默认阈值: 3 次连续失败
    默认冷却: 30 秒

    用法:
        cb = CircuitBreaker(threshold=3, cooldown=30.0)
        if cb.is_open("my_tool"):
            return  # 跳过
        # ... 执行 ...
        if success:
            cb.record_success("my_tool")
        else:
            cb.record_failure("my_tool")  # 可能触发熔断
    """

    def __init__(self, threshold: int = 3, cooldown: float = 30.0) -> None:
        self.threshold = threshold
        self.cooldown = cooldown
        self._failures: dict[str, int] = {}
        self._open_until: dict[str, float] = {}

    def record_failure(self, tool_name: str) -> bool:
        """记录一次失败。

        Args:
            tool_name: 工具名称。

        Returns:
            如果达到阈值触发熔断，返回 True。
        """
        self._failures[tool_name] = self._failures.get(tool_name, 0) + 1
        if self._failures[tool_name] >= self.threshold:
            self._open_until[tool_name] = time.time() + self.cooldown
            logger.warning(
                "熔断器已断开: %s (连续失败 %d 次)",
                tool_name, self._failures[tool_name],
            )
            return True
        logger.info(
            "工具 %s 失败 %d/%d 次",
            tool_name, self._failures[tool_name], self.threshold,
        )
        return False

    def record_success(self, tool_name: str) -> None:
        """记录一次成功，重置失败计数并关闭熔断。"""
        self._failures[tool_name] = 0
        self._open_until.pop(tool_name, None)

    def is_open(self, tool_name: str) -> bool:
        """检查熔断器是否已断开。

        Returns:
            True 表示断开中，应短路不执行。
        """
        if tool_name in self._open_until:
            if time.time() < self._open_until[tool_name]:
                return True
            # 冷却期满，自动半开（下次调用允许尝试）
            self._open_until.pop(tool_name, None)
            self._failures[tool_name] = 0
            logger.info("熔断器半开: %s 冷却期满", tool_name)
        return False

    def reset(self, tool_name: str | None = None) -> None:
        """重置熔断状态。

        Args:
            tool_name: 指定工具的熔断器，None 则全部重置。
        """
        if tool_name:
            self._failures.pop(tool_name, None)
            self._open_until.pop(tool_name, None)
        else:
            self._failures.clear()
            self._open_until.clear()


# ════════════════════════════════════════════════════════════════════
# MCP 会话管理
# ════════════════════════════════════════════════════════════════════


class MCPSession:
    """MCP 客户端会话包装。

    管理到单个 MCP Server 的连接生命周期。
    支持 stdio 和 http/sse 两种传输方式。
    延迟连接：首次调用 call_tool 时才建立连接。
    """

    def __init__(self, server_config: MCPServerConfig) -> None:
        self.config = server_config
        self._session: Any = None  # ClientSession instance
        self._read_stream: Any = None
        self._write_stream: Any = None
        self._connected: bool = False
        self._lock = asyncio.Lock()

    async def ensure_connected(self) -> None:
        """确保已连接到 MCP Server（线程安全）。"""
        if self._connected:
            return

        async with self._lock:
            if self._connected:  # 双重检查
                return
            await self._connect()

    async def _connect(self) -> None:
        """实际建立连接。"""
        from mcp import ClientSession

        transport = self.config.transport

        if transport == "stdio":
            await self._connect_stdio()
        elif transport == "http":
            await self._connect_http()
        else:
            raise ValueError(f"不支持的传输方式: {transport}")

        # 创建 MCP ClientSession
        self._session = ClientSession(self._read_stream, self._write_stream)
        await self._session.__aenter__()
        await self._session.initialize()
        self._connected = True
        logger.info(
            "MCP 会话已建立: %s (%s)",
            self.config.name, transport,
        )

    async def _connect_stdio(self) -> None:
        """通过 stdio 连接 MCP Server。"""
        from mcp.client.stdio import stdio_client, StdioServerParameters

        params = StdioServerParameters(
            command=self.config.command,
            args=self.config.args or [],
        )

        ctx = stdio_client(params)
        self._read_stream, self._write_stream = await ctx.__aenter__()
        # 保存 ctx 以便后续关闭
        self._stdio_ctx = ctx

    async def _connect_http(self) -> None:
        """通过 HTTP/SSE 连接 MCP Server。"""
        from mcp.client.sse import sse_client

        ctx = sse_client(self.config.url)
        self._read_stream, self._write_stream = await ctx.__aenter__()
        self._sse_ctx = ctx

    async def call_tool(
        self, tool_name: str, arguments: dict, timeout: int = 8
    ) -> dict:
        """调用 MCP 工具。

        Args:
            tool_name: 工具名称。
            arguments: 参数字典。
            timeout:   超时秒数（默认 8）。

        Returns:
            结果字典:
                - success (bool): 是否成功。
                - output (str):   输出内容。
                - error (str|None): 错误信息。
        """
        await self.ensure_connected()

        try:
            result = await asyncio.wait_for(
                self._session.call_tool(tool_name, arguments),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            return {
                "success": False,
                "output": "",
                "error": f"工具 {tool_name} 调用超时（{timeout}秒）",
            }
        except Exception as e:
            return {
                "success": False,
                "output": "",
                "error": f"工具 {tool_name} 调用异常: {e}",
            }

        # 解析 MCP CallToolResult
        # MCP SDK 返回的 result 有 isError 字段和 content 列表
        is_error = getattr(result, "isError", False)
        content_list = getattr(result, "content", [])
        output_parts: list[str] = []
        for item in content_list:
            text = getattr(item, "text", "")
            if text:
                output_parts.append(text)

        return {
            "success": not is_error,
            "output": "\n".join(output_parts),
            "error": None if not is_error else (output_parts[0] if output_parts else "工具返回错误"),
        }

    async def close(self) -> None:
        """关闭会话，释放资源。"""
        async with self._lock:
            if self._session:
                try:
                    await self._session.__aexit__(None, None, None)
                except BaseExceptionGroup as eg:
                    logger.warning("关闭 MCP 会话时出现 BaseExceptionGroup: %s", eg)
                except Exception as e:
                    logger.warning("关闭 MCP 会话时出错: %s", e)
                self._session = None

            # 关闭传输层
            for ctx_name in ("_stdio_ctx", "_sse_ctx"):
                ctx = getattr(self, ctx_name, None)
                if ctx:
                    try:
                        await ctx.__aexit__(None, None, None)
                    except BaseExceptionGroup:
                        pass
                    except Exception:
                        pass
                    setattr(self, ctx_name, None)

            self._read_stream = None
            self._write_stream = None
            self._connected = False


# ════════════════════════════════════════════════════════════════════
# 星枢引擎
# ════════════════════════════════════════════════════════════════════


class StarPivotEngine:
    """星枢引擎：工具调用中枢。

    职责:
        1. 代理所有工具调用到对应的 MCP Server。
        2. 管理 MCP 会话池（按服务器复用）。
        3. 熔断保护（连续 3 次失败断开 30 秒）。
        4. 超时控制（8 秒截停）。
        5. 失败自动重试 1 次。
        6. 并行批量执行。

    用法:
        registry = ToolRegistry()
        registry.discover_servers("/opt/starpivot/mcp_servers/")
        engine = StarPivotEngine(registry)
        result = await engine.execute("search", {"query": "新闻"})
        await engine.close()
    """

    def __init__(self, registry: ToolRegistry, enable_watchdog: bool = True, enable_scheduler: bool = True) -> None:
        self.registry = registry
        self._circuit_breaker = CircuitBreaker(threshold=3)
        self._sessions: dict[str, MCPSession] = {}
        self._closed: bool = False
        self._services_started: bool = False

        # ── 生命维持系统 ──
        self.watchdog = Watchdog(self, registry)

        # ── 自调度器 ──
        self.scheduler = Scheduler()

        # ── 安全护盾 ──
        from .security.shield import SecurityShield
        self.security = SecurityShield()

        self._enable_watchdog = enable_watchdog
        self._enable_scheduler = enable_scheduler

    # ── 单次执行 ──────────────────────────────

    async def execute(
        self,
        tool_name: str,
        arguments: dict,
        context: dict | None = None,
    ) -> dict:
        """执行一次工具调用。

        流程:
            1. 查找工具定义
            2. 熔断检查
            3. 获取/创建 MCP 会话
            4. 带超时调用（默认 8 秒）
            5. 失败时自动重试 1 次
            6. 连续失败触发熔断

        Args:
            tool_name: 工具名称。
            arguments: 工具参数。
            context:   上下文（可选，包含用户/会话信息）。

        Returns:
            结果字典:
                - success (bool):      是否成功。
                - output (str):        成功时的输出。
                - error (str|None):    失败时的错误信息。
                - circuit_open (bool):  是否因熔断返回（仅在熔断时出现）。
        """
        # ── 1. 查找工具 ──
        tool_def = self.registry.get_tool(tool_name)
        if tool_def is None:
            return {
                "success": False,
                "output": "",
                "error": f"未找到工具: {tool_name}。可用工具: {[t.name for t in self.registry.list_tools()]}",
            }

        # ── 自动启动后台服务（首次调用 execute 时） ──
        if not self._services_started:
            await self.start_services()

        # ── 2. 熔断检查 ──
        if self._circuit_breaker.is_open(tool_name):
            return {
                "success": False,
                "output": "",
                "error": f"工具 {tool_name} 已被熔断（连续失败超过 3 次，冷却期 30 秒）",
                "circuit_open": True,
            }

        # ── 3. 获取服务器配置 ──
        server_name = tool_def.server_name
        # 内部工具（_TOOL_REGISTRY 中的 Python 函数）直接调用
        if server_name == "_internal_":
            from core.tools import execute_tool as _execute_tool
            # 如果 context 中有 agent_id，从数据库获取完整 agent 信息
            _agent = context or {}
            if _agent and "agent_id" in _agent and "id" not in _agent:
                try:
                    from store.db import get_db
                    db = get_db()
                    agent = db.get_agent(_agent["agent_id"])
                    if agent:
                        _agent = dict(agent)
                except Exception:
                    pass
            try:
                result = _execute_tool(tool_name, arguments, _agent)
                return result
            except Exception as e:
                return {"success": False, "output": "", "error": f"内部工具执行失败: {e}"}
        
        server_config = self.registry.get_server(server_name)
        if server_config is None:
            return {
                "success": False,
                "output": "",
                "error": f"未找到服务器配置: {server_name}（工具 {tool_name} 所属）",
            }

        # ── 4. 获取或创建会话 ──
        session = self._sessions.get(server_name)
        if session is None:
            session = MCPSession(server_config)
            self._sessions[server_name] = session

        # ── 5. 执行（带重试） ──
        timeout = server_config.timeout
        last_error: str | None = None

        for attempt in range(2):  # 第1次正常 + 第2次重试
            try:
                result = await session.call_tool(
                    tool_name, arguments, timeout=timeout,
                )
            except Exception as e:
                last_error = f"工具 {tool_name} 执行异常: {e}"
                logger.warning("%s (尝试 %d/2)", last_error, attempt + 1)
                continue

            if result.get("success"):
                self._circuit_breaker.record_success(tool_name)
                # 尝试用 json-repair 修复工具返回的 JSON 内容
                output = result.get("output", "")
                if output:
                    import json
                    try:
                        json.loads(output)
                    except json.JSONDecodeError:
                        try:
                            from json_repair import repair_json
                            repaired = repair_json(output)
                            # 如果修复成功，替换原输出
                            result["output"] = repaired
                        except Exception:
                            pass
                return result
            else:
                last_error = result.get("error", "未知错误")
                logger.warning(
                    "工具 %s 执行失败: %s (尝试 %d/2)",
                    tool_name, last_error, attempt + 1,
                )

        # ── 6. 全部失败 → 记录熔断 ──
        self._circuit_breaker.record_failure(tool_name)
        return {
            "success": False,
            "output": "",
            "error": last_error or f"工具 {tool_name} 执行失败（已重试 1 次）",
        }

    # ── 批量执行 ──────────────────────────────

    async def batch_execute(
        self, calls: list[tuple[str, dict]]
    ) -> list[dict]:
        """并行执行多个互不依赖的工具调用。

        Args:
            calls:  工具调用列表，每项为 (tool_name, arguments)。

        Returns:
            结果列表，顺序与 calls 一一对应。
        """
        tasks = [
            self.execute(tool_name, arguments)
            for tool_name, arguments in calls
        ]
        return await asyncio.gather(*tasks)

    # ── 生命周期 ──────────────────────────────

    async def close(self) -> None:
        """关闭引擎，释放所有 MCP 会话。"""
        if self._closed:
            return
        self._closed = True

        # 停止后台服务
        await self.stop_services()

        for name, session in list(self._sessions.items()):
            try:
                await session.close()
                logger.info("已关闭 MCP 会话: %s", name)
            except BaseExceptionGroup as eg:
                logger.warning("关闭 %s 会话时出现 BaseExceptionGroup: %s", name, eg)
                for ex in eg.exceptions:
                    logger.warning("  └─ 异常: %s", ex)
            except Exception as e:
                logger.warning("关闭 %s 会话时出错: %s", name, e)
        self._sessions.clear()

    async def __aenter__(self) -> "StarPivotEngine":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    # ── 工具探测 ──────────────────────────────

    async def list_server_tools(
        self, server_name: str
    ) -> list[dict]:
        """查询某个 MCP Server 的完整工具列表。

        连接服务器并调用 list_tools，获取详细的参数 schema。
        结果会自动更新到注册表中。

        Args:
            server_name: 服务器名称。

        Returns:
            工具定义列表（dict 格式）。
        """
        server_config = self.registry.get_server(server_name)
        if server_config is None:
            return []

        session = self._sessions.get(server_name)
        if session is None:
            session = MCPSession(server_config)
            self._sessions[server_name] = session

        await session.ensure_connected()

        try:
            result = await session._session.list_tools()
            tools = getattr(result, "tools", [])
            tool_dicts: list[dict] = []
            for tool in tools:
                tdict = {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.inputSchema,
                }
                tool_dicts.append(tdict)
                # 更新注册表
                self.registry.update_tool_schema(
                    tool.name, tool.inputSchema,
                )
            return tool_dicts
        except Exception as e:
            logger.error("查询服务器 %s 工具列表失败: %s", server_name, e)
            return []

    # ── 服务生命周期 ──────────────────────────

    async def start_services(self) -> None:
        """启动引擎附带的后台服务。

        包括:
            - Watchdog（生命维持系统）
            - Scheduler（自调度器）

        首次调用 execute() 时会自动调用此方法。
        也可以手动提前调用以控制启动时机。
        """
        if self._services_started:
            return
        self._services_started = True

        if self._enable_watchdog:
            self.watchdog.start()

        if self._enable_scheduler:
            await self.scheduler.start()

        logger.info(
            "星枢引擎服务已启动 (watchdog=%s, scheduler=%s)",
            self._enable_watchdog, self._enable_scheduler,
        )

    async def stop_services(self) -> None:
        """停止所有后台服务。"""
        try:
            await self.watchdog.stop()
        except Exception as e:
            logger.warning("停止 Watchdog 时出错: %s", e)

        try:
            await self.scheduler.stop()
        except Exception as e:
            logger.warning("停止 Scheduler 时出错: %s", e)

        self._services_started = False
        logger.info("星枢引擎服务已停止")
