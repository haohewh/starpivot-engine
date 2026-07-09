"""注册管理器 — 管理 MCP Server 的注册/注销/更新。

与 ToolRegistry 和星枢引擎的 JSON 配置目录交互：
    - 向 /opt/starpivot/mcp_servers/ 写入 JSON 配置文件
    - 注册 Server Python 代码到 /opt/starpivot/mcp_servers/
    - 通过 ToolRegistry 更新运行时注册表

用法:
    manager = RegistryManager()
    # 注册
    success = manager.register(
        name="my_tool",
        server_code=code_string,
        config=config_dict,
    )
    # 注销
    success = manager.unregister("my_tool")
    # 更新
    success = manager.update("my_tool", new_code_string)
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from typing import Any

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
# 注册管理器
# ════════════════════════════════════════════════════════════════════


class RegistryManager:
    """管理 MCP Server 的注册/注销/更新。

    职责：
        1. 将生成的 Server Python 代码写入 mcp_servers/ 目录
        2. 将 JSON 配置写入 mcp_servers/ 目录
        3. 支持重新加载运行时注册表（通过 ToolRegistry）

    文件布局：
        /opt/starpivot/mcp_servers/
            ├── {name}_server.py     # Server 代码
            ├── {name}.json          # 配置
            └── __init__.py          # 包文件

    用法:
        manager = RegistryManager()
        # 注册新工具
        manager.register("my_tool", server_code, config)
        # 注销工具
        manager.unregister("my_tool")
        # 更新工具代码
        manager.update("my_tool", new_code)
    """

    DEFAULT_SERVER_DIR = "/opt/starpivot/mcp_servers/"

    def __init__(
        self,
        server_dir: str | None = None,
    ):
        """初始化注册管理器。

        Args:
            server_dir: MCP Server 配置目录。
        """
        self._server_dir = server_dir or self.DEFAULT_SERVER_DIR

    # ── 注册 ─────────────────────────────────────

    def register(
        self,
        name: str,
        server_code: str,
        config: dict | None = None,
    ) -> bool:
        """注册一个新的 MCP Server。

        写入两个文件：
            1. {server_dir}/{name}_server.py  — Server 代码
            2. {server_dir}/{name}.json       — JSON 配置

        Args:
            name:        服务器标识名。
            server_code: 完整的 Server Python 代码。
            config:      JSON 配置字典。None 则尝试自动从代码推断。

        Returns:
            注册是否成功。
        """
        logger.info("注册 MCP Server: %s", name)

        # ── 确保目录存在 ──
        os.makedirs(self._server_dir, exist_ok=True)

        # ── 验证输入 ──
        if not name or not name.strip():
            logger.error("注册失败: name 不能为空")
            return False

        if not server_code or not server_code.strip():
            logger.error("注册失败: server_code 不能为空")
            return False

        # ── 1. 写入 Server 代码 ──
        server_path = os.path.join(self._server_dir, f"{name}_server.py")
        try:
            with open(server_path, "w", encoding="utf-8") as f:
                f.write(server_code)
            logger.info("已写入 Server 代码: %s", server_path)
        except IOError as e:
            logger.error("写入 Server 代码失败 %s: %s", server_path, e)
            return False

        # ── 2. 写入 JSON 配置 ──
        if config is None:
            config = self._infer_config(name)

        config_path = os.path.join(self._server_dir, f"{name}.json")
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            logger.info("已写入 JSON 配置: %s", config_path)
        except IOError as e:
            logger.error("写入 JSON 配置失败 %s: %s", config_path, e)
            # 尝试清理已写入的 server 文件
            try:
                os.remove(server_path)
            except OSError:
                pass
            return False

        logger.info("注册完成: %s (代码=%s 配置=%s)", name, server_path, config_path)
        return True

    # ── 注销 ─────────────────────────────────────

    def unregister(self, name: str) -> bool:
        """注销一个 MCP Server。

        删除：
            1. {server_dir}/{name}_server.py  — Server 代码
            2. {server_dir}/{name}.json       — JSON 配置

        Args:
            name: 服务器标识名。

        Returns:
            是否成功注销（至少删除一个文件算成功）。
        """
        logger.info("注销 MCP Server: %s", name)

        deleted_any = False

        # ── 删除 Server 代码 ──
        server_path = os.path.join(self._server_dir, f"{name}_server.py")
        if os.path.isfile(server_path):
            try:
                os.remove(server_path)
                logger.info("已删除 Server 代码: %s", server_path)
                deleted_any = True
            except OSError as e:
                logger.error("删除 Server 代码失败 %s: %s", server_path, e)

        # ── 删除 JSON 配置 ──
        config_path = os.path.join(self._server_dir, f"{name}.json")
        if os.path.isfile(config_path):
            try:
                os.remove(config_path)
                logger.info("已删除 JSON 配置: %s", config_path)
                deleted_any = True
            except OSError as e:
                logger.error("删除 JSON 配置失败 %s: %s", config_path, e)

        if not deleted_any:
            logger.warning("注销 %s: 未找到任何文件", name)
            return False

        logger.info("注销完成: %s", name)
        return True

    # ── 更新 ─────────────────────────────────────

    def update(
        self,
        name: str,
        server_code: str | None = None,
        config: dict | None = None,
    ) -> bool:
        """更新已有的 MCP Server。

        只更新提供的部分，未提供的保留原有内容。

        Args:
            name:        服务器标识名。
            server_code: 新的 Server 代码（None 则保留原代码）。
            config:      新的 JSON 配置（None 则保留原配置）。

        Returns:
            是否成功更新（至少成功更新一个文件）。
        """
        logger.info("更新 MCP Server: %s", name)
        updated_any = False

        # ── 更新 Server 代码 ──
        if server_code is not None:
            server_path = os.path.join(self._server_dir, f"{name}_server.py")
            try:
                with open(server_path, "w", encoding="utf-8") as f:
                    f.write(server_code)
                logger.info("已更新 Server 代码: %s", server_path)
                updated_any = True
            except IOError as e:
                logger.error("更新 Server 代码失败 %s: %s", server_path, e)

        # ── 更新 JSON 配置 ──
        if config is not None:
            config_path = os.path.join(self._server_dir, f"{name}.json")
            try:
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(config, f, ensure_ascii=False, indent=2)
                logger.info("已更新 JSON 配置: %s", config_path)
                updated_any = True
            except IOError as e:
                logger.error("更新 JSON 配置失败 %s: %s", config_path, e)

        if not updated_any:
            logger.warning("更新 %s: 未提供任何更新内容", name)
            return False

        logger.info("更新完成: %s", name)
        return True

    # ── 列表 & 状态 ──────────────────────────────

    def list_registered(self) -> list[dict]:
        """列出所有已注册的 MCP Server。

        Returns:
            配置字典列表（从 JSON 文件解析）。
        """
        servers: list[dict] = []

        if not os.path.isdir(self._server_dir):
            logger.warning("Server 目录不存在: %s", self._server_dir)
            return servers

        for filename in sorted(os.listdir(self._server_dir)):
            if not filename.endswith(".json"):
                continue

            filepath = os.path.join(self._server_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    config = json.load(f)
                servers.append(config)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning("读取配置 %s 失败: %s", filepath, e)

        return servers

    def get_status(self, name: str) -> dict:
        """查询指定 Server 的注册状态。

        Args:
            name: 服务器标识名。

        Returns:
            状态字典:
                - registered (bool): 是否已注册
                - has_code (bool):   是否有代码文件
                - has_config (bool): 是否有配置文件
                - config (dict|None): 配置内容（如有）
        """
        status: dict = {
            "registered": False,
            "has_code": False,
            "has_config": False,
            "config": None,
        }

        # 检查代码文件
        server_path = os.path.join(self._server_dir, f"{name}_server.py")
        if os.path.isfile(server_path):
            status["has_code"] = True

        # 检查配置文件
        config_path = os.path.join(self._server_dir, f"{name}.json")
        if os.path.isfile(config_path):
            status["has_config"] = True
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    status["config"] = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass

        status["registered"] = status["has_code"] and status["has_config"]
        return status

    # ── 运行时注册表同步 ─────────────────────────

    def sync_to_registry(self, registry) -> int:
        """将配置文件同步到运行时注册表。

        调用 registry.discover_servers() 重新加载所有配置。

        Args:
            registry: ToolRegistry 实例。

        Returns:
            成功加载的服务器数量。
        """
        count = registry.discover_servers(self._server_dir)
        logger.info("已同步 %d 个 MCP Server 到注册表", count)
        return count

    # ── 辅助方法 ─────────────────────────────────

    @staticmethod
    def _infer_config(name: str) -> dict:
        """在没有提供配置时，推断默认配置。

        Args:
            name: 服务器标识名。

        Returns:
            推断出的配置字典。
        """
        return {
            "name": name,
            "transport": "stdio",
            "command": "/opt/starpivot/venv/bin/python",
            "args": [f"-m", f"mcp_servers.{name}_server"],
            "tools": [],
            "timeout": 15,
            "enabled": True,
        }

    @staticmethod
    def read_server_code(name: str, server_dir: str | None = None) -> str | None:
        """读取已注册 Server 的代码。

        Args:
            name:       服务器标识名。
            server_dir: Server 目录（默认 /opt/starpivot/mcp_servers/）。

        Returns:
            Server 代码文本，未找到时返回 None。
        """
        directory = server_dir or "/opt/starpivot/mcp_servers/"
        server_path = os.path.join(directory, f"{name}_server.py")
        if not os.path.isfile(server_path):
            return None
        try:
            with open(server_path, "r", encoding="utf-8") as f:
                return f.read()
        except IOError:
            return None
