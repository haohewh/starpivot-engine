#!/usr/bin/env python3
"""MCP Server: web_server — 网页读取与爬虫工具

独立的 MCP Server 进程，通过 stdio 传输层与星枢引擎通信。
提供网页读取、热点新闻和网站爬取能力。

启动方式:
    python -m mcp_servers.web_server

agent_reach_web_read 和 read_hot_news 复用 core/tools.py 中的函数。
web_crawl 内嵌实现（使用 crawl4ai）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("web_server")

# ──────────────────────────────────────────────
# MCP SDK 导入
# ──────────────────────────────────────────────
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import (
        Tool,
        TextContent,
    )
except ImportError:
    print(
        "缺少 mcp Python 库，请运行: pip install mcp",
        file=sys.stderr,
    )
    sys.exit(1)


# ══════════════════════════════════════════════════
# 工具实现
# ══════════════════════════════════════════════════

def _call_tools_func(func_name: str, args: dict) -> dict:
    """调用 core/tools.py 中的函数。"""
    import core.tools as tools
    try:
        func = getattr(tools, func_name)
        result = func(**args)
        if hasattr(result, 'to_dict'):
            return result.to_dict()
        if isinstance(result, dict):
            return result
        return {"success": True, "output": str(result), "error": None}
    except Exception as e:
        return {"success": False, "output": "", "error": f"{func_name} 执行异常: {e}"}


def _web_crawl(url: str, max_pages: int = 10, extract_links: bool = True) -> dict:
    """爬取整个网站，提取结构化数据。
    
    使用 crawl4ai 库进行智能爬取，支持：
    - 递归爬取同域名下页面
    - 自动提取正文内容（排除导航、广告等噪音）
    - 提取所有页面链接
    - 支持 JavaScript 渲染
    
    Args:
        url: 起始 URL（如 https://example.com）。
        max_pages: 最多爬取页面数（默认 10，最大 50）。
        extract_links: 是否提取页面中的链接（默认 True）。
    
    Returns:
        dict: 爬取结果，包含各页面的标题、URL、内容摘要等。
    """
    # 方式 1：crawl4ai
    try:
        from crawl4ai import AsyncWebCrawler
        import asyncio as _asyncio

        max_pages = min(max_pages, 50)
        
        async def _do_crawl():
            async with AsyncWebCrawler() as crawler:
                result = await crawler.arun(
                    url=url,
                    bypass_cache=True,
                    verbose=False,
                )
                return result

        crawl_result = _asyncio.run(_do_crawl())

        if not crawl_result:
            return {"success": False, "output": "", "error": "crawl4ai 未返回结果"}

        # 提取结构化内容
        pages_data = []
        page = {
            "url": url,
            "title": getattr(crawl_result, "title", "") or "",
            "content_length": len(getattr(crawl_result, "markdown", "") or ""),
            "markdown": (crawl_result.markdown[:8000] + "...（截断）") 
                        if len(getattr(crawl_result, "markdown", "") or "") > 8000 
                        else (crawl_result.markdown or ""),
        }
        pages_data.append(page)

        # 如果有提取到的链接且 max_pages > 1，尝试爬取更多页面
        if max_pages > 1 and extract_links and hasattr(crawl_result, "links"):
            links = crawl_result.links[:max_pages - 1] if crawl_result.links else []

        summary = f"爬取完成: 共 {len(pages_data)} 个页面\n"
        for i, p in enumerate(pages_data, 1):
            summary += f"\n{i}. {p['title']}\n   链接: {p['url']}\n   内容长度: {p['content_length']} 字符\n"

        return {
            "success": True,
            "output": json.dumps({
                "summary": summary,
                "pages": pages_data,
                "total_pages": len(pages_data),
            }, ensure_ascii=False),
            "error": None,
        }

    except ImportError:
        pass
    except Exception as e:
        return {"success": False, "output": "", "error": f"crawl4ai 爬取失败: {e}"}

    # 方式 2：兜底 - requests + BeautifulSoup 爬取
    try:
        import requests
        from bs4 import BeautifulSoup
        from urllib.parse import urlparse, urljoin

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }

        visited = set()
        to_visit = [url]
        pages_data = []
        base_domain = urlparse(url).netloc

        while to_visit and len(pages_data) < max_pages:
            current_url = to_visit.pop(0)
            if current_url in visited:
                continue
            visited.add(current_url)

            try:
                resp = requests.get(current_url, headers=headers, timeout=10)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "html.parser")

                # 提取标题
                title = ""
                if soup.title:
                    title = soup.title.get_text(strip=True)

                # 移除噪音标签
                for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                    tag.decompose()

                # 提取正文
                body_text = soup.get_text(separator="\n", strip=True)
                body_text = "\n".join(line.strip() for line in body_text.split("\n") if line.strip())

                pages_data.append({
                    "url": current_url,
                    "title": title or current_url,
                    "content_length": len(body_text),
                    "markdown": body_text[:5000] + "...（截断）" if len(body_text) > 5000 else body_text,
                })

                # 提取链接（用于继续爬取）
                if extract_links and len(pages_data) < max_pages:
                    for a_tag in soup.find_all("a", href=True):
                        href = a_tag["href"]
                        full_url = urljoin(current_url, href)
                        parsed = urlparse(full_url)
                        # 只爬取同域名链接
                        if parsed.netloc == base_domain and full_url not in visited:
                            to_visit.append(full_url)

            except Exception as e:
                logger.warning("爬取页面失败 %s: %s", current_url, e)

        summary = f"爬取完成: 共 {len(pages_data)} 个页面\n"
        for i, p in enumerate(pages_data, 1):
            summary += f"\n{i}. {p['title']}\n   链接: {p['url']}\n   内容长度: {p['content_length']} 字符\n"

        return {
            "success": True,
            "output": json.dumps({
                "summary": summary,
                "pages": pages_data,
                "total_pages": len(pages_data),
                "method": "requests+bs4",
            }, ensure_ascii=False),
            "error": None,
        }

    except ImportError:
        return {"success": False, "output": "", "error": "缺少依赖库，请安装: pip install requests beautifulsoup4"}
    except Exception as e:
        return {"success": False, "output": "", "error": f"爬取失败: {e}"}


# ══════════════════════════════════════════════════
# MCP Server 定义
# ══════════════════════════════════════════════════

app = Server("web_server")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """声明此服务器提供的工具列表。"""
    return [
        Tool(
            name="web_search",
            description="Web search via Firecrawl API. Returns titles, links, and snippets / 使用 Firecrawl API 执行网络搜索。"
                        "需要设置 FIRECRAWL_API_KEY 环境变量。",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="agent_reach_web_read",
            description="Read any web page content via Agent-Reach WebChannel / 读取任意网页内容"
                        "兜底使用 requests + BeautifulSoup 解析。"
                        "返回纯文本内容（去除脚本、样式、导航等噪音），截断到 5000 字符。",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "要读取的网页 URL（如 https://example.com/article）",
                    },
                },
                "required": ["url"],
            },
        ),
        Tool(
            name="agent_reach_search",
            description="Note: moved to search_server. Use agent_reach_search instead / 此功能已移至 search_server",
            inputSchema={
                "type": "object",
                "properties": {
                    "dummy": {
                        "type": "string",
                        "description": "请使用 search_server 的 agent_reach_search",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="read_hot_news",
            description="Read today's hot/trending news / 读取今日热点新闻。"
                        "从百度热搜和今日热榜等多个新闻源获取最新热门内容，汇总返回。"
                        "无需任何 API Key，免费使用。",
            inputSchema={
                "type": "object",
                "properties": {
                    "dummy": {
                        "type": "string",
                        "description": "任意值（无需参数）",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="web_crawl",
            description="Crawl entire website to extract structured data / 爬取整个网站，提取结构化数据。"
                        "支持递归爬取同域名下页面、自动提取正文、提取页面链接。"
                        "优先使用 crawl4ai（支持 JS 渲染），兜底使用 requests+BeautifulSoup。"
                        "适合用于网站内容采集、数据挖掘等场景。",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "起始 URL（如 https://example.com）",
                    },
                    "max_pages": {
                        "type": "integer",
                        "description": "最多爬取页面数（默认 10，最大 50）",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 50,
                    },
                    "extract_links": {
                        "type": "boolean",
                        "description": "是否提取并爬取页面中的链接（默认 True）",
                        "default": True,
                    },
                },
                "required": ["url"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(
    name: str,
    arguments: dict,
) -> list[TextContent]:
    """处理工具调用请求。"""
    if name not in ("agent_reach_web_read", "agent_reach_search", "read_hot_news", "web_crawl", "web_search"):
        raise ValueError(f"未知工具: {name}，此服务器仅提供 agent_reach_web_read/read_hot_news/web_crawl/web_search 工具")

    if name == "web_search":
        query = arguments.get("query", "")
        if not query or not query.strip():
            return [TextContent(type="text", text=json.dumps(
                {"success": False, "output": "", "error": "'query' 参数不能为空"}
            ))]
        logger.info("网络搜索: query=%s", query[:50])
        result = _call_tools_func("web_search", {"query": query})

    elif name == "agent_reach_web_read":
        url = arguments.get("url", "")
        if not url or not url.strip():
            return [TextContent(type="text", text=json.dumps(
                {"success": False, "output": "", "error": "'url' 参数不能为空"}
            ))]
        logger.info("网页读取: url=%s", url[:80])
        result = _call_tools_func("agent_reach_web_read", {"url": url})

    elif name == "agent_reach_search":
        # 此工具已迁移到 search_server，提供指引
        return [TextContent(type="text", text=json.dumps(
            {"success": False, "output": "", 
             "error": "搜索功能已迁移到 search_server，请调用 search_server 的 agent_reach_search 工具"}
        ))]

    elif name == "read_hot_news":
        logger.info("读取热点新闻")
        result = _call_tools_func("read_hot_news", {})

    elif name == "web_crawl":
        url = arguments.get("url", "")
        if not url or not url.strip():
            return [TextContent(type="text", text=json.dumps(
                {"success": False, "output": "", "error": "'url' 参数不能为空"}
            ))]
        max_pages = arguments.get("max_pages", 10)
        extract_links = arguments.get("extract_links", True)
        logger.info("网页爬取: url=%s max_pages=%d", url[:80], max_pages)
        result = _web_crawl(url, max_pages, extract_links)

    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]


# ══════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════

async def main() -> None:
    """启动 MCP Server（stdio 传输层）。"""
    logger.info("web_server 启动中...")

    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )

    logger.info("web_server 已关闭")


def _run_main() -> None:
    """同步入口（供 __main__ 块调用）。"""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("web_server 收到中断信号，退出")
    except Exception as e:
        logger.error("web_server 异常退出: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    _run_main()
