"""平台集成总线 — Platform Integration Bus。

各平台独立模块，通过 bus.py 统一调度。
当前支持：微信、钉钉、支付宝、抖音、剪映、飞书、腾讯会议。
"""
from .bus import PlatformBus
from .wechat import WeChatClient, WeChatConfig
from .dingtalk import DingTalkClient, DingTalkConfig
from .alipay import AlipayClient, AlipayConfig
from .douyin import DouYinClient, DouYinConfig
from .jianying import JianYingClient, JianYingConfig
from .feishu import FeishuClient, FeishuConfig
from .meeting import MeetingClient, MeetingConfig

__all__ = [
    "PlatformBus",
    "WeChatClient", "WeChatConfig",
    "DingTalkClient", "DingTalkConfig",
    "AlipayClient", "AlipayConfig",
    "DouYinClient", "DouYinConfig",
    "JianYingClient", "JianYingConfig",
    "FeishuClient", "FeishuConfig",
    "MeetingClient", "MeetingConfig",
]
