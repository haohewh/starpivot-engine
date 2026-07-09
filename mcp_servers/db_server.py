#!/usr/bin/env python3
"""MCP Server: db_server — 数据库查询工具

独立的 MCP Server 进程，通过 stdio 传输层与星枢引擎通信。
提供只读的数据库查询功能，仅允许 SELECT 语句。

启动方式:
    python -m mcp_servers.db_server

复用 core/tools.py 中的 query_database 函数。
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
logger = logging.getLogger("db_server")

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

def _execute_query(sql: str) -> dict:
    """执行只读 SQL 查询。

    安全检查：
    - 只允许 SELECT 语句
    - 最多返回 20 行

    Args:
        sql: SQL SELECT 查询语句。

    Returns:
        dict: 标准工具结果。
    """
    # ── 安全检查：只允许 SELECT ──
    sql_stripped = sql.strip().upper()
    if not sql_stripped.startswith("SELECT"):
        return {"success": False, "output": "", "error": "只允许 SELECT 查询"}

    try:
        from core.tools import query_database
        result = query_database(sql)
        if isinstance(result, dict):
            return result
        return result.to_dict()
    except Exception as e:
        return {"success": False, "output": "", "error": f"查询失败: {e}"}


# ══════════════════════════════════════════════════
# MCP Server 定义
# ══════════════════════════════════════════════════

app = Server("db_server")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """声明此服务器提供的工具列表。"""
    return [
        Tool(
            name="query_database",
            description="执行 SQL 查询（只允许 SELECT 语句，只读）。"
                        "查询 starpivot 数据库，最多返回 20 行结果。",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "SQL SELECT 查询语句",
                    },
                },
                "required": ["query"],
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
    if name not in ("query_database",):
        raise ValueError(f"未知工具: {name}，此服务器仅提供 query_database 工具")

    sql = arguments.get("query", "")
    if not sql or not sql.strip():
        return [TextContent(
            type="text",
            text=json.dumps({"success": False, "output": "", "error": "'sql' 参数不能为空"}, ensure_ascii=False),
        )]

    # 额外安全：服务端再次检查只允许 SELECT
    if not sql.strip().upper().startswith("SELECT"):
        return [TextContent(
            type="text",
            text=json.dumps({"success": False, "output": "", "error": "只允许 SELECT 查询"}, ensure_ascii=False),
        )]

    logger.info("执行数据库查询: sql=%s", sql[:100])
    result = _execute_query(sql)

    return [TextContent(
        type="text",
        text=json.dumps(result, ensure_ascii=False),
    )]


# ══════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════

async def main() -> None:
    """启动 MCP Server（stdio 传输层）。"""
    logger.info("db_server 启动中...")

    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )

    logger.info("db_server 已关闭")


def _run_main() -> None:
    """同步入口（供 __main__ 块调用）。"""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("db_server 收到中断信号，退出")
    except Exception as e:
        logger.error("db_server 异常退出: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    _run_main()
