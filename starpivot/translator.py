"""星枢引擎 — 模型格式转换器 (ModelTranslator)

将 MCP 工具定义 (ToolDefinition) 转为各 LLM 平台支持的 function calling 格式。
支持平台:
    - DeepSeek (OpenAI 兼容格式 + XML 兜底格式)
    - 通义千问 (Qwen)
    - OpenAI 原生格式

同时提供 parse_tool_calls 方法，从 LLM 的响应中统一提取工具调用信息。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from .registry import ToolDefinition

logger = logging.getLogger(__name__)


class ModelTranslator:
    """将 MCP 工具定义转为各 LLM 支持的格式。

    所有方法均为静态/类方法，可直接调用无需实例化。

    用法:
        tools = registry.list_tools()
        deepseek_tools = ModelTranslator.to_deepseek(tools)
        qwen_tools = ModelTranslator.to_qwen(tools)
        calls = ModelTranslator.parse_tool_calls(response, "deepseek")
    """

    # ──────────────────────────────────────────────
    # 格式转换：工具定义 → LLM 格式
    # ──────────────────────────────────────────────

    @staticmethod
    def to_openai(tools: list[ToolDefinition]) -> list[dict]:
        """转为 OpenAI function calling 格式（最通用）。

        Args:
            tools: 工具定义列表。

        Returns:
            符合 OpenAI tools 参数格式的列表。
        """
        openai_tools: list[dict] = []
        for tool in tools:
            properties: dict[str, dict] = {}
            required: list[str] = []
            schema = tool.input_schema or {}
            params = schema.get("properties", {})

            for pname, pdef in params.items():
                properties[pname] = {
                    "type": pdef.get("type", "string"),
                    "description": pdef.get("description", ""),
                }
                if pname in schema.get("required", []):
                    required.append(pname)

            func_def: dict[str, Any] = {
                "name": tool.name,
                "description": tool.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                },
            }
            if required:
                func_def["parameters"]["required"] = required

            openai_tools.append({
                "type": "function",
                "function": func_def,
            })

        return openai_tools

    @staticmethod
    def to_deepseek(tools: list[ToolDefinition]) -> list[dict]:
        """转为 DeepSeek function calling 格式。

        DeepSeek 兼容 OpenAI 格式，目前 to_deepseek 等同于 to_openai，
        后续版本可能在参数级别做 DeepSeek 特有的优化。

        Args:
            tools: 工具定义列表。

        Returns:
            符合 DeepSeek tools 参数格式的列表。
        """
        return ModelTranslator.to_openai(tools)

    @staticmethod
    def to_deepseek_xml(tools: list[ToolDefinition]) -> str:
        """转为 DeepSeek XML 工具格式（兜底格式）。

        当 DeepSeek JSON mode 不稳定时，用此方式构造 system prompt
        中的工具描述，LLM 会以 XML 格式返回 tool_calls。

        Args:
            tools: 工具定义列表。

        Returns:
            XML 格式的工具描述文本。
        """
        lines: list[str] = ["<tool_calls>"]
        for tool in tools:
            lines.append(f'  <invoke name="{tool.name}">')
            schema = tool.input_schema or {}
            params = schema.get("properties", {})
            for pname, pdef in params.items():
                ptype = pdef.get("type", "string")
                desc = pdef.get("description", "")
                required = pname in schema.get("required", [])
                req_str = " (必需)" if required else " (可选)"
                lines.append(
                    f'    <parameter name="{pname}" type="{ptype}">'
                    f"{desc}{req_str}</parameter>"
                )
            lines.append(f"    <description>{tool.description}</description>")
            lines.append("  </invoke>")
        lines.append("</tool_calls>")
        return "\n".join(lines)

    @staticmethod
    def to_qwen(tools: list[ToolDefinition]) -> list[dict]:
        """转为通义千问 function calling 格式。

        Qwen 使用不同的格式，相比 OpenAI 少了外层的 "type": "function"，
        且参数结构略有不同。

        Args:
            tools: 工具定义列表。

        Returns:
            符合 Qwen tools 参数格式的列表。
        """
        qwen_tools: list[dict] = []
        for tool in tools:
            schema = tool.input_schema or {}
            qwen_tools.append({
                "name": tool.name,
                "description": tool.description,
                "parameters": {
                    "type": "object",
                    "properties": schema.get("properties", {}),
                    "required": schema.get("required", []),
                },
            })
        return qwen_tools

    # ──────────────────────────────────────────────
    # 解析：LLM 响应 → 工具调用
    # ──────────────────────────────────────────────

    @staticmethod
    def parse_tool_calls(
        response: dict, model: str = "deepseek"
    ) -> list[dict[str, Any]]:
        """解析 LLM 返回的 tool calling，支持多种格式。

        支持的格式（自动检测，无需手动指定）:
            1. OpenAI/DeepSeek JSON 格式 (choices[0].message.tool_calls)
            2. DeepSeek XML 格式 (content 中包含 <tool_calls>)
            3. Qwen function calling 格式

        Args:
            response: LLM API 返回的完整响应字典。
            model:    模型名称（用于 hinted 解析策略，默认 "deepseek"）。

        Returns:
            标准化工具调用列表，每项含:
                - name (str):       工具名称
                - arguments (dict):  参数字典
                - id (str):         调用 ID
        """
        model_lower = model.lower()

        # 提取 message
        choices = response.get("choices", [])
        if not choices:
            return []
        message = choices[0].get("message", {})

        # ── Strategy 1: OpenAI 标准 JSON 格式 ──
        tool_calls = message.get("tool_calls")
        if tool_calls:
            return ModelTranslator._parse_openai_tool_calls(tool_calls)

        # ── Strategy 2: DeepSeek XML 格式 ──
        content = message.get("content", "") or ""
        if "<tool_calls>" in content or "<invoke" in content:
            xml_calls = ModelTranslator._parse_xml_tool_calls(content)
            if xml_calls:
                return xml_calls

        # ── Strategy 3: Qwen 格式 ──
        if "qwen" in model_lower or "tongyi" in model_lower:
            return ModelTranslator._parse_qwen_tool_calls(response)

        # 未找到任何工具调用
        return []

    # ── 内部解析实现 ──────────────────────────

    @staticmethod
    def _parse_openai_tool_calls(
        tool_calls: list[dict],
    ) -> list[dict[str, Any]]:
        """解析 OpenAI 标准格式的 tool_calls，含 json-repair 自动修复。"""
        results: list[dict[str, Any]] = []
        for tc in tool_calls:
            func = tc.get("function", {})
            raw_args = func.get("arguments", "{}")
            if isinstance(raw_args, str):
                try:
                    parsed_args = json.loads(raw_args)
                except json.JSONDecodeError:
                    logger.warning(
                        "工具 %s 参数 JSON 解析失败，尝试 json-repair 修复: %s",
                        func.get("name", "?"), raw_args[:100],
                    )
                    try:
                        from json_repair import repair_json
                        repaired = repair_json(raw_args)
                        parsed_args = json.loads(repaired)
                    except Exception:
                        parsed_args = {"query": raw_args[:50]}
            else:
                parsed_args = raw_args

            results.append({
                "name": func.get("name", ""),
                "arguments": parsed_args,
                "id": tc.get("id", ""),
            })
        return results

    @staticmethod
    def _parse_xml_tool_calls(content: str) -> list[dict[str, Any]]:
        """解析 DeepSeek XML 格式的 tool_calls。

        格式:
            <tool_calls>
              <invoke name="tool_name">
                <parameter name="param1">value1</parameter>
              </invoke>
            </tool_calls>
        """
        results: list[dict[str, Any]] = []
        pattern = r'<invoke name="([^"]+)">(.*?)</invoke>'

        for match in re.finditer(pattern, content, re.DOTALL):
            func_name = match.group(1).strip()
            args_text = match.group(2)
            args: dict[str, str] = {}

            # 解析参数
            for p in re.finditer(
                r'<parameter name="([^"]+)"[^>]*>(.*?)</parameter>',
                args_text,
                re.DOTALL,
            ):
                args[p.group(1)] = p.group(2).strip()

            results.append({
                "name": func_name,
                "arguments": args,
                "id": f"call_xml_{abs(hash(func_name)) % 10**8:08x}",
            })

        return results

    @staticmethod
    def _parse_qwen_tool_calls(response: dict) -> list[dict[str, Any]]:
        """解析通义千问格式的 tool_calls。"""
        results: list[dict[str, Any]] = []
        choices = response.get("choices", [])
        if not choices:
            return results

        message = choices[0].get("message", {})
        tool_calls = message.get("tool_calls", [])

        for tc in tool_calls:
            if not isinstance(tc, dict):
                continue
            func = tc.get("function", {})
            if not func:
                continue

            raw_args = func.get("arguments", {})
            if isinstance(raw_args, str):
                try:
                    parsed_args = json.loads(raw_args)
                except json.JSONDecodeError:
                    logger.warning("Qwen 工具 %s 参数 JSON 解析失败，尝试修复", func.get("name", "?"))
                    try:
                        from json_repair import repair_json
                        repaired = repair_json(raw_args)
                        parsed_args = json.loads(repaired)
                    except Exception:
                        parsed_args = {}
            else:
                parsed_args = raw_args

            results.append({
                "name": func.get("name", ""),
                "arguments": parsed_args,
                "id": tc.get("id", ""),
            })

        return results
