"""工具市场管理器 — Marketplace Manager。

社区工具发布/安装/搜索/评分/审核业务逻辑。
集成 store/db.py 的 CRUD 和 core/starpivot/registry.py 的 ToolRegistry。
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class MarketplaceManager:
    """工具市场管理器。

    封装所有工具市场操作：
    - 发布工具（提交代码 + 配置）
    - 搜索/浏览工具
    - 安装工具（自动注册到引擎）
    - 评分/评价
    - 审核（管理员）
    - 热门排行榜
    """

    def __init__(self, db=None, registry=None) -> None:
        from store.db import Database
        self._db = db or Database()
        self._registry = registry

    def set_registry(self, registry) -> None:
        """注入 ToolRegistry 引用（由引擎初始化时设置）。"""
        self._registry = registry

    # ── 发布 ────────────────────────────────────────────

    def publish_tool(self, name: str, description: str = "",
                     author_id: str = "", category: str = "",
                     mcp_server_code: str = "",
                     config_json: str = "") -> dict:
        """发布工具到市场。

        Args:
            name: 工具名称。
            description: 功能描述。
            author_id: 作者用户 ID。
            category: 分类（如 search, data, media, code 等）。
            mcp_server_code: MCP Server Python 代码。
            config_json: JSON 配置字符串。

        Returns:
            dict: 创建的工具信息。
        """
        if not name or not name.strip():
            return {"success": False, "error": "工具名称不能为空"}
        if not mcp_server_code or not mcp_server_code.strip():
            return {"success": False, "error": "MCP Server 代码不能为空"}

        try:
            tool = self._db.create_marketplace_tool(
                name=name.strip(),
                description=description.strip(),
                author_id=author_id,
                category=category,
                mcp_server_code=mcp_server_code,
                config_json=config_json,
            )
            logger.info("工具已发布: %s (id=%s, author=%s)", name, tool["id"], author_id)
            return {"success": True, "data": tool}
        except Exception as e:
            logger.error("发布工具失败: %s", e)
            return {"success": False, "error": str(e)}

    # ── 搜索 ────────────────────────────────────────────

    def search_tools(self, keyword: str = "", category: str = "",
                     sort_by: str = "stars", limit: int = 50) -> dict:
        """搜索市场上的工具。

        Args:
            keyword: 搜索关键词。
            category: 分类过滤。
            sort_by: 排序方式（stars / downloads / newest）。
            limit: 返回数量上限。

        Returns:
            dict: {success, data: [tools], total}
        """
        try:
            tools = self._db.search_marketplace_tools(
                keyword=keyword,
                category=category,
                sort_by=sort_by,
                limit=limit,
            )
            return {"success": True, "data": tools, "total": len(tools)}
        except Exception as e:
            logger.error("搜索工具失败: %s", e)
            return {"success": False, "error": str(e), "data": []}

    def get_tool_detail(self, tool_id: str) -> dict:
        """获取工具详情（含评分汇总）。"""
        try:
            tool = self._db.get_marketplace_tool(tool_id)
            if not tool:
                return {"success": False, "error": f"工具不存在: {tool_id}"}
            rating = self._db.get_tool_rating_summary(tool_id)
            reviews = self._db.list_marketplace_reviews(tool_id)
            tool["rating"] = rating
            tool["reviews"] = reviews
            return {"success": True, "data": tool}
        except Exception as e:
            logger.error("获取工具详情失败: %s", e)
            return {"success": False, "error": str(e)}

    def top_tools(self, category: str = "", limit: int = 20) -> dict:
        """获取热门工具排行榜。

        Args:
            category: 分类过滤（可选）。
            limit: 返回数量上限。

        Returns:
            dict: {success, data: [tools]}
        """
        try:
            tools = self._db.list_marketplace_tools(
                status="approved",
                category=category,
                limit=limit,
            )
            return {"success": True, "data": tools}
        except Exception as e:
            logger.error("获取热门工具失败: %s", e)
            return {"success": False, "error": str(e), "data": []}

    def list_pending_tools(self, limit: int = 50) -> dict:
        """列出待审核的工具（管理员用）。"""
        try:
            tools = self._db.list_marketplace_tools(
                status="pending",
                limit=limit,
            )
            return {"success": True, "data": tools}
        except Exception as e:
            logger.error("列出待审核工具失败: %s", e)
            return {"success": False, "error": str(e), "data": []}

    # ── 安装 ────────────────────────────────────────────

    def install_tool(self, tool_id: str, user_id: str = "") -> dict:
        """从市场安装工具。

        流程：
        1. 检查工具存在且状态为 approved。
        2. 将 MCP Server 代码写入 mcp_servers/ 目录。
        3. 生成 JSON 配置，注册到 ToolRegistry。
        4. 递增下载计数。

        Args:
            tool_id: 工具 ID。
            user_id: 安装者用户 ID（可选）。

        Returns:
            dict: {success, message, data: {tool_name, server_name, tool_names}}
        """
        try:
            # 1. 获取工具信息
            tool = self._db.get_marketplace_tool(tool_id)
            if not tool:
                return {"success": False, "error": f"工具不存在: {tool_id}"}
            if tool["status"] != "approved":
                return {"success": False, "error": f"工具状态为 {tool['status']}，不可安装"}

            tool_name = tool["name"]
            server_name = tool_name.lower().replace(" ", "_") + "_server"

            # 2. 写入 MCP Server 代码到 mcp_servers/
            if tool.get("mcp_server_code"):
                import os
                server_file = os.path.join(
                    os.path.dirname(__file__), "..", "..", "..",
                    "mcp_servers", f"{server_name}.py"
                )
                os.makedirs(os.path.dirname(server_file), exist_ok=True)
                with open(server_file, "w", encoding="utf-8") as f:
                    f.write(tool["mcp_server_code"])
                logger.info("已写入 MCP Server 文件: %s", server_file)

            # 3. 注册到 ToolRegistry
            config = {"name": server_name, "transport": "stdio"}
            if tool.get("config_json"):
                try:
                    extra_config = json.loads(tool["config_json"])
                    config.update(extra_config)
                except json.JSONDecodeError:
                    pass

            if self._registry:
                # 推断工具名列表（如果 config_json 中包含 tools 字段）
                config.setdefault("command", f"/opt/starpivot/venv/bin/python")
                config.setdefault("args", ["-m", f"mcp_servers.{server_name}"])
                config.setdefault("tools", [tool_name])
                config.setdefault("timeout", 8)
                config.setdefault("enabled", True)
                self._registry.register_server(server_name, config)
                logger.info("工具已注册到 ToolRegistry: %s", server_name)

                # 同时写 JSON 配置
                import json, os
                config_dir = os.path.join(
                    os.path.dirname(__file__), "..", "..", "..", "mcp_servers"
                )
                config_path = os.path.join(config_dir, f"{server_name}.json")
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)
                logger.info("已写入 MCP JSON 配置: %s", config_path)

            # 4. 递增下载数
            self._db.increment_tool_downloads(tool_id)

            logger.info("工具安装成功: %s (user=%s)", tool_name, user_id)
            return {
                "success": True,
                "message": f"工具 {tool_name} 安装成功",
                "data": {
                    "tool_id": tool_id,
                    "tool_name": tool_name,
                    "server_name": server_name,
                    "tool_names": [tool_name],
                },
            }
        except Exception as e:
            logger.error("安装工具失败: %s", e)
            return {"success": False, "error": str(e)}

    # ── 评分 ────────────────────────────────────────────

    def rate_tool(self, tool_id: str, user_id: str,
                  rating: int, comment: str = "") -> dict:
        """给工具评分。

        Args:
            tool_id: 工具 ID。
            user_id: 评价者用户 ID。
            rating: 评分 (1-5)。
            comment: 评价内容。

        Returns:
            dict: {success, data: review}
        """
        try:
            tool = self._db.get_marketplace_tool(tool_id)
            if not tool:
                return {"success": False, "error": f"工具不存在: {tool_id}"}
            if rating < 1 or rating > 5:
                return {"success": False, "error": "评分必须在 1-5 之间"}
            review = self._db.create_marketplace_review(
                tool_id=tool_id, user_id=user_id,
                rating=rating, comment=comment,
            )
            logger.info("工具评分成功: tool=%s, user=%s, rating=%d", tool_id, user_id, rating)
            return {"success": True, "data": review}
        except Exception as e:
            logger.error("评分失败: %s", e)
            return {"success": False, "error": str(e)}

    # ── 审核 ────────────────────────────────────────────

    def review_tool(self, tool_id: str, reviewer_id: str,
                    status: str, comment: str = "") -> dict:
        """审核工具（管理员操作）。

        Args:
            tool_id: 工具 ID。
            reviewer_id: 审核者用户 ID。
            status: 审核结果（approved / rejected）。
            comment: 审核意见。

        Returns:
            dict: {success, data: updated_tool}
        """
        if status not in ("approved", "rejected"):
            return {"success": False, "error": "审核结果只能是 approved 或 rejected"}
        try:
            tool = self._db.get_marketplace_tool(tool_id)
            if not tool:
                return {"success": False, "error": f"工具不存在: {tool_id}"}
            if tool["status"] != "pending":
                return {"success": False, "error": f"工具状态为 {tool['status']}，无需审核"}
            self._db.update_marketplace_tool(
                tool_id,
                status=status,
            )
            updated = self._db.get_marketplace_tool(tool_id)
            logger.info("工具审核完成: id=%s, status=%s, reviewer=%s", tool_id, status, reviewer_id)
            return {"success": True, "data": updated}
        except Exception as e:
            logger.error("审核失败: %s", e)
            return {"success": False, "error": str(e)}
