"""平台集成总线 — Platform Bus。

统一管理各平台客户端实例和凭证。
每个平台独立模块，bus.py 负责统一调度。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .wechat import WeChatClient, WeChatConfig
from .dingtalk import DingTalkClient, DingTalkConfig
from .alipay import AlipayClient, AlipayConfig
from .douyin import DouYinClient, DouYinConfig
from .jianying import JianYingClient, JianYingConfig
from .feishu import FeishuClient, FeishuConfig
from .meeting import MeetingClient, MeetingConfig

logger = logging.getLogger(__name__)


class PlatformBus:
    """平台集成总线。

    管理多个外部平台客户端，提供统一的凭证注入和调用入口。

    用法:
        bus = PlatformBus()
        bus.configure("wechat", app_id="xxx", app_secret="yyy")
        result = await bus.wechat.send_message("openid", "你好")
    """

    def __init__(self) -> None:
        # 平台客户端实例
        self.wechat: WeChatClient = WeChatClient()
        self.dingtalk: DingTalkClient = DingTalkClient()
        self.alipay: AlipayClient = AlipayClient()
        self.douyin: DouYinClient = DouYinClient()
        self.jianying: JianYingClient = JianYingClient()
        self.feishu: FeishuClient = FeishuClient()
        self.meeting: MeetingClient = MeetingClient()

        # 平台注册表（扩展用）
        self._platforms: dict[str, Any] = {
            "wechat": self.wechat,
            "dingtalk": self.dingtalk,
            "alipay": self.alipay,
            "douyin": self.douyin,
            "jianying": self.jianying,
            "feishu": self.feishu,
            "meeting": self.meeting,
        }

    # ── 平台注册（扩展） ────────────────────

    def register(self, name: str, client: Any) -> None:
        """注册新的平台客户端。

        Args:
            name: 平台名称（如 "feishu", "douyin"）。
            client: 平台客户端实例（须有 configure 和 is_configured 方法）。
        """
        self._platforms[name] = client
        if not hasattr(self, name):
            setattr(self, name, client)
        logger.info("平台已注册: %s (%s)", name, type(client).__name__)

    def get_platform(self, name: str) -> Any | None:
        """按名称获取平台客户端。"""
        return self._platforms.get(name)

    def list_platforms(self) -> list[str]:
        """列出所有已注册的平台。"""
        return list(self._platforms.keys())

    def list_configured(self) -> list[str]:
        """列出已配置凭证的平台。"""
        return [
            name for name, client in self._platforms.items()
            if hasattr(client, "is_configured") and client.is_configured()
        ]

    # ── 凭证管理 ──────────────────────────

    def configure(self, platform: str, **kwargs: Any) -> dict:
        """配置指定平台的凭证。

        Args:
            platform: 平台名称（wechat / dingtalk / alipay）。
            **kwargs: 凭证键值对。

        Returns:
            dict: {success, message, configured_keys}
        """
        client = self._platforms.get(platform)
        if client is None:
            return {
                "success": False,
                "message": f"未知平台: {platform}，可用: {list(self._platforms.keys())}",
                "configured_keys": [],
            }
        try:
            client.configure(**kwargs)
            configured = list(kwargs.keys())
            logger.info("平台凭证已配置: %s -> %s", platform, configured)
            return {
                "success": True,
                "message": f"平台 {platform} 凭证配置成功",
                "configured_keys": configured,
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"配置失败: {e}",
                "configured_keys": [],
            }

    def configure_from_dict(self, configs: dict[str, dict]) -> list[dict]:
        """批量配置多个平台的凭证。

        Args:
            configs: {platform_name: {key: value, ...}, ...}

        Returns:
            list[dict]: 每个平台的配置结果。
        """
        results = []
        for platform, kwargs in configs.items():
            results.append(self.configure(platform, **kwargs))
        return results

    # ── 状态检查 ──────────────────────────

    def status(self) -> dict:
        """查看所有平台的状态。"""
        return {
            "platforms": self.list_platforms(),
            "configured": self.list_configured(),
            "details": {
                name: {
                    "configured": (
                        client.is_configured()
                        if hasattr(client, "is_configured")
                        else False
                    ),
                    "type": type(client).__name__,
                }
                for name, client in self._platforms.items()
            },
        }

    # ── 便捷调用 ──────────────────────────

    async def call(
        self,
        platform: str,
        action: str,
        **kwargs: Any,
    ) -> dict:
        """统一调用平台操作。

        Args:
            platform: 平台名称。
            action: 操作名称（如 send_message, pay, get_user）。
            **kwargs: 操作参数。

        Returns:
            dict: 操作结果。
        """
        client = self._platforms.get(platform)
        if client is None:
            return {
                "success": False,
                "message": f"未知平台: {platform}",
                "data": None,
            }
        method = getattr(client, action, None)
        if method is None:
            return {
                "success": False,
                "message": f"平台 {platform} 不支持操作: {action}",
                "data": None,
            }
        try:
            if hasattr(method, "__call__"):
                result = await method(**kwargs) if hasattr(method, "__await__") or "async" in str(type(method)) else method(**kwargs)
                return result if isinstance(result, dict) else {"success": True, "data": result}
            return {"success": False, "message": f"{action} 不可调用", "data": None}
        except Exception as e:
            logger.error("平台调用失败: %s.%s -> %s", platform, action, e)
            return {"success": False, "message": f"调用异常: {e}", "data": None}
