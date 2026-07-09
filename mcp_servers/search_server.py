#!/usr/bin/env python3
"""MCP Server: search_server — Bing 搜索工具

独立的 MCP Server 进程，通过 stdio 传输层与星枢引擎通信。
提供 agent_reach_search 工具的搜索能力（Bing 搜索，无需 API Key）。

启动方式:
    python -m mcp_servers.search_server

搜索逻辑直接内嵌，无外部依赖（requests + beautifulsoup4），
进程崩溃不影响星枢引擎主进程。
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
logger = logging.getLogger("search_server")

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
# 搜索实现（独立内嵌，不依赖外部核心代码）
# ══════════════════════════════════════════════════

def _bing_search(query: str, max_results: int = 10) -> str:
    """使用 Bing 搜索，无需 API Key。

    Args:
        query: 搜索关键词。
        max_results: 返回结果数量上限（默认 10）。

    Returns:
        格式化后的搜索结果文本。
    """
    try:
        from urllib.parse import quote
        import requests
        from bs4 import BeautifulSoup
    except ImportError as e:
        return f"错误: 缺少依赖库 ({e})，请运行: pip install requests beautifulsoup4"

    url = "https://cn.bing.com/search?q=" + quote(query)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=8)
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        return "错误: 搜索请求超时（8秒）"
    except requests.exceptions.RequestException as e:
        return f"错误: 搜索请求失败: {e}"

    soup = BeautifulSoup(resp.text, "html.parser")
    results = soup.select("li.b_algo")
    if not results:
        results = soup.select(".b_algo")

    lines: list[str] = []
    for i, item in enumerate(results[:max_results], 1):
        title_el = item.select_one("h2 a")
        snippet_el = item.select_one(".b_caption p")
        if title_el:
            title = title_el.get_text(strip=True)
            link = title_el.get("href", "")
            snippet = snippet_el.get_text(strip=True) if snippet_el else ""
            lines.append(f"{i}. {title}")
            if link:
                lines.append(f"   链接: {link}")
            if snippet:
                lines.append(f"   摘要: {snippet[:300]}")
            lines.append("")

    if not lines:
        body_text = soup.get_text(separator="\n", strip=True)
        lines.append("未解析到结构化搜索结果，返回页面文本片段：")
        lines.append(body_text[:1500])

    return "\n".join(lines)


# ══════════════════════════════════════════════════
# MCP Server 定义
# ══════════════════════════════════════════════════

app = Server("search_server")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """声明此服务器提供的工具列表。"""
    return [
        Tool(
            name="agent_reach_search",
            description="搜索互联网（通过 Bing 搜索，无需 API Key）。"
                        "直接请求 Bing 搜索引擎，解析 HTML 提取结果标题、链接和摘要。"
                        "在中国境内可正常访问 cn.bing.com，无需 API Key 或额外安装。",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "返回结果数量上限（1-10，默认 10）",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 10,
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
        name: 工具名称（必须为 agent_reach_search）。
        arguments: 工具参数字典。

    Returns:
        TextContent 列表。

    Raises:
        ValueError: 未知工具名。
    """
    if name not in ("agent_reach_search", "search"):
        raise ValueError(f"未知工具: {name}，此服务器仅提供 agent_reach_search 工具")

    query = arguments.get("query", "")
    if not query or not query.strip():
        return [TextContent(
            type="text",
            text="错误: 'query' 参数不能为空",
        )]

    max_results = min(arguments.get("max_results", 10), 10)

    logger.info("执行搜索: query=%s max_results=%d", query[:50], max_results)
    result_text = _bing_search(query, max_results)

    return [TextContent(
        type="text",
        text=result_text,
    )]


# ══════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════

async def main() -> None:
    """启动 MCP Server（stdio 传输层）。"""
    logger.info("search_server 启动中...")

    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )

    logger.info("search_server 已关闭")


def _run_main() -> None:
    """同步入口（供 __main__ 块调用）。"""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("search_server 收到中断信号，退出")
    except Exception as e:
        logger.error("search_server 异常退出: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    _run_main()
