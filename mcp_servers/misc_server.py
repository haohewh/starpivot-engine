#!/usr/bin/env python3
"""MCP Server: misc_server — 杂项工具（无专用 Server 的工具）

独立的 MCP Server 进程，通过 stdio 传输层与星枢引擎通信。
提供 skills_execute, generate_image, call_agent 等剩余工具。

启动方式:
    python -m mcp_servers.misc_server

复用 core/tools.py 中的函数。
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("misc_server")

# ──────────────────────────────────────────────
# MCP SDK 导入
# ──────────────────────────────────────────────
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import (
        Tool,
        TextContent,
        CallToolResult,
        ListToolsResult,
    )
except ImportError:
    print(
        "缺少 mcp Python 库，请运行: pip install mcp",
        file=sys.stderr,
    )
    sys.exit(1)


# ══════════════════════════════════════════════════
# 工具调用辅助
# ══════════════════════════════════════════════════

def _call_tool(func, args: dict) -> dict:
    """调用 tools.py 中的函数并返回标准结果字典。

    Args:
        func: tools.py 中的工具函数。
        args: 工具参数字典。

    Returns:
        dict: 标准工具结果字典。
    """
    from core.tools import ToolResult

    try:
        result = func(**args)
        if isinstance(result, dict):
            return result
        if isinstance(result, ToolResult):
            return result.to_dict()
        return {"success": True, "output": str(result), "error": None}
    except TypeError as e:
        return {"success": False, "output": "", "error": f"参数错误: {e}"}
    except Exception as e:
        return {"success": False, "output": "", "error": f"执行异常: {e}"}


# ══════════════════════════════════════════════════
# MCP Server 定义
# ══════════════════════════════════════════════════

app = Server("misc_server")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """声明此服务器提供的工具列表。"""
    return [
        Tool(
            name="calculate",
            description="安全计算数学表达式。"
                        "只允许数字、四则运算(+-*/)、幂(**)、取模(%)、括号和科学计数法。"
                        "支持常量 pi 和 e。禁止函数调用和危险操作。",
            inputSchema={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "数学表达式字符串，如 '1+2*3' 或 'pi * 2**2'",
                    },
                },
                "required": ["expression"],
            },
        ),
        Tool(
            name="echo",
            description="直接返回输入的文本。用于测试工具调用链路是否正常。",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "要回显的任意文本",
                    },
                },
                "required": ["text"],
            },
        ),
        Tool(
            name="skills_execute",
            description="执行指定的技能（Skill）。"
                        "技能系统是星枢的扩展能力，包括 browser_navigate、"
                        "web_search、read_file 等数百个预定义技能。",
            inputSchema={
                "type": "object",
                "properties": {
                    "skill_id": {
                        "type": "string",
                        "description": "要调用的技能ID，如 browser_navigate、web_search、read_file 等",
                    },
                },
                "required": ["skill_id"],
            },
        ),
        Tool(
            name="generate_image",
            description="通过 LLM 生成 SVG 图片（无需 GPU，无需外部 API）。"
                        "支持多种视觉风格：modern, minimal, colorful, sketch, vintage。",
            inputSchema={
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "图片内容描述（如「一座星空下的山峰」）",
                    },
                    "style": {
                        "type": "string",
                        "description": "视觉风格：modern/minimal/colorful/sketch/vintage",
                        "default": "modern",
                    },
                    "width": {
                        "type": "number",
                        "description": "SVG 画布宽度（默认 800）",
                        "default": 800,
                    },
                    "height": {
                        "type": "number",
                        "description": "SVG 画布高度（默认 600）",
                        "default": 600,
                    },
                },
                "required": ["description"],
            },
        ),
        Tool(
            name="call_agent",
            description="调用另一个 Agent 执行任务。"
                        "支持通知（notify）、请求（request）、审批（approve）、审计（audit）四种任务类型。",
            inputSchema={
                "type": "object",
                "properties": {
                    "target_agent_id": {
                        "type": "string",
                        "description": "目标 Agent 的 ID（如 ST03, ST04, ST05）",
                    },
                    "message": {
                        "type": "string",
                        "description": "要传递的消息内容",
                    },
                    "task_type": {
                        "type": "string",
                        "description": "任务类型：notify=通知, request=请求, approve=审批, audit=审计",
                        "default": "notify",
                    },
                },
                "required": ["target_agent_id", "message"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(
    name: str,
    arguments: dict,
) -> list[TextContent]:
    """处理工具调用请求。

    Args:
        name: 工具名称。
        arguments: 工具参数字典。

    Returns:
        TextContent 列表。

    Raises:
        ValueError: 未知工具名。
    """
    from core.tools import skills_execute, generate_image, call_agent, calculate, echo

    TOOL_MAP = {
        "calculate": calculate,
        "echo": echo,
        "skills_execute": skills_execute,
        "generate_image": generate_image,
        "call_agent": call_agent,
    }

    func = TOOL_MAP.get(name)
    if func is None:
        raise ValueError(
            f"未知工具: {name}，此服务器仅提供 "
            f"calculate/echo/skills_execute/generate_image/call_agent 工具"
        )

    logger.info("执行工具: %s args=%s", name, {k: v for k, v in arguments.items() if k != "message"})
    result = _call_tool(func, arguments)

    return [TextContent(
        type="text",
        text=json.dumps(result, ensure_ascii=False),
    )]


# ══════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════

async def main() -> None:
    """启动 MCP Server（stdio 传输层）。"""
    logger.info("misc_server 启动中...")

    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )

    logger.info("misc_server 已关闭")


def _run_main() -> None:
    """同步入口（供 __main__ 块调用）。"""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("misc_server 收到中断信号，退出")
    except Exception as e:
        logger.error("misc_server 异常退出: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    _run_main()
