#!/usr/bin/env python3
"""MCP Server: doc_server — 文档转换工具

独立的 MCP Server 进程，通过 stdio 传输层与星枢引擎通信。
提供 PDF 转 Word 文档功能。

启动方式:
    python -m mcp_servers.doc_server

复用 core/tools.py 中的 pdf_to_word 函数。
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
logger = logging.getLogger("doc_server")

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
# 工具调用辅助（带 agent 上下文）
# ══════════════════════════════════════════════════

def _call_tool_with_agent(func, args: dict, user_id: str = "") -> dict:
    """调用 tools.py 中的函数，传入 _agent 上下文。

    pdf_to_word 需要 user_id 进行路径安全限制。

    Args:
        func: tools.py 中的工具函数。
        args: 工具参数字典。
        user_id: 用户 ID。

    Returns:
        dict: 标准工具结果字典。
    """
    from core.tools import ToolResult

    _agent = {"id": "mcp_doc_server", "user_id": user_id}
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

app = Server("doc_server")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """声明此服务器提供的工具列表。"""
    return [
        Tool(
            name="pdf_to_word",
            description="将 PDF 文件转换为 Word 文档（.docx）。"
                        "需要用户身份验证以确定文件访问路径。",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "用户 ID（用于路径安全限制）",
                    },
                    "pdf_path": {
                        "type": "string",
                        "description": "PDF 文件路径（相对于用户目录）",
                    },
                },
                "required": ["user_id", "pdf_path"],
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
    if name not in ("pdf_to_word",):
        raise ValueError(f"未知工具: {name}，此服务器仅提供 pdf_to_word 工具")

    from core.tools import pdf_to_word

    # 提取 user_id
    user_id = arguments.pop("user_id", "")

    logger.info("PDF转Word: pdf_path=%s user_id=%s", arguments.get("pdf_path", ""), user_id)
    result = _call_tool_with_agent(pdf_to_word, arguments, user_id)

    return [TextContent(
        type="text",
        text=json.dumps(result, ensure_ascii=False),
    )]


# ══════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════

async def main() -> None:
    """启动 MCP Server（stdio 传输层）。"""
    logger.info("doc_server 启动中...")

    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )

    logger.info("doc_server 已关闭")


def _run_main() -> None:
    """同步入口（供 __main__ 块调用）。"""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("doc_server 收到中断信号，退出")
    except Exception as e:
        logger.error("doc_server 异常退出: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    _run_main()
