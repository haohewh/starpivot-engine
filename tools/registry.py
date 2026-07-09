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


def execute_tool(name: str, args: dict, agent: dict) -> dict:
    """执行指定名称的工具。

    根据 name 在工具注册表中查找并调用对应的工具函数。
    如果 name 不在内置工具列表中，检查是否是技能系统中的技能。
    如果技能系统中有 MCP 技能，路由到 MCPManager。

    Args:
        name: 工具名称（如 "read_file", "calculate"）。
        args: 工具参数字典（如 {"path": "test.txt"}）。
        agent: Agent 上下文信息（传递给工具函数的 _agent 关键字参数）。

    Returns:
        dict: 包含 success(bool), output(str), error(str|None) 的字典。
    """
    # ── 首先检查内置工具注册表 ──
    if name in _TOOL_REGISTRY:
        func, _ = _TOOL_REGISTRY[name]
        try:
            result = func(**args, _agent=agent)
        except TypeError as e:
            return ToolResult(
                success=False, output="", error=f"工具 '{name}' 参数错误: {e}"
            ).to_dict()
        except Exception as e:
            return ToolResult(
                success=False, output="", error=f"工具 '{name}' 执行异常: {e}"
            ).to_dict()

        # 兼容：如果返回已经是 dict（如市场工具），直接返回
        if isinstance(result, dict):
            return result
        return result.to_dict()

    # ── 然后检查技能系统中的技能 ──
    try:
        from core.skills.skill_manager import SkillManager
        manager = SkillManager()
        return manager.execute_skill(name, args, agent)
    except ImportError:
        pass
    except Exception as e:
        return ToolResult(
            success=False, output="", error=f"技能 '{name}' 执行异常: {e}"
        ).to_dict()

    # ── 两者都不是 ──
    return ToolResult(success=False, output="", error=f"未知工具/技能: {name}").to_dict()


def get_available_tools() -> list[dict]:
    """获取所有内置工具的名称和参数描述。

    返回列表供 Agent 系统提示词或工具选择逻辑使用。
    不包含技能系统中的技能（技能由 agent_loop 按星级动态加载）。

    Returns:
        list[dict]: 每个元素包含 name 和 parameters 字段。
    """
    tools: list[dict] = []
    for name, (func, params) in _TOOL_REGISTRY.items():
        tools.append({
            "name": name,
            "description": (func.__doc__ or "").strip().split("\n\n")[0],
            "parameters": params,
        })
    return tools


# ──────────────────────────────────────────────
# 技能系统集成工具
# ──────────────────────────────────────────────

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
            "description": "目标Agent的ID（如 ST03, ST04, ST05）",
            "required": True,
        },
        {
            "name": "message",
            "type": "string",
            "description": "要传递的消息内容",
            "required": True,
        },
        {
            "name": "task_type",
            "type": "string",
            "description": "任务类型：notify=通知, request=请求, approve=审批, audit=审计",
            "required": False,
        },
    ],
)


def generate_image_freeapi(prompt: str, size: str = "1024x1024", **_kwargs) -> ToolResult:
    """通过 MiniMax API 生成图片。"""
    import os, uuid, time, requests, json as _json

    # 读取 MiniMax API Key
    api_key = os.environ.get("MINIMAX_API_KEY", "")
    if not api_key:
        env_file = os.path.expanduser("~/.hermes/.env")
        if os.path.exists(env_file):
            for line in open(env_file):
                if line.startswith("MINIMAX_API_KEY="):
                    api_key = line.strip().split("=", 1)[1].strip()
                    break
    if not api_key:
        return ToolResult(success=False, output="", error="未配置 MINIMAX_API_KEY")
    try:
        resp = requests.post(
            "https://api.minimax.chat/v1/image_generation",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": "image-01", "prompt": prompt, "n": 1},
            timeout=60,
        )
        result = resp.json()

        # 保存原始响应
        out_dir = "/opt/starpivot/output"
        os.makedirs(out_dir, exist_ok=True)
        meta_fp = os.path.join(out_dir, f"minimax_resp_{uuid.uuid4().hex[:8]}_{int(time.time())}.json")
        with open(meta_fp, "w", encoding="utf-8") as f:
            _json.dump(result, f, ensure_ascii=False, indent=2)

        # 提取图片 URL — MiniMax 响应格式: {"data": {"image_urls": ["..."]}}
        img_url = None
        data_obj = result.get("data")
        if isinstance(data_obj, dict):
            urls = data_obj.get("image_urls", [])
            if urls:
                img_url = urls[0]
        elif isinstance(data_obj, list):
            img_url = data_obj[0].get("image_url") or data_obj[0].get("url")

        if not img_url:
            return ToolResult(success=True, output=f"API 响应已保存，未找到图片 URL: {_json.dumps(result, ensure_ascii=False)[:300]}")

        # 下载图片
        img_resp = requests.get(img_url, timeout=60)
        img_resp.raise_for_status()

        ext = "png"
        # 尝试从 Content-Type 判断扩展名
        ct = img_resp.headers.get("Content-Type", "")
        if "jpeg" in ct or "jpg" in ct:
            ext = "jpg"
        elif "gif" in ct:
            ext = "gif"
        elif "webp" in ct:
            ext = "webp"

        img_fp = os.path.join(out_dir, f"minimax_img_{uuid.uuid4().hex[:8]}_{int(time.time())}.{ext}")
        with open(img_fp, "wb") as f:
            f.write(img_resp.content)

        return ToolResult(success=True, output=f"图片已生成: {img_fp}\nURL: {img_url}")
    except Exception as e:
        return ToolResult(success=False, output="", error=f"MiniMax 生图失败: {e}")


