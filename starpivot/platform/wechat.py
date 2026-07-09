"""微信平台模块 — WeChat Integration。

封装微信公众平台/小程序/支付接口。
凭证通过 PlatformBus 注入，不硬编码。
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class WeChatConfig:
    """微信平台凭证。"""
    app_id: str = ""
    app_secret: str = ""
    mch_id: str = ""        # 商户号（支付用）
    mch_key: str = ""       # 商户 API 密钥（支付用）
    token: str = ""         # 公众号 token（验证用）
    encoding_aes_key: str = ""


class WeChatClient:
    """微信客户端 — 消息推送 / 二维码 / 支付。

    此版本为骨架实现，返回模拟数据供集成测试。
    生产环境请接入真实微信 API (https://api.weixin.qq.com)。
    """

    def __init__(self, config: WeChatConfig | None = None) -> None:
        self.config = config or WeChatConfig()
        self._access_token: str = ""
        self._token_expires: float = 0

    # ── 凭证管理 ──────────────────────────

    def configure(self, **kwargs: Any) -> None:
        """动态更新凭证。"""
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
        logger.info("微信凭证已更新: %s", list(kwargs.keys()))

    def is_configured(self) -> bool:
        """检查必要凭证是否已配置。"""
        return bool(self.config.app_id and self.config.app_secret)

    async def _get_access_token(self) -> str:
        """获取 access_token（带缓存）。"""
        if self._access_token and time.time() < self._token_expires - 60:
            return self._access_token
        # 模拟 token 获取
        self._access_token = f"mock_wx_token_{int(time.time())}"
        self._token_expires = time.time() + 7200
        return self._access_token

    # ── 消息发送 ──────────────────────────

    async def send_message(
        self,
        to_user: str,
        content: str,
        msg_type: str = "text",
    ) -> dict:
        """发送模板消息 / 客服消息。

        Args:
            to_user: 接收方 OpenID。
            content: 消息内容（纯文本或 JSON）。
            msg_type: 消息类型 (text / template / image / etc.)

        Returns:
            dict: {success, message, data}
        """
        token = await self._get_access_token()
        # 骨架实现
        logger.info(
            "微信消息发送: to=%s type=%s len=%d",
            to_user, msg_type, len(content),
        )
        return {
            "success": True,
            "message": "消息发送成功（模拟）",
            "data": {
                "to_user": to_user,
                "msg_type": msg_type,
                "msgid": f"mock_{int(time.time() * 1000)}",
            },
        }

    # ── 二维码 ────────────────────────────

    async def get_qr_code(
        self,
        scene_str: str = "",
        expire_seconds: int = 2592000,
    ) -> dict:
        """获取带参数的二维码。

        Args:
            scene_str: 场景值（字符串）。
            expire_seconds: 过期时间（秒，默认 30 天）。

        Returns:
            dict: {success, message, data: {ticket, url, expire_seconds}}
        """
        await self._get_access_token()
        ticket = f"mock_qr_ticket_{int(time.time())}"
        url = f"https://weixin.qq.com/q/{ticket}"
        logger.info("微信二维码生成: scene=%s", scene_str)
        return {
            "success": True,
            "message": "二维码生成成功（模拟）",
            "data": {
                "ticket": ticket,
                "url": url,
                "expire_seconds": expire_seconds,
            },
        }

    # ── 支付 ──────────────────────────────

    async def pay(
        self,
        open_id: str,
        order_no: str,
        amount: int,
        description: str = "",
        notify_url: str = "",
    ) -> dict:
        """发起微信支付（JSAPI / 小程序支付）。

        Args:
            open_id: 用户 OpenID。
            order_no: 商户订单号。
            amount: 支付金额（分）。
            description: 商品描述。
            notify_url: 回调通知 URL。

        Returns:
            dict: {success, message, data: {prepay_id, pay_params}}
        """
        if not self.config.mch_id:
            return {"success": False, "message": "商户号未配置", "data": None}
        prepay_id = f"wx_prepay_{int(time.time() * 1000)}"
        logger.info(
            "微信支付发起: order=%s amount=%d open_id=%s",
            order_no, amount, open_id,
        )
        return {
            "success": True,
            "message": "支付订单创建成功（模拟）",
            "data": {
                "prepay_id": prepay_id,
                "order_no": order_no,
                "amount": amount,
                "pay_params": {
                    "appId": self.config.app_id,
                    "timeStamp": str(int(time.time())),
                    "nonceStr": hashlib.md5(str(time.time()).encode()).hexdigest()[:16],
                    "package": f"prepay_id={prepay_id}",
                    "signType": "MD5",
                },
            },
        }

    async def refund(
        self,
        order_no: str,
        refund_no: str,
        total_amount: int,
        refund_amount: int,
    ) -> dict:
        """微信退款。

        Args:
            order_no: 商户订单号。
            refund_no: 退款单号。
            total_amount: 原订单金额（分）。
            refund_amount: 退款金额（分）。

        Returns:
            dict: {success, message, data}
        """
        logger.info(
            "微信退款发起: order=%s refund=%s amount=%d",
            order_no, refund_no, refund_amount,
        )
        return {
            "success": True,
            "message": "退款处理中（模拟）",
            "data": {
                "order_no": order_no,
                "refund_no": refund_no,
                "refund_amount": refund_amount,
                "status": "processing",
            },
        }
