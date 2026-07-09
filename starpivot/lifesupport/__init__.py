"""星枢生命维持系统 — LifeSupport。

自动监控所有 MCP Server 的健康状态，故障自动修复。
"""

from .watchdog import Watchdog

__all__ = ["Watchdog"]
