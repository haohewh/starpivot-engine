#!/usr/bin/env python3
"""MCP Server: marketplace_server — 工具市场

提供工具发布、安装、搜索、评分、排行榜、审核功能。
通过 tool_install 安装的工具自动注册到 ToolRegistry。

启动方式:
    python -m mcp_servers.marketplace_server
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys

sys.path.insert(0, "/opt/starpivot")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("marketplace_server")

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
except ImportError:
    print("缺少 mcp Python 库，请运行: pip install mcp", file=sys.stderr)
    sys.exit(1)

app = Server("marketplace_server")


def _get_manager():
    """获取 MarketplaceManager 实例。"""
    from core.starpivot.marketplace import MarketplaceManager
    mgr = MarketplaceManager()
    try:
        from core.starpivot.registry import ToolRegistry
        # 尝试获取全局注册表
        import __main__ as main_mod
        if hasattr(main_mod, "registry"):
            mgr.set_registry(main_mod.registry)
    except Exception:
        pass
    return mgr


TOOLS = [
    Tool(
        name="tool_publish",
        description="发布工具到市场（提交代码+配置）",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "工具名称"},
                "description": {"type": "string", "description": "工具描述"},
                "author_id": {"type": "string", "description": "作者用户ID"},
                "category": {"type": "string", "description": "分类（search/data/media/code等）"},
                "mcp_server_code": {"type": "string", "description": "MCP Server Python 代码"},
                "config_json": {"type": "string", "description": "JSON 配置字符串"},
            },
            "required": ["name", "mcp_server_code"],
        },
    ),
    Tool(
        name="tool_install",
        description="从市场安装工具（自动注册到引擎）",
        inputSchema={
            "type": "object",
            "properties": {
                "tool_id": {"type": "string", "description": "市场工具 ID"},
                "user_id": {"type": "string", "description": "安装者用户 ID（可选）"},
            },
            "required": ["tool_id"],
        },
    ),
    Tool(
        name="tool_search",
        description="搜索市场上的工具",
        inputSchema={
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "搜索关键词"},
                "category": {"type": "string", "description": "分类过滤"},
                "sort_by": {"type": "string", "description": "排序: stars/downloads/newest", "default": "stars"},
                "limit": {"type": "integer", "description": "返回数量上限", "default": 50},
            },
        },
    ),
    Tool(
        name="tool_rate",
        description="给工具评分（1-5星）",
        inputSchema={
            "type": "object",
            "properties": {
                "tool_id": {"type": "string", "description": "工具 ID"},
                "user_id": {"type": "string", "description": "评价者用户 ID"},
                "rating": {"type": "integer", "description": "评分（1-5）"},
                "comment": {"type": "string", "description": "评价内容"},
            },
            "required": ["tool_id", "user_id", "rating"],
        },
    ),
    Tool(
        name="tool_top",
        description="热门工具排行榜",
        inputSchema={
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "分类过滤（可选）"},
                "limit": {"type": "integer", "description": "返回数量", "default": 20},
            },
        },
    ),
    Tool(
        name="tool_review",
        description="审核工具（管理员）",
        inputSchema={
            "type": "object",
            "properties": {
                "tool_id": {"type": "string", "description": "工具 ID"},
                "reviewer_id": {"type": "string", "description": "审核者用户 ID"},
                "status": {"type": "string", "description": "审核结果: approved/rejected"},
                "comment": {"type": "string", "description": "审核意见"},
            },
            "required": ["tool_id", "reviewer_id", "status"],
        },
    ),
]


@app.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    mgr = _get_manager()

    result = {"success": False, "error": f"未知工具: {name}"}

    if name == "tool_publish":
        result = mgr.publish_tool(
            name=arguments.get("name", ""),
            description=arguments.get("description", ""),
            author_id=arguments.get("author_id", ""),
            category=arguments.get("category", ""),
            mcp_server_code=arguments.get("mcp_server_code", ""),
            config_json=arguments.get("config_json", ""),
        )
    elif name == "tool_install":
        result = mgr.install_tool(
            tool_id=arguments.get("tool_id", ""),
            user_id=arguments.get("user_id", ""),
        )
    elif name == "tool_search":
        result = mgr.search_tools(
            keyword=arguments.get("keyword", ""),
            category=arguments.get("category", ""),
            sort_by=arguments.get("sort_by", "stars"),
            limit=arguments.get("limit", 50),
        )
    elif name == "tool_rate":
        result = mgr.rate_tool(
            tool_id=arguments.get("tool_id", ""),
            user_id=arguments.get("user_id", ""),
            rating=arguments.get("rating", 5),
            comment=arguments.get("comment", ""),
        )
    elif name == "tool_top":
        result = mgr.top_tools(
            category=arguments.get("category", ""),
            limit=arguments.get("limit", 20),
        )
    elif name == "tool_review":
        result = mgr.review_tool(
            tool_id=arguments.get("tool_id", ""),
            reviewer_id=arguments.get("reviewer_id", ""),
            status=arguments.get("status", ""),
            comment=arguments.get("comment", ""),
        )

    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]


async def main() -> None:
    logger.info("marketplace_server 启动中...")
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )
    logger.info("marketplace_server 已关闭")


def _run_main() -> None:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("marketplace_server 收到中断信号，退出")
    except Exception as e:
        logger.error("marketplace_server 异常退出: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    _run_main()
