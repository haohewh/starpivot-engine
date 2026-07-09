"""AI Agent 工具平台 Tools 执行器 — Agent 调用的工具集合

每个内置工具函数返回 ToolResult，
execute_tool 作为统一入口分发调用。
"""

from __future__ import annotations

import ast
import operator
import os
from dataclasses import dataclass, field
from typing import Any


# ──────────────────────────────────────────────
# 返回值定义
# ──────────────────────────────────────────────

@dataclass
class ToolResult:
    """工具调用的标准返回值。"""
    success: bool
    output: str
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """转为 dict，供 execute_tool 统一返回。"""
        return {"success": self.success, "output": self.output, "error": self.error}


# ──────────────────────────────────────────────
# 内置工具函数（每个返回 ToolResult）
# ──────────────────────────────────────────────



# === web tools ===


def web_search(query: str, **kwargs) -> ToolResult:
    """用 Firecrawl API 执行网络搜索。

    优先从环境变量 FIRECRAWL_API_KEY 读取 API key，
    若未设置则返回提示信息。

    Args:
        query: 搜索关键词。

    Returns:
        ToolResult: success=True 时 output 为搜索结果文本。
    """
    api_key = os.environ.get("FIRECRAWL_API_KEY")
    if not api_key:
        return ToolResult(
            success=False,
            output="",
            error="FIRECRAWL_API_KEY 环境变量未设置，无法执行 web_search。"
                   "请先设置 ~/.hermes/.env 中的 FIRECRAWL_API_KEY 并加载环境变量。",
        )

    try:
        import requests
        resp = requests.post(
            "https://api.firecrawl.dev/v1/search",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"query": query, "pageSize": 5},
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("data", [])
            lines: list[str] = []
            for i, item in enumerate(results, 1):
                title = item.get("title", "无标题")
                url = item.get("url", "")
                snippet = item.get("description", item.get("snippet", ""))
                lines.append(f"{i}. {title}")
                if url:
                    lines.append(f"   链接: {url}")
                if snippet:
                    lines.append(f"   摘要: {snippet}")
                lines.append("")
            output = "\n".join(lines) if lines else "未找到相关结果。"
            return ToolResult(success=True, output=output)
        else:
            return ToolResult(
                success=False,
                output="",
                error=f"Firecrawl API 请求失败 (HTTP {resp.status_code}): {resp.text[:300]}",
            )
    except ImportError:
        return ToolResult(
            success=False,
            output="",
            error="缺少 requests 库，请运行: pip install requests",
        )
    except Exception as e:
        return ToolResult(success=False, output="", error=f"web_search 出错: {e}")



def agent_reach_web_read(url: str, **kwargs) -> ToolResult:
    """读取任意网页内容，支持超时和兜底。"""
    try:
        content = None
        # 方式1：Agent-Reach WebChannel（threading 超时）
        try:
            from agent_reach.channels.web import WebChannel
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(lambda: WebChannel().read(url))
                content = future.result(timeout=8)
        except Exception:
            pass
        
        # 方式2：兜底 - 直接用 requests 读
        if not content:
            import requests
            from bs4 import BeautifulSoup
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            resp = requests.get(url, timeout=10, headers=headers)
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            content = soup.get_text(separator="\n", strip=True)
        
        truncated = content[:5000]
        if len(content) > 5000:
            truncated += "\n\n...（内容已截断，完整内容较长）"
        return ToolResult(success=True, output=truncated)
    except ImportError:
        return ToolResult(
            success=False, output="",
            error="缺少 agent_reach 模块，请运行: pip install git+https://github.com/Panniantong/Agent-Reach.git",
        )
    except Exception as e:
        return ToolResult(success=False, output="", error=f"Agent-Reach 网页读取失败: {e}")



def agent_reach_search(query: str, **kwargs) -> ToolResult:
    """搜索互联网（通过 Bing 搜索，无需 API Key）。

    直接请求 Bing 搜索引擎，解析 HTML 提取结果标题、链接和摘要。
    在中国境内可正常访问 cn.bing.com，无需 API Key 或额外安装。

    Args:
        query: 搜索关键词。

    Returns:
        ToolResult: success=True 时 output 为搜索结果。
    """
    try:
        from urllib.parse import quote
        import requests
        from bs4 import BeautifulSoup

        url = "https://cn.bing.com/search?q=" + quote(query)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        resp = requests.get(url, headers=headers, timeout=8)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        results = soup.select("li.b_algo")
        lines: list[str] = []

        if not results:
            # 兜底：尝试另一种常见的 Bing 结果选择器
            results = soup.select(".b_algo")

        for i, item in enumerate(results[:10], 1):
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
            # 如果还是没结果，退回到原始 HTML 文本提取
            body_text = soup.get_text(separator="\n", strip=True)
            lines.append("未解析到结构化搜索结果，返回页面文本片段：")
            lines.append(body_text[:1500])

        output = "\n".join(lines)
        return ToolResult(success=True, output=output)

    except ImportError as e:
        return ToolResult(
            success=False, output="",
            error=f"缺少依赖库: {e}，请运行: pip install requests beautifulsoup4",
        )
    except Exception as e:
        return ToolResult(success=False, output="", error=f"Bing 搜索失败: {e}")




def read_hot_news(dummy: str = "", **_kwargs) -> ToolResult:
    """读取今日热点新闻。用 requests 读取多个新闻源后汇总。"""
    try:
        import requests
        from bs4 import BeautifulSoup
        results = []
        
        # 源1：百度热搜
        try:
            r = requests.get("https://top.baidu.com/board?tab=realtime", timeout=8,
                headers={"User-Agent": "Mozilla/5.0"})
            soup = BeautifulSoup(r.text, "html.parser")
            items = soup.select(".category-wrap_iQLoo .content_1YWBm")
            for item in items[:10]:
                title = item.get_text(strip=True)
                if title:
                    results.append(f"【百度】{title}")
        except:
            pass
        
        # 源2：今日热榜
        try:
            r = requests.get("https://tophub.today/c/news", timeout=8,
                headers={"User-Agent": "Mozilla/5.0"})
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.select("a")[:15]:
                txt = a.get_text(strip=True)
                if txt and len(txt) > 6:
                    results.append(f"【热榜】{txt}")
        except:
            pass
        
        if results:
            return ToolResult(success=True, output="\n".join(results[:20]))
        return ToolResult(success=False, output="", error="无法获取新闻")
    except Exception as e:
        return ToolResult(success=False, output="", error=str(e))

_TOOL_REGISTRY["read_hot_news"] = (
    read_hot_news,
    [
        {"name": "dummy", "type": "string", "description": "任意值", "required": False},
    ],
)
