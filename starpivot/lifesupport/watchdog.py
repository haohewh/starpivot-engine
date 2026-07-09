"""星枢生命维持 — Watchdog（看门狗）。

自动监控所有 MCP Server 的健康状态，检测到崩溃后自动重启。

用法:
    engine = StarPivotEngine(registry)
    watchdog = Watchdog(engine, registry)
    watchdog.start()
    # 自动在后台每 30 秒检测一次
    status = watchdog.get_status()
    watchdog.stop()
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class Watchdog:
    """生命维持系统：监控所有 MCP Server 健康，崩溃自动重启。

    职责:
        1. 定时检测所有已注册 MCP Server 的健康状态。
        2. 检测到崩溃（连接失败/无响应）后自动重启。
        3. 报告所有 Server 的健康状态。
        4. 提供手动检查和重启接口。

    用法:
        watchdog = Watchdog(engine, registry)
        watchdog.start()          # 启动后台监控循环
        alive = watchdog.check_server("search")
        ok = watchdog.restart_server("search")
        status = watchdog.get_status()
        watchdog.stop()           # 停止监控循环
    """

    def __init__(
        self,
        engine: Any,
        registry: Any,
        interval: int = 30,
    ) -> None:
        self.engine = engine
        self.registry = registry
        self.interval = interval  # 检测间隔（秒）
        self._running = False
        self._task: asyncio.Task | None = None
        self._status: dict[str, dict] = {}  # server_name -> {alive, last_check, error}
        self._restart_count: dict[str, int] = {}
        self._max_restarts = 3  # 每轮检测最多重启次数

    # ── 启动/停止 ──────────────────────────────

    def start(self) -> None:
        """启动监控循环（每 interval 秒检测一次）。

        在事件循环中启动后台 asyncio.Task，自动检测所有已注册
        MCP Server 的健康状态，崩溃自动重启。
        """
        if self._running:
            logger.warning("Watchdog 已在运行中")
            return
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info(
            "Watchdog 已启动（检测间隔: %d 秒）", self.interval,
        )

    async def stop(self) -> None:
        """停止监控循环。"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Watchdog 已停止")

    # ── 监控循环 ──────────────────────────────

    async def _monitor_loop(self) -> None:
        """后台监控主循环。"""
        while self._running:
            try:
                await self._check_all_servers()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Watchdog 检测异常: %s", e)
            await asyncio.sleep(self.interval)

    async def _check_all_servers(self) -> None:
        """检测所有已注册服务器的健康状态。"""
        servers = self.registry.list_servers()
        for server in servers:
            if not server.enabled:
                continue
            name = server.name
            alive = await self.check_server(name)
            now = time.time()

            if alive:
                self._status[name] = {
                    "alive": True,
                    "last_check": now,
                    "error": None,
                    "restart_count": self._restart_count.get(name, 0),
                }
            else:
                # 记录失败状态
                self._status[name] = {
                    "alive": False,
                    "last_check": now,
                    "error": f"Server {name} 无响应",
                    "restart_count": self._restart_count.get(name, 0),
                }
                # 自动重启（限制每轮最多重启次数）
                restarts = self._restart_count.get(name, 0)
                if restarts < self._max_restarts:
                    ok = await self.restart_server(name)
                    if ok:
                        self._restart_count[name] = restarts + 1
                        self._status[name]["alive"] = True
                        self._status[name]["error"] = None
                        logger.info(
                            "Watchdog 已自动重启 Server: %s（第 %d 次）",
                            name, restarts + 1,
                        )
                else:
                    logger.warning(
                        "Watchdog: Server %s 已达最大重启次数（%d），"
                        "跳过本轮重启",
                        name, self._max_restarts,
                    )

    # ── 单服务器检测 ──────────────────────────

    async def check_server(self, name: str) -> bool:
        """检测单个 MCP Server 是否存活。

        通过尝试获取/创建会话并发送 list_tools 请求来检测。

        Args:
            name: 服务器名称。

        Returns:
            True 表示存活，False 表示已崩溃或无响应。
        """
        server_config = self.registry.get_server(name)
        if server_config is None:
            logger.warning("Watchdog: 未找到服务器配置: %s", name)
            return False

        try:
            # 从引擎获取现有会话或创建新会话
            session = self.engine._sessions.get(name)
            if session is None:
                from ..engine import MCPSession  # 延迟导入避免循环
                session = MCPSession(server_config)
                self.engine._sessions[name] = session

            await session.ensure_connected()
            # 发送轻量探测请求
            await session._session.list_tools()
            return True
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(
                "Watchdog: Server %s 检测失败: %s", name, e,
            )
            return False

    async def restart_server(self, name: str) -> bool:
        """重启故障 Server。

        流程:
            1. 关闭旧会话（如果存在）。
            2. 从引擎会话池中移除旧会话。
            3. 引擎会在下次调用时自动创建新会话。

        Args:
            name: 服务器名称。

        Returns:
            True 表示重启成功，False 表示失败。
        """
        server_config = self.registry.get_server(name)
        if server_config is None:
            logger.error("Watchdog: 无法重启 %s — 未找到配置", name)
            return False

        try:
            # 关闭旧会话
            old_session = self.engine._sessions.pop(name, None)
            if old_session:
                try:
                    await old_session.close()
                except Exception as e:
                    logger.warning(
                        "关闭旧会话 %s 时出错: %s", name, e,
                    )

            # 创建新会话并验证连接
            from ..engine import MCPSession  # 延迟导入避免循环
            new_session = MCPSession(server_config)
            await new_session.ensure_connected()
            self.engine._sessions[name] = new_session

            logger.info("Watchdog: Server %s 重启成功", name)
            return True
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Watchdog: 重启 Server %s 失败: %s", name, e)
            return False

    # ── 状态报告 ──────────────────────────────

    def get_status(self) -> dict:
        """获取所有 Server 的健康状态。

        Returns:
            字典，键为服务器名称，值为状态信息:
                - alive (bool):        是否存活。
                - last_check (float):  最后检测时间戳。
                - error (str|None):    错误信息（如果有）。
                - restart_count (int): 本轮重启次数。
        """
        return dict(self._status)

    def get_summary(self) -> dict:
        """获取健康摘要。

        Returns:
            - total (int):  服务器总数。
            - alive (int):  存活数量。
            - dead (int):   故障数量。
            - servers (list): 每台服务器的简要状态。
        """
        servers = self.registry.list_servers()
        total = len(servers)
        alive_count = 0
        dead_count = 0
        details = []

        for s in servers:
            st = self._status.get(s.name, {})
            is_alive = st.get("alive", False)
            if is_alive:
                alive_count += 1
            else:
                dead_count += 1
            details.append({
                "name": s.name,
                "alive": is_alive,
                "error": st.get("error"),
            })

        return {
            "total": total,
            "alive": alive_count,
            "dead": dead_count,
            "servers": details,
        }
