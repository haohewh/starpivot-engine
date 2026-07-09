"""飞书平台模块 — Feishu (Lark) Integration。

封装飞书消息发送、文档读取接口。
凭证通过 PlatformBus 注入。
骨架实现，返回模拟数据供集成测试。
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class FeishuConfig:
    """飞书平台凭证。"""
    app_id: str = ""
    app_secret: str = ""


class FeishuClient:
    """飞书客户端 — 消息发送 / 文档读写。

    此版本为骨架实现，返回模拟数据供集成测试。
    生产环境请接入飞书开放 API (https://open.feishu.cn)。
    """

    def __init__(self, config: FeishuConfig | None = None) -> None:
        self.config = config or FeishuConfig()
        self._tenant_token: str = ""
        self._token_expires: float = 0

    def configure(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
        logger.info("飞书凭证已更新: %s", list(kwargs.keys()))

    def is_configured(self) -> bool:
        return bool(self.config.app_id and self.config.app_secret)

    async def _get_tenant_token(self) -> str:
        if self._tenant_token and time.time() < self._token_expires - 60:
            return self._tenant_token
        self._tenant_token = f"mock_fs_token_{int(time.time())}"
        self._token_expires = time.time() + 7200
        return self._tenant_token

    async def send_message(self, receive_id: str,
                           content: str,
                           msg_type: str = "text",
                           receive_id_type: str = "open_id") -> dict:
        """发送飞书消息。

        Args:
            receive_id: 接收方 ID（open_id / user_id / chat_id）。
            content: 消息内容。
            msg_type: 消息类型（text / post / image / interactive）。
            receive_id_type: ID 类型。

        Returns:
            dict: {success, message, data: {message_id}}
        """
        await self._get_tenant_token()
        logger.info("飞书消息发送: to=%s type=%s len=%d",
                     receive_id, msg_type, len(content))
        return {
            "success": True,
            "message": "消息发送成功（模拟）",
            "data": {
                "message_id": f"om_mock_{int(time.time() * 1000)}",
                "receive_id": receive_id,
                "msg_type": msg_type,
            },
        }

    async def get_document(self, document_id: str) -> dict:
        """获取飞书文档内容。

        Args:
            document_id: 文档 ID。

        Returns:
            dict: {success, message, data: {document_id, title, content}}
        """
        await self._get_tenant_token()
        logger.info("飞书文档读取: doc_id=%s", document_id)
        return {
            "success": True,
            "message": "文档获取成功（模拟）",
            "data": {
                "document_id": document_id,
                "title": f"文档_{document_id}",
                "content": "这是飞书文档的模拟内容。\n包含多行文本。",
                "owner": "mock_user",
                "create_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
            },
        }
