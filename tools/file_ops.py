"""AI Agent 工具平台 Tools 执行器 — Agent 调用的工具集合

每个内置工具函数返回 ToolResult，
execute_tool 作为统一入口分发调用。
"""

from __future__ import annotations

import ast
import operator
import os
from dataclasses import dataclass, field
from typing import Any


# ──────────────────────────────────────────────
# 返回值定义
# ──────────────────────────────────────────────

@dataclass
class ToolResult:
    """工具调用的标准返回值。"""
    success: bool
    output: str
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """转为 dict，供 execute_tool 统一返回。"""
        return {"success": self.success, "output": self.output, "error": self.error}


# ──────────────────────────────────────────────
# 内置工具函数（每个返回 ToolResult）
# ──────────────────────────────────────────────



# === file tools ===


def read_file(path: str, **kwargs) -> ToolResult:
    """读取文件内容。

    Args:
        path: 文件路径（绝对或相对）。

    Returns:
        ToolResult: success=True 时 output 为文件内容。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return ToolResult(success=True, output=content)
    except FileNotFoundError:
        return ToolResult(success=False, output="", error=f"文件不存在: {path}")
    except IsADirectoryError:
        return ToolResult(success=False, output="", error=f"路径是目录，不是文件: {path}")
    except Exception as e:
        return ToolResult(success=False, output="", error=f"读取文件失败: {e}")



def write_file(path: str, content: str, **kwargs) -> ToolResult:
    """写入文件内容（覆盖写入，自动创建父目录）。

    安全限制：只允许写入 /opt/starpivot/user_files/{user_id}/outputs/ 目录。

    Args:
        path: 文件路径（相对于用户 outputs 目录）。
        content: 写入的文本内容。

    Returns:
        ToolResult: success=True 时 output 为写入成功提示。
    """
    try:
        # 安全限制：只允许写入 user_files/{user_id}/outputs/ 目录
        base_dir = "/opt/starpivot/user_files"
        agent = kwargs.get("_agent", {})
        user_id = agent.get("user_id", "")

        if not user_id:
            return ToolResult(success=False, output="", error="无法确定用户身份，拒绝写入")

        safe_dir = os.path.normpath(os.path.join(base_dir, user_id, "outputs"))
        os.makedirs(safe_dir, exist_ok=True)

        # 如果 path 是绝对路径，强制重新解释为相对路径
        target = os.path.normpath(os.path.join(safe_dir, path.lstrip("/")))
        if not target.startswith(safe_dir):
            return ToolResult(success=False, output="", error="无权写入此路径（超出安全目录）")

        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)
        return ToolResult(success=True, output=f"文件已写入: {target}")
    except Exception as e:
        return ToolResult(success=False, output="", error=f"写入文件失败: {e}")



def list_files(path: str = ".", **kwargs) -> ToolResult:
    """列出目录下的文件和文件夹。

    安全限制：只允许列出 /opt/starpivot/user_files/{user_id}/ 目录。

    Args:
        path: 目录路径（相对于用户目录，默认 "."）。

    Returns:
        ToolResult: success=True 时 output 为文件和文件夹列表（每行一个）。
    """
    try:
        # 安全限制：只允许列出 user_files/{user_id}/ 目录
        base_dir = "/opt/starpivot/user_files"
        agent = kwargs.get("_agent", {})
        user_id = agent.get("user_id", "")

        if not user_id:
            return ToolResult(success=False, output="", error="无法确定用户身份，拒绝列出")

        safe_dir = os.path.normpath(os.path.join(base_dir, user_id))
        # 如果 path 是绝对路径，强制重新解释为相对路径
        target = os.path.normpath(os.path.join(safe_dir, path.lstrip("/")))
        if not target.startswith(safe_dir):
            return ToolResult(success=False, output="", error="无权访问此目录（超出安全目录）")

        entries = os.listdir(target)
        lines: list[str] = []
        for entry in sorted(entries):
            full = os.path.join(target, entry)
            suffix = "/" if os.path.isdir(full) else ""
            lines.append(f"{entry}{suffix}")
        return ToolResult(success=True, output="\n".join(lines))
    except FileNotFoundError:
        return ToolResult(success=False, output="", error=f"目录不存在: {path}")
    except NotADirectoryError:
        return ToolResult(success=False, output="", error=f"路径不是目录: {path}")
    except Exception as e:
        return ToolResult(success=False, output="", error=f"列出目录失败: {e}")



def read_user_file(filepath: str, **_kwargs) -> ToolResult:
    """读取用户文件（只允许读取 /opt/starpivot/user_files/ 目录下的文件）。

    Args:
        filepath: 文件路径（相对于用户目录，如 "outputs/20260629_notice.md"）
    """
    import os

    # 安全限制：只允许读取 user_files 目录
    base_dir = "/opt/starpivot/user_files"
    # 从 _kwargs 中获取 user_id
    agent = _kwargs.get("_agent", {})
    user_id = agent.get("user_id", "")

    if not user_id:
        return ToolResult(success=False, output="", error="无法确定用户身份")

    safe_path = os.path.normpath(os.path.join(base_dir, user_id, filepath))
    # 检查路径是否在安全目录内
    if not safe_path.startswith(os.path.normpath(os.path.join(base_dir, user_id))):
        return ToolResult(success=False, output="", error="无权访问此文件")

    if not os.path.exists(safe_path):
        return ToolResult(success=False, output="", error=f"文件不存在: {filepath}")

    try:
        with open(safe_path, "r", encoding="utf-8") as f:
            content = f.read(50000)  # 最多读 50KB
        return ToolResult(success=True, output=content)
    except Exception as e:
        return ToolResult(success=False, output="", error=f"读取失败: {e}")


