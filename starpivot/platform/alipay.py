"""支付宝平台模块 — Alipay Integration。

封装支付宝支付、退款接口。
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
class AlipayConfig:
    """支付宝平台凭证。"""
    app_id: str = ""
    private_key: str = ""
    alipay_public_key: str = ""
    notify_url: str = ""
    gateway: str = "https://openapi.alipay.com/gateway.do"
    sign_type: str = "RSA2"


class AlipayClient:
    """支付宝客户端 — 支付 / 退款 / 查询。

    此版本为骨架实现，返回模拟数据供集成测试。
    生产环境请接入支付宝开放 API (https://open.alipay.com)。
    """

    def __init__(self, config: AlipayConfig | None = None) -> None:
        self.config = config or AlipayConfig()

    # ── 凭证管理 ──────────────────────────

    def configure(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
        logger.info("支付宝凭证已更新: %s", list(kwargs.keys()))

    def is_configured(self) -> bool:
        return bool(self.config.app_id)

    # ── 支付 ──────────────────────────────

    async def pay(
        self,
        order_no: str,
        amount: str,
        subject: str = "",
        buyer_id: str = "",
        **kwargs: Any,
    ) -> dict:
        """发起支付宝支付（统一收单）。

        Args:
            order_no: 商户订单号。
            amount: 支付金额（元，精确到两位小数）。
            subject: 订单标题。
            buyer_id: 买家支付宝用户 ID。
            **kwargs: 额外参数（body, timeout_express 等）。

        Returns:
            dict: {success, message, data: {trade_no, order_no, amount, ...}}
        """
        if not self.is_configured():
            return {"success": False, "message": "支付宝 AppID 未配置", "data": None}
        trade_no = f"alipay_trade_{int(time.time() * 1000)}"
        logger.info(
            "支付宝支付发起: order=%s amount=%s subject=%s",
            order_no, amount, subject,
        )
        return {
            "success": True,
            "message": "支付请求提交成功（模拟）",
            "data": {
                "trade_no": trade_no,
                "order_no": order_no,
                "amount": amount,
                "subject": subject,
                "buyer_id": buyer_id or "mock_buyer_id",
                "status": "WAIT_BUYER_PAY",
                "pay_url": f"https://pay.alipay.com/?trade_no={trade_no}",
            },
        }

    async def refund(
        self,
        order_no: str,
        refund_amount: str,
        refund_reason: str = "",
        out_request_no: str = "",
    ) -> dict:
        """支付宝退款。

        Args:
            order_no: 商户订单号。
            refund_amount: 退款金额（元）。
            refund_reason: 退款原因。
            out_request_no: 标识一次退款请求（不重复）。

        Returns:
            dict: {success, message, data: {...}}
        """
        refund_no = out_request_no or f"refund_{int(time.time() * 1000)}"
        logger.info(
            "支付宝退款: order=%s amount=%s reason=%s",
            order_no, refund_amount, refund_reason,
        )
        return {
            "success": True,
            "message": "退款请求提交成功（模拟）",
            "data": {
                "order_no": order_no,
                "refund_no": refund_no,
                "refund_amount": refund_amount,
                "status": "REFUND_SUCCESS",
            },
        }

    async def query(self, order_no: str) -> dict:
        """查询支付/退款状态。

        Args:
            order_no: 商户订单号。

        Returns:
            dict: {success, message, data: {...}}
        """
        logger.info("支付宝订单查询: order=%s", order_no)
        return {
            "success": True,
            "message": "查询成功（模拟）",
            "data": {
                "order_no": order_no,
                "trade_no": f"mock_trade_{order_no}",
                "amount": "0.01",
                "status": "TRADE_SUCCESS",
                "paid_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            },
        }