_TOOL_REGISTRY["generate_image_freeapi"] = (
    generate_image_freeapi,
    [
        {"name":"prompt","type":"string","description":"图片描述","required":True},
        {"name":"size","type":"string","description":"图片尺寸","required":False},
    ],
)

# ── 新增工具：读用户文件 + 只读SQL查询 ─────────

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


def query_database(sql: str, **_kwargs) -> ToolResult:
    """执行 SQL 查询（只允许 SELECT 语句，只读）。

    Args:
        sql: SQL 查询语句（仅 SELECT 允许）
    """
    import re, sqlite3, os, json

    # 安全检查：只允许 SELECT
    sql_stripped = sql.strip().upper()
    if not sql_stripped.startswith("SELECT"):
        return ToolResult(success=False, output="", error="只允许 SELECT 查询")

    db_path = "/opt/starpivot/data/starpivot.db"
    if not os.path.exists(db_path):
        return ToolResult(success=False, output="", error="数据库不存在")

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(sql)
        rows = cursor.fetchmany(20)  # 最多返回 20 行
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        result = []
        for row in rows:
            result.append(dict(row))
        conn.close()
        return ToolResult(success=True, output=json.dumps({"columns": columns, "rows": result}, ensure_ascii=False, indent=2))
    except Exception as e:
        return ToolResult(success=False, output="", error=f"查询失败: {e}")


# 注册 read_user_file
_TOOL_REGISTRY["read_user_file"] = (
    read_user_file,
    [
        {"name": "filepath", "type": "string", "description": "文件路径，如 outputs/20260629_notice.md", "required": True},
    ],
)

# 注册 query_database
_TOOL_REGISTRY["query_database"] = (
    query_database,
    [
        {"name": "sql", "type": "string", "description": "SELECT 查询语句", "required": True},
    ],
)


# ── PDF 转 Word ──────────────────────────


def pdf_to_word(pdf_path: str, **_kwargs) -> ToolResult:
    """将 PDF 文件转换为 Word 文档。

    Args:
        pdf_path: PDF 文件路径（/opt/starpivot/user_files/{user_id}/ 下）

    Returns:
        ToolResult: success=True 时 output 为输出的文件名。
    """
    import os
    from pdf2docx import parse

    agent = _kwargs.get("_agent", {})
    user_id = agent.get("user_id", "")
    if not user_id:
        return ToolResult(success=False, output="", error="无法确定用户身份")

    base_dir = "/opt/starpivot/user_files"
    safe_input = os.path.normpath(os.path.join(base_dir, user_id, pdf_path))
    if not safe_input.startswith(os.path.normpath(os.path.join(base_dir, user_id))):
        return ToolResult(success=False, output="", error="无权访问此文件")

    if not os.path.exists(safe_input):
        return ToolResult(success=False, output="", error=f"文件不存在: {pdf_path}")

    # 输出文件名
    output_name = os.path.splitext(os.path.basename(pdf_path))[0] + ".docx"
    output_dir = os.path.join(base_dir, user_id, "outputs")
    os.makedirs(output_dir, exist_ok=True)
    safe_output = os.path.join(output_dir, output_name)

    try:
        parse(safe_input, safe_output)
        return ToolResult(success=True, output=f"转换成功: {output_name}")
    except Exception as e:
        return ToolResult(success=False, output="", error=f"转换失败: {e}")


_TOOL_REGISTRY["pdf_to_word"] = (
    pdf_to_word,
    [
        {"name": "pdf_path", "type": "string", "description": "PDF 文件路径", "required": True},
    ],
)

def read_hot_news(dummy: str = "", **_kwargs) -> ToolResult:
    """读取今日热点新闻。用 requests 读取多个新闻源后汇总。"""
    try:
        import requests
        from bs4 import BeautifulSoup
        results = []
        
        # 源1：百度热搜
        try:
            r = requests.get("https://top.baidu.com/board?tab=realtime", timeout=8,
                headers={"User-Agent": "Mozilla/5.0"})
            soup = BeautifulSoup(r.text, "html.parser")
            items = soup.select(".category-wrap_iQLoo .content_1YWBm")
            for item in items[:10]:
                title = item.get_text(strip=True)
                if title:
                    results.append(f"【百度】{title}")
        except:
            pass
        
        # 源2：今日热榜
        try:
            r = requests.get("https://tophub.today/c/news", timeout=8,
                headers={"User-Agent": "Mozilla/5.0"})
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.select("a")[:15]:
                txt = a.get_text(strip=True)
                if txt and len(txt) > 6:
                    results.append(f"【热榜】{txt}")
        except:
            pass
        
        if results:
            return ToolResult(success=True, output="\n".join(results[:20]))
        return ToolResult(success=False, output="", error="无法获取新闻")
    except Exception as e:
        return ToolResult(success=False, output="", error=str(e))

_TOOL_REGISTRY["read_hot_news"] = (
    read_hot_news,
    [
        {"name": "dummy", "type": "string", "description": "任意值", "required": False},
    ],
)
