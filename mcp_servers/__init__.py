"""MCP Server package for StarPivot Engine.

Each module in this package is a standalone MCP Server process,
invoked via `python -m mcp_servers.<name>` with stdio transport.

MCP Server 进程独立运行，崩溃不影响星枢引擎主进程。
引擎通过 JSON 配置文件发现和连接这些服务器。
"""

# 包版本号，与星枢引擎同步
__version__ = "1.0.0"
