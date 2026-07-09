"""星枢引擎 — 工具注册表 (ToolRegistry)

管理所有 MCP Server 提供的工具。支持从 JSON 配置目录自动发现服务器。
每个 MCP Server 配置对应一个 JSON 文件，描述传输方式、命令、工具列表等。

用法:
    registry = ToolRegistry()
    registry.register_server("search", {"command": "python", "args": ["-m", "mcp_server_search"]})
    tool = registry.get_tool("search")
    tools = registry.list_tools()
    count = registry.discover_servers("/opt/starpivot/mcp_servers/")
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 数据模型
# ──────────────────────────────────────────────


@dataclass
class ToolDefinition:
    """工具定义，描述一个可供调用的工具。

    Attributes:
        name:        工具名称（全局唯一）。
        description: 工具功能描述。
        input_schema: JSON Schema 格式的参数定义。
        server_name: 提供该工具的 MCP Server 名称。
    """
    name: str
    description: str
    input_schema: dict = field(default_factory=dict)
    server_name: str = ""


@dataclass
class MCPServerConfig:
    """MCP Server 连接配置。

    Attributes:
        name:      服务器唯一标识。
        transport: 传输方式（"stdio" 或 "http"）。
        command:   stdio 模式的可执行文件路径。
        args:      stdio 模式的命令行参数列表。
        url:       http/sse 模式的端点 URL。
        tools:     该服务器提供的工具名称列表。
        timeout:   调用超时秒数（默认 8）。
        enabled:   是否启用。
    """
    name: str
    transport: str = "stdio"
    command: str | None = None
    args: list[str] | None = None
    url: str | None = None
    tools: list[str] | None = None
    timeout: int = 8
    enabled: bool = True


# ──────────────────────────────────────────────
# 工具注册表
# ──────────────────────────────────────────────


class ToolRegistry:
    """工具注册表，管理所有 MCP Server 提供的工具。

    职责:
        1. 从配置目录自动发现 MCP Server。
        2. 维护 服务器名 → 配置 的映射。
        3. 维护 工具名 → 工具定义 的映射。
        4. 提供按名称查找和全量列举的能力。
    """

    def __init__(self) -> None:
        self._servers: dict[str, MCPServerConfig] = {}
        self._tools: dict[str, ToolDefinition] = {}

    # ── 注册 ─────────────────────────────────

    def register_server(self, name: str, config: dict) -> None:
        """注册一个 MCP Server。

        Args:
            name:   服务器标识名。
            config: 配置字典，支持字段：
                - name (str): 服务器名称（默认等于 name 参数）
                - transport (str): "stdio" 或 "http"
                - command (str): stdio 命令
                - args (list[str]): stdio 参数
                - url (str): HTTP 地址
                - tools (list[str]): 提供的工具名列表
                - timeout (int): 超时秒数
                - enabled (bool): 是否启用
        """
        server_config = MCPServerConfig(
            name=config.get("name", name),
            transport=config.get("transport", "stdio"),
            command=config.get("command"),
            args=config.get("args", []),
            url=config.get("url"),
            tools=config.get("tools"),
            timeout=config.get("timeout", 8),
            enabled=config.get("enabled", True),
        )
        self._servers[name] = server_config
        logger.info("已注册 MCP Server: %s (%s)", name, server_config.transport)

        # 如果配置中明确声明了工具列表，立即注册轻型占位定义
        if server_config.tools:
            for tool_name in server_config.tools:
                if tool_name not in self._tools:
                    self._tools[tool_name] = ToolDefinition(
                        name=tool_name,
                        description=f"由 {name} 提供的工具",
                        input_schema={},
                        server_name=name,
                    )

    def register_tool(self, tool: ToolDefinition) -> None:
        """注册（或更新）一个工具定义。

        Args:
            tool: 工具定义对象。
        """
        self._tools[tool.name] = tool

    # ── 查询 ─────────────────────────────────

    def get_tool(self, name: str) -> ToolDefinition | None:
        """根据工具名查找工具定义。

        Args:
            name: 工具名称。

        Returns:
            ToolDefinition 或 None（未找到时）。
        """
        return self._tools.get(name)

    def list_tools(self) -> list[ToolDefinition]:
        """列出所有已注册的可用工具。

        Returns:
            全部 ToolDefinition 列表。
        """
        return list(self._tools.values())

    def get_server(self, name: str) -> MCPServerConfig | None:
        """根据服务器名获取配置。

        Args:
            name: 服务器标识名。

        Returns:
            MCPServerConfig 或 None。
        """
        return self._servers.get(name)

    def list_servers(self) -> list[MCPServerConfig]:
        """列出所有已注册的 MCP Server。

        Returns:
            全部 MCPServerConfig 列表。
        """
        return list(self._servers.values())

    # ── 自动发现 ─────────────────────────────

    def discover_servers(self, config_dir: str) -> int:
        """从配置目录加载所有 MCP Server 配置。

        扫描 config_dir 下所有 *.json 文件，逐个加载并注册。
        仅注册 enabled=True（或未设置 enabled 字段）的服务器。

        Args:
            config_dir: 配置文件目录路径。

        Returns:
            成功加载的服务器数量。
        """
        if not os.path.isdir(config_dir):
            logger.warning("MCP servers 配置目录不存在: %s", config_dir)
            return 0

        count = 0
        for filename in sorted(os.listdir(config_dir)):
            if not filename.endswith(".json"):
                continue
            filepath = os.path.join(config_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    config = json.load(f)
                if config.get("enabled", True):
                    self.register_server(config["name"], config)
                    count += 1
                    logger.info("从 %s 发现并注册了服务器: %s", filename, config["name"])
            except Exception as e:
                logger.error("加载 MCP Server 配置 %s 失败: %s", filepath, e)

        return count

    # ── 工具辅助 ─────────────────────────────

    def update_tool_schema(
        self, tool_name: str, input_schema: dict
    ) -> bool:
        """更新工具参数的 JSON Schema。

        当 MCP Server 的 initialize 或 list_tools 返回了更详细的
        参数定义时调用此方法补充。

        Args:
            tool_name:   工具名称。
            input_schema: JSON Schema 格式的参数定义。

        Returns:
            是否更新成功（工具不存在时返回 False）。
        """
        tool = self._tools.get(tool_name)
        if tool is None:
            return False
        tool.input_schema = input_schema
        return True

    def __repr__(self) -> str:
        return (
            f"<ToolRegistry servers={len(self._servers)} "
            f"tools={len(self._tools)}>"
        )
