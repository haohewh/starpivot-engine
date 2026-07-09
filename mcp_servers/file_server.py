#!/usr/bin/env python3
"""MCP Server: file_server — 文件操作工具

独立的 MCP Server 进程，通过 stdio 传输层与星枢引擎通信。
提供文件读取、写入和列表功能。

启动方式:
    python -m mcp_servers.file_server

复用 core/tools.py 中的函数，通过 _agent 上下文传递 user_id。
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
logger = logging.getLogger("file_server")

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
# 工具实现（复用 core/tools.py）
# ══════════════════════════════════════════════════

def _call_tool_with_agent(func, args: dict, user_id: str = "") -> dict:
    """调用 tools.py 中的函数，传入 _agent 上下文。

    Args:
        func: tools.py 中的工具函数。
        args: 工具参数字典。
        user_id: 用户 ID（用于权限控制）。

    Returns:
        dict: 标准工具结果字典 {"success": bool, "output": str, "error": str | None}
    """
    from core.tools import ToolResult

    _agent = {"id": "mcp_file_server", "user_id": user_id}
    try:
        result = func(**args, _agent=_agent)
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

app = Server("file_server")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """声明此服务器提供的工具列表。"""
    return [
        Tool(
            name="read_file",
            description="通用文件读取工具。读取任何可访问的文件（无需 user_id 限制）。"
                        "使用绝对路径或相对于当前工作目录的路径。",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件路径（绝对路径或相对路径）",
                    },
                },
                "required": ["path"],
            },
        ),
        Tool(
            name="read_user_file",
            description="读取用户文件（只允许读取 /opt/starpivot/user_files/ 目录下的文件）。",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "用户 ID（用于路径安全限制）",
                    },
                    "filepath": {
                        "type": "string",
                        "description": "文件路径（相对于用户目录，如 outputs/20260629_notice.md）",
                    },
                },
                "required": ["user_id", "filepath"],
            },
        ),
        Tool(
            name="write_file",
            description="写入文件内容（覆盖写入，自动创建父目录）。"
                        "只允许写入 /opt/starpivot/user_files/{user_id}/outputs/ 目录。",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "用户 ID（用于路径安全限制）",
                    },
                    "path": {
                        "type": "string",
                        "description": "文件路径（相对于用户 outputs 目录）",
                    },
                    "content": {
                        "type": "string",
                        "description": "写入的文本内容",
                    },
                },
                "required": ["user_id", "path", "content"],
            },
        ),
        Tool(
            name="list_files",
            description="列出目录下的文件和文件夹。"
                        "只允许列出 /opt/starpivot/user_files/{user_id}/ 目录。",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "用户 ID（用于路径安全限制）",
                    },
                    "path": {
                        "type": "string",
                        "description": "目录路径（相对于用户目录，默认当前目录）",
                        "default": ".",
                    },
                },
                "required": ["user_id"],
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
    from core.tools import read_file, read_user_file, write_file, list_files

    # 提取 user_id（所有文件工具都需要）
    user_id = arguments.pop("user_id", "")

    if name == "read_file":
        logger.info("通用文件读取: path=%s", arguments.get("path", ""))
        result = _call_tool_with_agent(read_file, arguments, user_id)
    elif name == "read_user_file":
        logger.info("读取用户文件: filepath=%s user_id=%s", arguments.get("filepath", ""), user_id)
        result = _call_tool_with_agent(read_user_file, arguments, user_id)
    elif name == "write_file":
        logger.info("写入文件: path=%s user_id=%s", arguments.get("path", ""), user_id)
        result = _call_tool_with_agent(write_file, arguments, user_id)
    elif name == "list_files":
        logger.info("列出文件: path=%s user_id=%s", arguments.get("path", "."), user_id)
        result = _call_tool_with_agent(list_files, arguments, user_id)
    else:
        raise ValueError(f"未知工具: {name}，此服务器仅提供 read_file/read_user_file/write_file/list_files 工具")

    return [TextContent(
        type="text",
        text=json.dumps(result, ensure_ascii=False),
    )]


# ══════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════

async def main() -> None:
    """启动 MCP Server（stdio 传输层）。"""
    logger.info("file_server 启动中...")

    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )

    logger.info("file_server 已关闭")


def _run_main() -> None:
    """同步入口（供 __main__ 块调用）。"""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("file_server 收到中断信号，退出")
    except Exception as e:
        logger.error("file_server 异常退出: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    _run_main()
