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



# === agent tools ===


def call_agent(target_agent_id: str, message: str, task_type: str = "notify", **_kwargs) -> ToolResult:
    """向另一个Agent发送协作任务。

    将此任务写入 workflow_tasks 表，目标Agent稍后可以查看和处理。

    Args:
        target_agent_id: 目标Agent的ID（如 ST03, ST04, ST05）。
        message: 要传递的消息内容。
        task_type: 任务类型（notify=通知, request=请求, approve=审批, audit=审计）。

    Returns:
        ToolResult: 包含任务ID和状态。
    """
    try:
        import uuid
        from store.db import get_db
        db = get_db()
        task_id = "WT" + uuid.uuid4().hex[:12]
        db._execute_write(
            "INSERT INTO workflow_tasks (id, from_agent_id, to_agent_id, task_type, message, status) VALUES (?, ?, ?, ?, ?, 'pending')",
            (task_id, _kwargs.get("_agent", {}).get("id", "unknown"), target_agent_id, task_type, message)
        )
        return ToolResult(success=True, output=f"任务已发送: {task_id} → {target_agent_id} ({task_type})")
    except Exception as e:
        return ToolResult(success=False, output="", error=f"call_agent 失败: {e}")



def skills_execute(skill_id: str, **kwargs) -> ToolResult:
    """执行技能系统中的指定技能。

    通过 skill_id 在技能注册表中查找并路由到：
    - 内置工具（builtin_tool）
    - MCP服务器（mcp_server + mcp_tool）
    - AI原生能力（无后端）

    Args:
        skill_id: 技能ID（如 "browser_navigate", "web_search"）。
        **kwargs: 传递给技能的参数。

    Returns:
        ToolResult: 执行结果。
    """
    try:
        from core.skills.skill_manager import SkillManager
        manager = SkillManager()
        # 构造一个最小的 agent 上下文
        agent = {"id": "system", "tier": "正常", "star_level": 5, "name": "System"}
        result = manager.execute_skill(skill_id, kwargs, agent)
        if isinstance(result, dict):
            return ToolResult(
                success=result.get("success", False),
                output=result.get("output", ""),
                error=result.get("error"),
            )
        return ToolResult(success=True, output=str(result))
    except Exception as e:
        return ToolResult(success=False, output="", error=f"skills_execute 失败: {e}")



def get_skill_system_tools() -> list[dict]:
    """获取技能系统提供的工具列表。

    以星级5返回所有技能的工具描述。
    用于有完整工具访问权限的场景。

    Returns:
        list[dict]: 工具描述列表。
    """
    try:
        from core.skills.skill_manager import SkillManager
        manager = SkillManager()
        return manager.get_tools_for_star_level(5)
    except ImportError:
        return []
    except Exception as e:
        logger = __import__("logging").getLogger(__name__)
        logger.warning("获取技能系统工具失败: %s", e)
        return []



def get_skills_stats() -> dict:
    """获取技能系统统计信息。"""
    try:
        from core.skills.skill_manager import SkillManager
        manager = SkillManager()
        return manager.get_stats()
    except ImportError:
        return {"total_skills": 0, "error": "技能系统未加载"}
    except Exception as e:
        return {"total_skills": 0, "error": str(e)}


# 注册 ocr_image 到工具注册表
_TOOL_REGISTRY["ocr_image"] = (
    ocr_image,
    [
        {
            "name": "filepath",
            "type": "string",
            "description": "图片文件路径（支持 JPG/PNG/BMP/TIFF）",
            "required": True,
        },
    ],
)

# 注册 skills_execute 到工具注册表
_TOOL_REGISTRY["skills_execute"] = (
    skills_execute,
    [
        {
            "name": "skill_id",
            "type": "string",
            "description": "要调用的技能ID，如 browser_navigate、web_search、read_file 等",
            "required": True,
        },
    ],
)

# 注册 generate_image 到工具注册表
_TOOL_REGISTRY["generate_image"] = (
    generate_image,
    [
        {
            "name": "description",
            "type": "string",
            "description": "图片内容描述（如「一座星空下的山峰」）",
            "required": True,
        },
        {
            "name": "style",
            "type": "string",
            "description": "视觉风格：modern/minimal/colorful/sketch/vintage",
            "required": False,
            "default": "modern",
        },
        {
            "name": "width",
            "type": "number",
            "description": "SVG 画布宽度（默认 800）",
            "required": False,
            "default": 800,
        },
        {
            "name": "height",
            "type": "number",
            "description": "SVG 画布高度（默认 600）",
            "required": False,
            "default": 600,
        },
    ],
)

# 注册 compose_poster 到工具注册表
_TOOL_REGISTRY["compose_poster"] = (
    compose_poster,
    [
        {
            "name": "title",
            "type": "string",
            "description": "海报标题",
            "required": True,
        },
        {
            "name": "subtitle",
            "type": "string",
            "description": "副标题（可选）",
            "required": False,
            "default": "",
        },
        {
            "name": "body",
            "type": "string",
            "description": "正文内容（可选，支持 HTML 标签）",
            "required": False,
            "default": "",
        },
        {
            "name": "image_path",
            "type": "string",
            "description": "图片路径（可选，用于海报中的插图）",
            "required": False,
            "default": "",
        },
        {
            "name": "style",
            "type": "string",
            "description": "视觉风格：modern/tech/elegant/colorful/vintage",
            "required": False,
            "default": "modern",
        },
    ],
)

# 注册 call_agent 到工具注册表
_TOOL_REGISTRY["call_agent"] = (
    call_agent,
    [
        {
            "name": "target_agent_id",
            "type": "string",
