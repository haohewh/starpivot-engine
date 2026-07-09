"""MCP 包装器生成器 — 为发现的工具自动生成 MCP Server 代码。

生成的 Server 代码遵循星枢引擎现有 MCP Server 模式（如 search_server.py）：
    - 使用 mcp.server.Server + stdio_server
    - list_tools() 声明工具
    - call_tool() 处理调用
    - main() 入口加 __main__ 块

输出：
    1. server_code (str): 完整的 Python Server 代码
    2. config_dict (dict): 对应的 JSON 配置字典

用法:
    generator = MCPWrapperGenerator()
    server_code = generator.generate(analysis)
    config = generator.get_config(analysis)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from .github_scanner import RepoAnalysis

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
# MCP 包装器生成器
# ════════════════════════════════════════════════════════════════════


class MCPWrapperGenerator:
    """为发现的工具自动生成 MCP Server 包装器。

    生成的 Server 是自包含的 Python 文件：
        - 可通过 python -m <module_path> 直接启动
        - 通过 stdio 与星枢引擎通信
        - 包含 list_tools / call_tool 处理函数

    用法:
        code = MCPWrapperGenerator().generate(analysis)
        with open("my_server.py", "w") as f:
            f.write(code)
        config = MCPWrapperGenerator().get_config(analysis)
    """

    OUTPUT_DIR: str = "/opt/starpivot/mcp_servers/"

    def __init__(self, output_dir: str | None = None):
        self._output_dir = output_dir or self.OUTPUT_DIR

    def generate(self, analysis: RepoAnalysis) -> str:
        """为仓库分析结果生成完整的 MCP Server 代码。

        Args:
            analysis: 仓库分析结果（需 suitable=True）。

        Returns:
            完整的 Python Server 代码文本。

        Raises:
            ValueError: 如果 analysis.suitable 为 False。
        """
        if not analysis.suitable:
            raise ValueError(
                f"仓库 {analysis.repo.full_name} 不适合作为 MCP Server: "
                f"{analysis.reason}"
            )

        server_name = analysis.name
        repo = analysis.repo
        tools = analysis.suggested_tools

        code = self._generate_header(server_name, repo)
        code += self._generate_imports(server_name)
        code += self._generate_tool_implementations(server_name, tools)
        code += self._generate_server_class(server_name, tools)
        code += self._generate_entry_point(server_name)

        logger.info(
            "已生成 MCP Server 代码: %s_server.py (%d 工具)",
            server_name, len(tools),
        )
        return code

    def get_config(self, analysis: RepoAnalysis) -> dict:
        """生成 MCP Server 的 JSON 配置字典。

        Args:
            analysis: 仓库分析结果。

        Returns:
            配置字典，符合 ToolRegistry.register_server() 格式。
        """
        server_name = analysis.name
        tool_names = [t["name"] for t in analysis.suggested_tools]

        config = {
            "name": server_name,
            "transport": "stdio",
            "command": f"/opt/starpivot/venv/bin/python",
            "args": ["-m", f"mcp_servers.{server_name}_server"],
            "tools": tool_names,
            "timeout": 15,
            "enabled": True,
        }
        return config

    def get_config_path(self, server_name: str) -> str:
        """获取配置文件路径。

        Args:
            server_name: 服务器名称。

        Returns:
            配置文件完整路径（.json）。
        """
        return f"{self._output_dir}{server_name}.json"

    # ── 代码生成方法 ──────────────────────────────

    @staticmethod
    def _generate_header(server_name: str, repo: RepoInfo) -> str:
        """生成文件头部注释。"""
        # 这里用 Any 避免 import 循环
        repo_name = getattr(repo, "full_name", "unknown/unknown")
        repo_desc = getattr(repo, "description", "")
        repo_url = getattr(repo, "url", f"https://github.com/{repo_name}")

        return f'''#!/usr/bin/env python3
"""MCP Server: {server_name}_server — 自动发现的工具

源仓库: {repo_name}
仓库描述: {repo_desc}
仓库 URL: {repo_url}

此文件由 StarPivot Discovery 自动生成。
请审查代码后再部署到生产环境。

启动方式:
    python -m mcp_servers.{server_name}_server
