"""钉钉平台模块 — DingTalk Integration。

封装钉钉机器人消息推送、用户查询接口。
凭证通过 PlatformBus 注入。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DingTalkConfig:
    """钉钉平台凭证。"""
    app_key: str = ""
    app_secret: str = ""
    agent_id: str = ""       # 应用 AgentId
    webhook_token: str = ""  # 群机器人 webhook token


class DingTalkClient:
    """钉钉客户端 — 消息推送 / 用户查询 / 群机器人。

    此版本为骨架实现，返回模拟数据供集成测试。
    生产环境请接入钉钉开放 API (https://oapi.dingtalk.com)。
    """

    def __init__(self, config: DingTalkConfig | None = None) -> None:
        self.config = config or DingTalkConfig()
        self._access_token: str = ""
        self._token_expires: float = 0

    # ── 凭证管理 ──────────────────────────

    def configure(self, **kwargs: Any) -> None:
        """动态更新凭证。"""
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
        logger.info("钉钉凭证已更新: %s", list(kwargs.keys()))

    def is_configured(self) -> bool:
        return bool(self.config.app_key and self.config.app_secret)

    async def _get_access_token(self) -> str:
        """获取 access_token（带缓存）。"""
        if self._access_token and time.time() < self._token_expires - 60:
            return self._access_token
        self._access_token = f"mock_dd_token_{int(time.time())}"
        self._token_expires = time.time() + 7200
        return self._access_token

    # ── 消息发送 ──────────────────────────

    async def send_message(
        self,
        user_ids: str | list[str],
        content: str,
        msg_type: str = "text",
    ) -> dict:
        """发送工作通知消息。

        Args:
            user_ids: 接收方 UserID（单个或列表）。
            content: 消息内容。
            msg_type: 消息类型 (text / markdown / action_card / etc.)

        Returns:
            dict: {success, message, data}
        """
        if isinstance(user_ids, str):
            user_ids = [user_ids]
        token = await self._get_access_token()
        logger.info(
            "钉钉消息发送: to=%s type=%s len=%d",
            user_ids, msg_type, len(content),
        )
        return {
            "success": True,
            "message": "工作通知发送成功（模拟）",
            "data": {
                "task_id": f"mock_task_{int(time.time())}",
                "user_count": len(user_ids),
            },
        }

    async def send_webhook(
        self,
        content: str,
        msg_type: str = "text",
        at_mobiles: list[str] | None = None,
        at_all: bool = False,
    ) -> dict:
        """发送群机器人消息。

        Args:
            content: 消息内容。
            msg_type: 消息类型 (text / markdown / link / actionCard / feedCard)。
            at_mobiles: @ 指定的手机号列表。
            at_all: 是否 @ 所有人。

        Returns:
            dict: {success, message}
        """
        if not self.config.webhook_token:
            return {"success": False, "message": "Webhook Token 未配置", "data": None}
        logger.info(
            "钉钉群消息发送: type=%s at_all=%s len=%d",
            msg_type, at_all, len(content),
        )
        return {
            "success": True,
            "message": "群消息发送成功（模拟）",
            "data": {
                "at_all": at_all,
                "at_mobiles": at_mobiles or [],
            },
        }

    # ── 用户查询 ──────────────────────────

    async def get_user(self, user_id: str) -> dict:
        """查询钉钉用户信息。

        Args:
            user_id: 用户 UserID。

        Returns:
            dict: {success, message, data: {user_id, name, mobile, email, ...}}
        """
        await self._get_access_token()
        logger.info("钉钉用户查询: user_id=%s", user_id)
        return {
            "success": True,
            "message": "用户查询成功（模拟）",
            "data": {
                "user_id": user_id,
                "name": f"用户_{user_id}",
                "mobile": "138****0000",
                "email": f"{user_id}@example.com",
                "department": ["1"],
                "active": True,
            },
        }

    async def list_users(self, department_id: str = "1", offset: int = 0, size: int = 20) -> dict:
        """查询部门用户列表。

        Args:
            department_id: 部门 ID。
            offset: 分页偏移。
            size: 每页大小。

        Returns:
            dict: {success, message, data: {list, total}}
        """
        await self._get_access_token()
        logger.info("钉钉用户列表: dept=%s offset=%d size=%d", department_id, offset, size)
        return {
            "success": True,
            "message": "用户列表查询成功（模拟）",
            "data": {
                "list": [
                    {"user_id": f"user_{i}", "name": f"用户_{i}"}
                    for i in range(offset, min(offset + size, 100))
                ],
                "total": 100,
            },
        }
