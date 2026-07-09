"""更新力监测 (Update Monitor) — 检查 Git 提交频率。

每周自动评分，根据：
- 近 7 天提交次数
- 近 30 天提交次数
- 提交间隔规律性

评分标准：
- 100: 日均 ≥2 次提交
- 85:  日均 ≥1 次
- 70:  每周 ≥3 次
- 50:  每周 ≥1 次
- 30:  每月 ≥1 次
- 0:   无更新
"""

from __future__ import annotations

import logging
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class UpdateMonitor:
    """更新力监测器。

    通过检查 Git 提交历史，评估工具的持续更新活跃度。
    支持指定工具路径或项目根路径。
    """

    def __init__(self, repo_path: str | None = None) -> None:
        self._repo_path = repo_path or os.getcwd()
        self._results: dict[str, Any] = {}

    def evaluate(self, tool_name: str, repo_path: str | None = None) -> dict:
        """评估工具的更新力。

        Args:
            tool_name: 工具名称。
            repo_path: Git 仓库路径（可选）。

        Returns:
            dict: {score, commits_7d, commits_30d, weekly_avg, detail}
        """
        result: dict[str, Any] = {
            "name": "update_monitor",
            "tool_name": tool_name,
            "score": 0,
            "commits_7d": 0,
            "commits_30d": 0,
            "weekly_avg": 0.0,
            "detail": "",
            "error": None,
        }

        path = repo_path or self._repo_path

        try:
            # 检查是否为 Git 仓库
            if not os.path.exists(os.path.join(path, ".git")):
                # 从工具名反向推测可能路径
                alt_path = self._find_tool_path(tool_name)
                if alt_path:
                    path = alt_path
                else:
                    result["score"] = 30
                    result["detail"] = f"未找到 Git 仓库（在 {path} 和工具路径中均未找到 .git）"
                    self._results[tool_name] = result
                    return result

            # 获取近 7 天提交数
            commits_7d = self._git_log(path, 7)
            # 获取近 30 天提交数
            commits_30d = self._git_log(path, 30)

            result["commits_7d"] = commits_7d
            result["commits_30d"] = commits_30d
            result["weekly_avg"] = round(commits_30d / 4.33, 1) if commits_30d > 0 else 0.0

            # 评分
            daily_avg = commits_7d / 7.0 if commits_7d > 0 else 0.0
            result["score"] = self._score_updates(daily_avg, commits_7d, commits_30d)
            result["detail"] = (
                f"近 7 天 {commits_7d} 次提交, 近 30 天 {commits_30d} 次提交, "
                f"日均 {daily_avg:.1f} 次"
            )

        except FileNotFoundError:
            result["score"] = 30
            result["detail"] = "Git 未安装，无法检测更新力"
            result["error"] = "git not found"
        except Exception as e:
            result["score"] = 30
            result["detail"] = f"检测异常: {e}"
            result["error"] = str(e)
            logger.warning("更新力监测异常: %s", e)

        self._results[tool_name] = result
        return result

    # ── 辅助 ─────────────────────────────────────────────────

    def _git_log(self, repo_path: str, days: int) -> int:
        """获取指定天数内的 Git 提交数量。"""
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", "--after", since, "--format=%H"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                count = len([l for l in result.stdout.strip().split("\n") if l.strip()])
                return count
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        return 0

    def _find_tool_path(self, tool_name: str) -> str | None:
        """根据工具名尝试定位其路径。"""
        candidates = [
            os.path.expanduser("~"),
            "/opt/starpivot",
            "/home",
            os.getcwd(),
        ]
        for base in candidates:
            if os.path.exists(base):
                # 尝试直接匹配
                for root, dirs, _ in os.walk(base):
                    if tool_name in dirs:
                        git_path = os.path.join(root, tool_name)
                        if os.path.exists(os.path.join(git_path, ".git")):
                            return git_path
                    # 防止遍历太深
                    if root.count(os.sep) > 5:
                        break
        return None

    @staticmethod
    def _score_updates(daily_avg: float, commits_7d: int, commits_30d: int) -> int:
        """根据提交频率评分。"""
        if daily_avg >= 2:
            return 100
        if daily_avg >= 1:
            return 85
        if commits_7d >= 3:
            return 70
        if commits_7d >= 1:
            return 50
        if commits_30d >= 1:
            return 30
        return 0