"""

'''
    @staticmethod
    def _generate_imports(server_name: str) -> str:
        """生成 import 部分。"""
        imports = '''from __future__ import annotations

import asyncio
import json
import logging
import sys
import subprocess

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("__SERVER_NAME__")

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


'''
        return imports.replace("__SERVER_NAME__", server_name)

    @staticmethod
    def _generate_tool_implementations(server_name: str, tools: list[dict]) -> str:
        """生成工具的实际实现函数。

        每个工具生成一个 Python 函数，内部通过 subprocess 或
        requests 调用原始工具的 CLI / API。

        这是一个基础实现，后续可以：
            - 支持 pip install 后 import 调用
            - 支持 Docker 容器化执行
            - 通过 LLM 分析 README 自动生成调用逻辑
        """
        code = ""
        code += "# ══════════════════════════════════════════════════════════════\n"
        code += "# 工具实现\n"
        code += "# ══════════════════════════════════════════════════════════════\n\n"
        code += "# TODO: 根据仓库 README 和文档，实现各工具的调用逻辑。\n"
        code += "# 以下为占位实现，需要人工审查和补全。\n\n"

        for tool in tools:
            tool_name = tool["name"]
            tool_desc = tool.get("description", "")
            params = tool.get("input_schema", {}).get("properties", {})
            required = tool.get("input_schema", {}).get("required", [])

            code += f"def _execute_{tool_name}(arguments: dict) -> str:\n"
            code += f'    """执行 {tool_name} 工具。\n\n'
            code += f"    {tool_desc}\n\n"
            code += "    Args:\n"
            for pname, pdef in params.items():
                ptype = pdef.get("type", "str")
                pdesc = pdef.get("description", "")
                code += f"        {pname} ({ptype}): {pdesc}\n"
            code += "\n"
            code += "    Returns:\n"
            code += "        工具执行结果文本。\n"
            code += '    """\n'
            code += f'    logger.info("执行 {tool_name}: arguments=%s", arguments)\n\n'

            # 生成参数提取逻辑
            code += "    # ── 提取参数 ──\n"
            for pname, pdef in params.items():
                ptype = pdef.get("type", "string")
                default = pdef.get("default")
                if pname in required:
                    if ptype == "integer":
                        code += f"    {pname} = arguments.get(\"{pname}\", 0)\n"
                    elif ptype == "number":
                        code += f"    {pname} = arguments.get(\"{pname}\", 0.0)\n"
                    elif ptype == "boolean":
                        code += f"    {pname} = arguments.get(\"{pname}\", False)\n"
                    else:
                        code += f"    {pname} = arguments.get(\"{pname}\", \"\")\n"
                else:
                    if default is not None:
                        code += f"    {pname} = arguments.get(\"{pname}\", {json.dumps(default)})\n"
                    elif ptype == "integer":
                        code += f"    {pname} = arguments.get(\"{pname}\")\n"
                    else:
                        code += f"    {pname} = arguments.get(\"{pname}\", \"\")\n"

            code += "\n"
            code += "    # ── TODO: 实现实际的工具调用逻辑 ──\n"
            code += "    # 根据仓库的文档，调用对应的 API 或 CLI。\n"
            code += "    # 示例：\n"
            code += "    #   import requests\n"
            code += "    #   resp = requests.post(url, json=arguments)\n"
            code += '    #   return resp.text\n'
            code += "\n"
            code += f'    return f"[{tool_name}] 收到参数: {{json.dumps(arguments, ensure_ascii=False, indent=2)}}"\\n"工具实现待补全: 请参考源仓库文档"\\n'
            code += "\n\n"

        return code

    @staticmethod
    def _generate_server_class(server_name: str, tools: list[dict]) -> str:
        """生成 MCP Server 类定义。"""
        code = "# ══════════════════════════════════════════════════════════════\n"
        code += "# MCP Server 定义\n"
        code += "# ══════════════════════════════════════════════════════════════\n\n"

        code += f'app = Server("{server_name}_server")\n\n\n'

        # ── list_tools ──
        code += "@app.list_tools()\n"
        code += "async def list_tools() -> list[Tool]:\n"
        code += '    """声明此服务器提供的工具列表。"""\n'
        code += "    return [\n"
        for tool in tools:
            tool_name = tool["name"]
            tool_desc = tool.get("description", "")
            input_schema = tool.get("input_schema", {})
            schema_json = json.dumps(input_schema, indent=16, ensure_ascii=False)
            code += f"        Tool(\n"
            code += f'            name="{tool_name}",\n'
            code += f'            description="{tool_desc}",\n'
            code += f"            inputSchema={schema_json},\n"
            code += f"        ),\n"
        code += "    ]\n\n\n"

        # ── call_tool ──
        code += "@app.call_tool()\n"
        code += "async def call_tool(\n"
        code += "    name: str,\n"
        code += "    arguments: dict,\n"
        code += ") -> list[TextContent]:\n"
        code += '    """处理工具调用请求。\n\n'
        code += "    Args:\n"
        code += "        name: 工具名称。\n"
        code += "        arguments: 工具参数字典。\n\n"
        code += "    Returns:\n"
        code += "        TextContent 列表。\n\n"
        code += "    Raises:\n"
        code += "        ValueError: 未知工具名。\n"
        code += '    """\n'

        # 生成工具路由
        for i, tool in enumerate(tools):
            tool_name = tool["name"]
            if i == 0:
                code += f"    if name == \"{tool_name}\":\n"
            else:
                code += f"    elif name == \"{tool_name}\":\n"
            code += f'        result_text = _execute_{tool_name}(arguments)\n'
            code += f"        return [TextContent(type=\"text\", text=result_text)]\n"

        code += "    else:\n"
        tool_names_str = ", ".join(f'"{t["name"]}"' for t in tools)
        code += f"        raise ValueError(f\"未知工具: {{name}}，此服务器仅提供 {tool_names_str} 工具\")\n"
        code += "\n\n"

        return code

    @staticmethod
    def _generate_entry_point(server_name: str) -> str:
        """生成入口函数和 __main__ 块。"""
        code = "# ══════════════════════════════════════════════════════════════\n"
        code += "# 入口\n"
        code += "# ══════════════════════════════════════════════════════════════\n\n"

        code += "async def main() -> None:\n"
        code += '    """启动 MCP Server（stdio 传输层）。"""\n'
        code += f'    logger.info("{server_name}_server 启动中...")\n\n'
        code += "    async with stdio_server() as (read_stream, write_stream):\n"
        code += "        await app.run(\n"
        code += "            read_stream,\n"
        code += "            write_stream,\n"
        code += "            app.create_initialization_options(),\n"
        code += "        )\n\n"
        code += f'    logger.info("{server_name}_server 已关闭")\n\n\n'

        code += "def _run_main() -> None:\n"
        code += '    """同步入口（供 __main__ 块调用）。"""\n'
        code += "    try:\n"
        code += "        asyncio.run(main())\n"
        code += "    except KeyboardInterrupt:\n"
        code += f'        logger.info("{server_name}_server 收到中断信号，退出")\n'
        code += "    except Exception as e:\n"
        code += f'        logger.error("{server_name}_server 异常退出: %s", e)\n'
        code += "        sys.exit(1)\n\n\n"

        code += 'if __name__ == "__main__":\n'
        code += "    _run_main()\n"
        return code
