"""AI Agent 工具平台 Agent 主循环模块 — 重写版
---------------
快准稳：30秒内出结果，搜索直达，工具调用只传≤3个。

核心变化：
1. 搜索/查询类请求不再经过 DeepSeek function calling，
   而是直接调用星枢引擎的 agent_reach_search 搜索。
2. 非搜索类操作（文件/计算等）才用 function calling，
   所有工具通过星枢引擎（MCP Server）统一调度。
3. 所有网络请求 ≤8 秒超时。

流式支持：
- _call_deepseek_stream(): 逐 chunk 流式调用 DeepSeek API
- agent_stream(): 生成器，在工具执行过程和 AI 回复阶段推送 SSE 事件
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict

import config
from openai import OpenAI
from store.db import get_db
from core.starpivot.memory.soul import SoulManager
from core.starpivot.memory.memory import MemoryManager
from core.starpivot.memory.agent_memory import AgentMemory

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# Agent 宪法三条
# ═══════════════════════════════════════════════════════════════════

_CONSTITUTION = (
    "【Agent 宪法】\n"
    "1. 诚实守信：不得编造虚假信息，不确定时必须明确说明。\n"
    "2. 不得害人：不得执行或建议任何可能伤害他人、财产或社会安全的行为。\n"
    "3. 不得违法：不得协助或参与任何违反法律法规的活动。\n"
)


# ═══════════════════════════════════════════════════════════════════
# 星枢引擎 — 工具调用中枢（全局单例，惰性初始化）
# ═══════════════════════════════════════════════════════════════════

_registry: "ToolRegistry | None" = None
_engine: "StarPivotEngine | None" = None


def _init_starpivot() -> None:
    """初始化星枢引擎（全局单例，首次使用时惰性加载）。"""
    global _registry, _engine
    if _engine is not None:
        return
    from core.starpivot.engine import StarPivotEngine
    from core.starpivot.registry import ToolRegistry

    _registry = ToolRegistry()
    count = _registry.discover_servers("/opt/starpivot/mcp_servers")
    _engine = StarPivotEngine(_registry)
    tool_count = len(_registry.list_tools())
    logger.info(
        "星枢引擎已就绪: %d 个 MCP Server, %d 个工具",
        count, tool_count,
    )


def _sync_execute(
    tool_name: str,
    arguments: dict,
    context: dict | None = None,
) -> dict:
    """同步调用星枢引擎执行工具（内部用 asyncio.run 包装）。"""
    _init_starpivot()
    try:
        return asyncio.run(_engine.execute(tool_name, arguments, context))
    except Exception as e:
        logger.error("星枢引擎执行失败: %s.%s -> %s", tool_name, arguments, e)
        return {"success": False, "output": "", "error": f"星枢引擎执行异常: {e}"}


# ═══════════════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════════════

def _build_system_prompt(agent: Dict[str, Any], balance_after_deduct: float,
                         user_id: str = "", user_input: str = "") -> str:
    """构建系统提示词：铁律 → SOUL.md → 用户设定 → 宪法 → 工具感知 → 记忆注入。

    合成顺序（从最不可覆盖到最可补充）：
      1. 【铁律（锁死，用户写，优先级最高）】
      2. 【SOUL.md 正文（≥5000 字，定义角色身份）】
      3. 【用户 system_prompt 设定】
      4. 【Agent 宪法三条】
      5. 【余额信息】
      6. 【工具感知（自动生成）】
      7. 【记忆注入（热记忆 + 温记忆）】

    Args:
        agent:               Agent 字典。
        balance_after_deduct: 扣费后余额。
        user_id:              用户 ID（用于记忆注入）。
        user_input:           用户输入（用于冷记忆关键词检测）。

    Returns:
        完整 system_prompt 字符串。
    """
    from core.starpivot.memory.soul import SoulManager
    from core.starpivot.memory.memory import MemoryManager

    soul_mgr = SoulManager()
    parts = []

    # ── 1. 铁律（锁死） ──
    ironclad = soul_mgr.get_ironclad(agent["id"])
    if ironclad:
        parts.append(f"【铁律 — 不可违反，优先级最高】\n{ironclad}\n")

    # ── 2. SOUL.md 正文 ──
    soul_content = soul_mgr.get_soul_content(agent["id"])
    if soul_content:
        parts.append(f"【底层人格 — 不可更改】\n{soul_content}\n")

    # ── 3. 用户 system_prompt 设定 ──
    user_edits = agent.get('system_prompt', '').strip()
    if user_edits:
        parts.append(f"【用户设定】\n{user_edits}\n")

    # ── 4. Agent 宪法三条 ──
    parts.append(f"你是 {agent['name']}（ID: {agent['id']}），"
                 f"一个 {agent['tier']} 层级的 AI Agent。\n"
                 f"{_CONSTITUTION}"
                 f"当前余额：{balance_after_deduct:.2f} 积分\n")

    # ── 5. 工具感知 ──
    _init_starpivot()
    tool_count = 0
    tool_names = []
    try:
        tools = _registry.list_tools()
        tool_count = len(tools)
        tool_names = [t.name for t in tools[:30]]
    except Exception:
        pass

    if tool_count > 0:
        names_str = "、".join(tool_names)
        if tool_count > 30:
            names_str += f"、……共 {tool_count} 种"
        parts.append(
            f"\n【你的能力】\n"
            f"你拥有 {tool_count} 种工具能力，覆盖搜索、文件、图片、语音、视频、"
            f"文档、数据、代码、支付、平台集成、模型调用等各个领域。\n"
            f"当用户需要你执行某项任务时，主动判断是否需要使用工具，并调用相应的能力。\n"
            f"不要主动说自己能力有限——你有的工具比你想象的更多。\n"
            f"可用工具（部分）：{names_str}"
        )

    # ── 6. 记忆注入（热记忆 + 温记忆） ──
    if user_id:
        try:
            mem_mgr = MemoryManager(agent["id"], user_id)
            memory_block = mem_mgr.inject()
            if memory_block and memory_block != "":
                parts.append(memory_block)

            # ── 冷记忆检索：当用户提到"之前""上次"等关键词 ──
            cold_keywords = _detect_cold_memory_keywords(user_input or "")
            if cold_keywords:
                cold_results = mem_mgr.recall(cold_keywords)
                if cold_results:
                    cold_lines = []
                    for m in cold_results[:5]:
                        cold_lines.append(f"  - {m['content']}")
                    parts.append(
                        "\n\n【历史记忆检索 — 按需加载】\n"
                        + "\n".join(cold_lines)
                        + "\n（这些是你在更早之前和用户交流中了解到的信息）\n"
                    )
        except Exception as e:
            logger.warning("记忆注入失败（非致命）: %s", e)

    return "\n".join(parts)


def _call_deepseek(
    messages: list,
    api_key: str,
    base_url: str,
    model: str,
    timeout: int = 15,
) -> str:
    """调用 DeepSeek API 做推理，返回 assistant 回复文本。

    Args:
        messages: 符合 OpenAI 格式的消息列表。
        api_key: DeepSeek API Key。
        base_url: API 基础地址。
        model: 模型名称。
        timeout: 请求超时秒数（默认 15）。

    Returns:
        API 返回的 assistant 消息 content。

    Raises:
        RuntimeError: API 调用失败时抛出。
    """
    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.7,
            max_tokens=2000,
            timeout=timeout,
        )
    except Exception as e:
        raise RuntimeError(f"DeepSeek API 调用失败: {e}")

    if not response.choices or len(response.choices) == 0:
        raise RuntimeError(f"DeepSeek API 返回无 choices: {response}")

    return response.choices[0].message.content or ""


def _call_deepseek_full(
    messages: list,
    api_key: str,
    base_url: str,
    model: str,
    tools: list | None = None,
    timeout: int = 15,
) -> tuple:
    """调用 DeepSeek API，返回 (content, tool_calls, full_message)。

    支持 tools（function calling）参数。

    Returns:
        (content: str|None, tool_calls: list|None, full_message)

    Raises:
        RuntimeError: API 调用失败时抛出。
    """
    kwargs = dict(
        model=model,
        messages=messages,
        temperature=0.7,
        max_tokens=4000,
        timeout=timeout,
    )
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        response = client.chat.completions.create(**kwargs)
    except Exception as e:
        raise RuntimeError(f"DeepSeek API 调用失败: {e}")

    if not response.choices or len(response.choices) == 0:
        raise RuntimeError(f"DeepSeek API 返回无 choices: {response}")

    message = response.choices[0].message
    return message.content, message.tool_calls, message


# ═══════════════════════════════════════════════════════════════════
# 智能搜索 — 不走 function calling，直接抓取
# ═══════════════════════════════════════════════════════════════════

def _is_search_query(text: str) -> bool:
    """判断用户输入是否为搜索/查询类请求。

    搜索类请求走星枢引擎搜索，不走 AI function calling。
    """
    keywords = [
        "搜", "找", "查", "新闻", "今天", "最近", "查询", "搜索", "查找",
        "哪里", "多少", "统计", "数据", "分析", "热点", "热搜", "头条",
        "天气", "汇率", "股票", "价格", "谁", "什么是", "怎么样",
        "最新", "消息", "报道", "时讯",
    ]
    t = text.lower().strip()
    # 短文本（≤10字）包含关键词 → 搜索
    if len(t) <= 10 and any(kw in t for kw in keywords):
        return True
    # 长文本包含搜索特征
    if any(kw in t for kw in keywords[:12]):
        return True
    # 问句
    if t.startswith(("什么", "怎么", "如何", "为啥", "为什么", "哪", "谁")):
        return True
    return False


# ═══════════════════════════════════════════════════════════════════
# 冷记忆检索关键词检测
# ═══════════════════════════════════════════════════════════════════

_COLD_MEMORY_KEYWORDS = [
    "之前", "以前", "上次", "上回", "上次说", "之前说",
    "我记得", "你还记得", "你记得", "我说过", "提过",
    "前面", "刚才", "早先", "此前",
]


def _detect_cold_memory_keywords(text: str) -> str:
    """检测用户输入是否包含冷记忆检索关键词。

    Args:
        text: 用户输入文本。

    Returns:
        匹配的关键词字符串，如果没有匹配则返回空字符串。
    """
    if not text:
        return ""
    for kw in _COLD_MEMORY_KEYWORDS:
        if kw in text:
            # 返回匹配到的关键词作为检索词
            return kw
    return ""


def _save_conversation_memory(agent_id: str, user_id: str,
                              user_input: str, assistant_reply: str,
                              messages: list | None = None) -> None:
    """保存对话记忆：热记忆 + 自动提取温记忆 + 自动摘要。

    1. 将本轮对话保存为热记忆（Tier 1）
    2. 从用户输入中自动提取温记忆（姓名、职业、偏好等）
    3. 调用 auto_summarize 生成对话摘要（agentmemory 风格）

    Args:
        agent_id:       Agent ID。
        user_id:        用户 ID。
        user_input:     用户输入。
        assistant_reply: AI 回复（用于生成摘要）。
        messages:       完整的消息列表（用于 auto_summarize）。
    """
    if not user_id:
        return
    try:
        from core.starpivot.memory.memory import MemoryManager
        mem_mgr = MemoryManager(agent_id, user_id)

        # ── 保存热记忆 ──
        hot_summary = f"用户: {user_input[:100]} | AI: {assistant_reply[:100]}"
        mem_mgr.memorize(
            content=hot_summary,
            importance=0.5,
            tier=1,
            source="conversation",
            keywords="",
        )

        # ── 自动提取温记忆 ──
        mem_mgr.extract_from_text(user_input)

        # ── 自动摘要（agentmemory 风格） ──
        if messages:
            mem_mgr.auto_summarize(messages)

    except Exception as e:
        logger.warning("对话记忆保存失败（非致命）: %s", e)

# ═══════════════════════════════════════════════════════════════════
# 工具判断 — 需要 function calling 的场景
# ═══════════════════════════════════════════════════════════════════

_NON_SEARCH_TOOL_KEYWORDS = [
    "读", "写", "打开", "文件", "保存", "目录", "列表", "上传",
    "生成", "画", "图片", "海报", "ocr", "识别", "pdf",
    "计算", "转换", "翻译", "语音", "下载", "视频",
]


def _needs_non_search_tools(user_input: str) -> bool:
    """判断用户输入是否需要非搜索类工具（文件/计算/生成等）。

    只有这些才走 function calling。
    """
    text = user_input.lower()
    return any(kw in text for kw in _NON_SEARCH_TOOL_KEYWORDS)

