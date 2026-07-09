"""GitHub 扫描器 — 自动发现 GitHub 上的新工具。

搜索策略（不使用 GitHub API，避免被限）：
    1. 用 agent_reach_search（Bing 搜索）搜索 "github trending 2025 tools"
    2. 用 agent_reach_search 按关键词搜索仓库
    3. 解析搜索结果中的仓库链接，获取仓库信息
    4. 分析仓库是否适合作为 MCP Server

后续迭代可以：
    - 缓存搜索结果避免重复扫描
    - 更智能的仓库分析（读 README / 检测 Python SDK）
    - 支持其他平台（GitLab / Gitee）
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
# 数据模型
# ════════════════════════════════════════════════════════════════════


@dataclass
class RepoInfo:
    """仓库基本信息。"""
    full_name: str          # e.g. "owner/repo"
    description: str = ""
    stars: int = 0
    language: str = ""
    url: str = ""
    source: str = ""        # "trending" | "keyword_search"


@dataclass
class RepoAnalysis:
    """仓库分析结果。"""
    name: str               # 生成的 MCP 服务器名称
    repo: RepoInfo
    suitable: bool = False
    reason: str = ""
    has_python_sdk: bool = False
    has_cli_api: bool = False
    has_readme: bool = False
    tool_names: list[str] = field(default_factory=list)
    suggested_tools: list[dict] = field(default_factory=list)


# ════════════════════════════════════════════════════════════════════
# GitHub 扫描器
# ════════════════════════════════════════════════════════════════════


class GitHubScanner:
    """扫描 GitHub 发现新工具。

    使用 agent_reach_search（Bing 搜索）替代 GitHub API，
    搜索时加 "site:github.com" 限定在 GitHub 域内。

    用法:
        scanner = GitHubScanner()
        repos = scanner.scan_trending()
        for repo in repos:
            analysis = scanner.analyze_repo(repo)
            if analysis.suitable:
                print(f"发现适合 MCP 的仓库: {repo.full_name}")
    """

    # 默认搜索关键词列表
    TRENDING_KEYWORDS = [
        "github trending repositories this week",
        "github trending AI tools this month",
    ]
    KEYWORD_TEMPLATES = [
        "site:github.com MCP server tool 2025",
        "site:github.com tool calling AI",
        "site:github.com AI tool SDK Python",
        "site:github.com open source AI tool 2025",
        "site:github.com LLM tool plugin",
    ]

    # 已知适合用 agent_reach_search 扫描的 MCP 类型关键词（简体中文）
    ZH_KEYWORDS = [
        "site:github.com MCP Server AI 工具",
        "site:github.com tool calling 框架",
    ]

    def __init__(
        self,
        cache_ttl: int = 3600,   # 缓存有效期（秒）
        max_results_per_query: int = 10,
    ):
        self._cache: dict[str, tuple[float, list[RepoInfo]]] = {}
        self._cache_ttl = cache_ttl
        self._max_results = max_results_per_query

    # ── 公开 API ──────────────────────────────────

    def scan_trending(self) -> list[RepoInfo]:
        """扫描 GitHub Trending，返回星数增长快的仓库。

        使用所有预定义关键词搜索，去重后返回结果。

        Returns:
            仓库信息列表（已去重，按源顺序排列）。
        """
        seen: set[str] = set()
        results: list[RepoInfo] = []

        for keyword in self.TRENDING_KEYWORDS:
            repos = self._search(keyword, source="trending")
            for repo in repos:
                if repo.full_name not in seen:
                    seen.add(repo.full_name)
                    results.append(repo)

        logger.info(
            "扫描 Trending 完成: 共 %d 个关键词，发现 %d 个独立仓库",
            len(self.TRENDING_KEYWORDS), len(results),
        )
        return results

    def scan_by_keywords(self, keywords: list[str] | None = None) -> list[RepoInfo]:
        """按关键词搜索仓库。

        Args:
            keywords: 关键词列表。None 则使用默认 KEYWORD_TEMPLATES。

        Returns:
            仓库信息列表（已去重）。
        """
        if keywords is None:
            keywords = self.KEYWORD_TEMPLATES + self.ZH_KEYWORDS

        seen: set[str] = set()
        results: list[RepoInfo] = []

        for keyword in keywords:
            repos = self._search(keyword, source="keyword_search")
            for repo in repos:
                if repo.full_name not in seen:
                    seen.add(repo.full_name)
                    results.append(repo)

        logger.info(
            "关键词搜索完成: 共 %d 个关键词，发现 %d 个独立仓库",
            len(keywords), len(results),
        )
        return results

    def analyze_repo(self, repo: RepoInfo) -> RepoAnalysis:
        """分析仓库是否适合作为 MCP Server。

        分析维度：
            - 仓库描述中包含 "MCP"、"tool"、"SDK"、"CLI" 等关键词
            - 主要编程语言是 Python
            - 有 README 文档（通过搜索推断）
            - 有 CLI 或 API 接口

        Args:
            repo: 仓库基本信息。

        Returns:
            RepoAnalysis 分析结果。
        """
        analysis = RepoAnalysis(
            name=self._to_server_name(repo.full_name),
            repo=repo,
        )

        desc_lower = (repo.description or "").lower()

        # ── 判断：MCP 相关 ──
        mcp_keywords = ["mcp", "model context protocol", "tool calling",
                        "function calling", "tool use"]
        has_mcp = any(kw in desc_lower for kw in mcp_keywords)
        if has_mcp:
            analysis.suitable = True
            analysis.reason = "描述包含 MCP/工具调用 关键词"

        # ── 判断：Python SDK ──
        py_keywords = ["python", "sdk", "library", "package", "pip"]
        has_py = any(kw in desc_lower for kw in py_keywords)
        analysis.has_python_sdk = has_py

        # ── 判断：CLI/API ──
        cli_keywords = ["cli", "command line", "api", "rest", "http",
                        "endpoint", "server"]
        has_cli = any(kw in desc_lower for kw in cli_keywords)
        analysis.has_cli_api = has_cli

        # ── 综合判断 ──
        if not analysis.suitable:
            # 如果描述里包含 "tool" + (有 Python 或 CLI)，也视为适合
            if "tool" in desc_lower and (has_py or has_cli):
                analysis.suitable = True
                analysis.reason = "工具类仓库 + Python/CLI"

        if not analysis.suitable:
            # 如果是 Python 项目且有 "AI" 关键词
            if repo.language == "Python" and ("ai" in desc_lower or "llm" in desc_lower):
                analysis.suitable = True
                analysis.reason = "Python AI/LLM 项目，可能有工具接口"

        if not analysis.suitable:
            analysis.reason = "未命中任何适合条件"

        # ── 建议工具名 ──
        if analysis.suitable:
            analysis.tool_names = self._suggest_tool_names(repo, analysis)
            analysis.suggested_tools = [
                {
                    "name": tn,
                    "description": f"由 {repo.full_name} 提供的功能",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": f"{tn} 的输入参数",
                            },
                        },
                        "required": ["query"],
                    },
                }
                for tn in analysis.tool_names
            ]

        logger.info(
            "仓库 %s 分析完成: suitable=%s reason=%s",
            repo.full_name, analysis.suitable, analysis.reason,
        )
        return analysis

    # ── 内部方法 ──────────────────────────────────

    def _search(self, keyword: str, source: str) -> list[RepoInfo]:
        """执行一次搜索。优先从缓存读取。

        Args:
            keyword: 搜索关键词。
            source:  来源标记（"trending" 或 "keyword_search"）。

        Returns:
            解析出的仓库信息列表。
        """
        # 缓存检查
        now = time.time()
        cache_key = f"{source}:{keyword}"
        if cache_key in self._cache:
            cached_time, cached_data = self._cache[cache_key]
            if now - cached_time < self._cache_ttl:
                logger.debug("缓存命中: %s", cache_key)
                return cached_data

        # 执行搜索
        raw_text = self._execute_search(keyword)
        repos = self._parse_github_links(raw_text, source)

        # 写入缓存
        self._cache[cache_key] = (now, repos)
        return repos

    def _execute_search(self, keyword: str) -> str:
        """调用 agent_reach_search 执行搜索。

        Args:
            keyword: 搜索关键词。

        Returns:
            搜索结果的原始文本。
        """
        try:
            from core.tools import agent_reach_search

            # 使用中文 Bing 搜索获得更好结果
            result = agent_reach_search(query=keyword)
            if result.success:
                return result.output
            logger.warning("搜索失败: %s", result.error)
            return ""
        except ImportError:
            logger.warning("无法导入 core.tools.agent_reach_search")
            return ""
        except Exception as e:
            logger.error("搜索异常: %s", e)
            return ""

    def _parse_github_links(self, text: str, source: str) -> list[RepoInfo]:
        """从搜索结果的文本中提取 GitHub 仓库信息。

        解析模式：
            - github.com/owner/repo 链接
            - 描述文本中的项目名、星数信息

        Args:
            text:   搜索结果的原始文本。
            source: 来源标记。

        Returns:
            仓库信息列表。
        """
        repos: list[RepoInfo] = []
        seen: set[str] = set()

        if not text:
            return repos

        # 匹配 GitHub 仓库 URL: github.com/owner/repo
        url_pattern = r'https?://github\.com/([a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+?)(?:\s|/|$)'
        for match in re.finditer(url_pattern, text):
            full_name = match.group(1).rstrip("/")
            if full_name in seen:
                continue
            seen.add(full_name)

            url = f"https://github.com/{full_name}"

            # 尝试从 URL 附近提取描述
            pos = match.start()
            context_start = max(0, pos - 150)
            context_end = min(len(text), pos + 150)
            context = text[context_start:context_end]

            description = self._extract_description(context, full_name)
            stars = self._extract_stars(context)
            language = self._extract_language(context)

            repos.append(RepoInfo(
                full_name=full_name,
                description=description,
                stars=stars,
                language=language,
                url=url,
                source=source,
            ))

        # 如果没解析到 URL，尝试匹配 owner/repo 样式的文本
        if not repos:
            name_pattern = r'([a-zA-Z0-9][a-zA-Z0-9._-]*/[a-zA-Z0-9][a-zA-Z0-9._-]*)'
            for match in re.finditer(name_pattern, text):
                full_name = match.group(1)
                if full_name in seen:
                    continue
                # 排除常见误匹配
                if self._is_likely_repo_name(full_name):
                    seen.add(full_name)
                    repos.append(RepoInfo(
                        full_name=full_name,
                        url=f"https://github.com/{full_name}",
                        source=source,
                    ))

        logger.debug("从搜索结果解析到 %d 个仓库", len(repos))
        return repos

    @staticmethod
    def _extract_description(context: str, full_name: str) -> str:
        """从上下文中提取仓库描述。"""
        # 去掉 URL 本身
        cleaned = context.replace(f"https://github.com/{full_name}", "")
        cleaned = cleaned.replace(f"github.com/{full_name}", "")
        cleaned = cleaned.strip(" \n\t-–—|")

        # 如果描述太长，截断
        if len(cleaned) > 200:
            cleaned = cleaned[:200] + "..."

        return cleaned

    @staticmethod
    def _extract_stars(context: str) -> int:
        """从上下文中提取星数。"""
        # 匹配 "★ 1234" 或 "stars: 1234" 或 "1234 stars"
        patterns = [
            r'★\s*(\d{1,3}(?:,\d{3})*(?:\.\dk?)?)',
            r'(\d[\d,]*)\s*(?:stars?|star)',
            r'(?:stars?|star)\s*[：:]\s*(\d[\d,]*)',
            r'(\d[\d,]*)\s*(?:★|⭐)',
        ]
        for pattern in patterns:
            m = re.search(pattern, context, re.IGNORECASE)
            if m:
                try:
                    return int(m.group(1).replace(",", ""))
                except ValueError:
                    pass
        return 0

    @staticmethod
    def _extract_language(context: str) -> str:
        """从上下文中提取主要编程语言。"""
        known_languages = [
            "Python", "JavaScript", "TypeScript", "Go", "Rust",
            "Java", "C++", "C#", "Ruby", "Kotlin", "Swift",
        ]
        for lang in known_languages:
            if lang in context:
                return lang
        return ""

    @staticmethod
    def _is_likely_repo_name(name: str) -> bool:
        """判断一个字符串是否是合理的仓库名。
        
        仓库名一般格式：owner/repo
        - owner 和 repo 都至少 2 个字符
        - 不包含 @ 等特殊符号
        """
        parts = name.split("/")
        if len(parts) != 2:
            return False
        owner, repo = parts
        if len(owner) < 2 or len(repo) < 2:
            return False
        if "@" in name or "#" in name:
            return False
        return True

    @staticmethod
    def _to_server_name(full_name: str) -> str:
        """将仓库全名转为 MCP Server 名称。
        
        e.g. "owner/mcp-server-tool" → "mcp_server_tool"
        """
        name = full_name.split("/")[-1]
        # 替换非法字符
        name = re.sub(r'[^a-zA-Z0-9_]', '_', name)
        name = re.sub(r'_+', '_', name)
        name = name.strip("_").lower()
        if not name:
            name = "unknown_tool"
        return name

    @staticmethod
    def _suggest_tool_names(repo: RepoInfo, analysis: RepoAnalysis) -> list[str]:
        """根据仓库信息建议工具名称。"""
        server_name = GitHubScanner._to_server_name(repo.full_name)
        base_name = server_name

        # 如果描述包含特定关键词，生成更语义化的工具名
        desc_lower = (repo.description or "").lower()
        if "search" in desc_lower:
            return [f"{base_name}_search"]
        elif "translate" in desc_lower or "translation" in desc_lower:
            return [f"{base_name}_translate"]
        elif "image" in desc_lower or "generate" in desc_lower:
            return [f"{base_name}_generate"]
        elif "chat" in desc_lower or "conversation" in desc_lower:
            return [f"{base_name}_chat"]
        elif "analyze" in desc_lower or "analysis" in desc_lower:
            return [f"{base_name}_analyze"]
        elif "code" in desc_lower or "program" in desc_lower:
            return [f"{base_name}_execute"]
        elif "summarize" in desc_lower:
            return [f"{base_name}_summarize"]
        else:
            return [f"{base_name}_tool"]

    def clear_cache(self) -> None:
        """清空搜索缓存。"""
        self._cache.clear()
        logger.info("搜索缓存已清空")
