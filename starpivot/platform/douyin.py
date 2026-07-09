"""抖音平台模块 — DouYin (Douyin) Integration。

封装抖音视频上传、数据查询接口。
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
class DouYinConfig:
    """抖音平台凭证。"""
    client_key: str = ""
    client_secret: str = ""
    open_id: str = ""


class DouYinClient:
    """抖音客户端 — 视频上传 / 数据查询。

    此版本为骨架实现，返回模拟数据供集成测试。
    生产环境请接入抖音开放 API (https://open.douyin.com)。
    """

    def __init__(self, config: DouYinConfig | None = None) -> None:
        self.config = config or DouYinConfig()
        self._access_token: str = ""
        self._token_expires: float = 0

    def configure(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
        logger.info("抖音凭证已更新: %s", list(kwargs.keys()))

    def is_configured(self) -> bool:
        return bool(self.config.client_key and self.config.client_secret)

    async def _get_access_token(self) -> str:
        if self._access_token and time.time() < self._token_expires - 60:
            return self._access_token
        self._access_token = f"mock_dy_token_{int(time.time())}"
        self._token_expires = time.time() + 7200
        return self._access_token

    async def upload_video(self, video_path: str, title: str = "",
                           description: str = "",
                           hashtags: list[str] | None = None) -> dict:
        """上传视频到抖音。

        Args:
            video_path: 视频文件路径。
            title: 视频标题。
            description: 视频描述。
            hashtags: 话题标签列表。

        Returns:
            dict: {success, message, data: {video_id, share_url}}
        """
        await self._get_access_token()
        logger.info("抖音视频上传: path=%s title=%s", video_path, title)
        return {
            "success": True,
            "message": "视频上传成功（模拟）",
            "data": {
                "video_id": f"mock_video_{int(time.time() * 1000)}",
                "share_url": f"https://www.douyin.com/video/mock_{int(time.time())}",
                "title": title,
                "status": "processing",
            },
        }

    async def get_video_data(self, video_id: str) -> dict:
        """获取抖音视频数据（播放量、点赞、评论等）。

        Args:
            video_id: 视频 ID。

        Returns:
            dict: {success, message, data: {stats}}
        """
        await self._get_access_token()
        logger.info("抖音视频数据查询: video_id=%s", video_id)
        return {
            "success": True,
            "message": "视频数据获取成功（模拟）",
            "data": {
                "video_id": video_id,
                "play_count": 12345,
                "like_count": 567,
                "comment_count": 89,
                "share_count": 34,
                "collect_count": 234,
                "avg_watch_seconds": 45.6,
            },
        }
