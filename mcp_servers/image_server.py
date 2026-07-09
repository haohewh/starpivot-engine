#!/usr/bin/env python3
"""MCP Server: image_server — 图片生成与处理工具

独立的 MCP Server 进程，通过 stdio 传输层与星枢引擎通信。
提供图片生成、OCR 识别和海报合成功能。

启动方式:
    python -m mcp_servers.image_server

复用 core/tools.py 中的函数。
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("image_server")

# ──────────────────────────────────────────────
# MCP SDK 导入
# ──────────────────────────────────────────────
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import (
        Tool,
        TextContent,
        CallToolResult,
        ListToolsResult,
    )
except ImportError:
    print(
        "缺少 mcp Python 库，请运行: pip install mcp",
        file=sys.stderr,
    )
    sys.exit(1)


# ══════════════════════════════════════════════════
# 工具调用辅助
# ══════════════════════════════════════════════════

def _call_tool(func, args: dict) -> dict:
    """调用 tools.py 中的函数并返回标准结果字典。

    Args:
        func: tools.py 中的工具函数。
        args: 工具参数字典。

    Returns:
        dict: 标准工具结果字典。
    """
    from core.tools import ToolResult

    try:
        result = func(**args)
        if isinstance(result, dict):
            return result
        if isinstance(result, ToolResult):
            return result.to_dict()
        return {"success": True, "output": str(result), "error": None}
    except TypeError as e:
        return {"success": False, "output": "", "error": f"参数错误: {e}"}
    except Exception as e:
        return {"success": False, "output": "", "error": f"执行异常: {e}"}


# ══════════════════════════════════════════════════
# MCP Server 定义
# ══════════════════════════════════════════════════

app = Server("image_server")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """声明此服务器提供的工具列表。"""
    return [
        Tool(
            name="generate_image_freeapi",
            description="通过 MiniMax API 生成图片。无需 GPU，需要配置 MINIMAX_API_KEY。",
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "图片描述文本",
                    },
                    "size": {
                        "type": "string",
                        "description": "图片尺寸（默认 1024x1024）",
                        "default": "1024x1024",
                    },
                },
                "required": ["prompt"],
            },
        ),
        Tool(
            name="ocr_image",
            description="使用 RapidOCR 识别图片中的文字。"
                        "基于 ONNX Runtime，无需 GPU，支持中英文混合识别。",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "图片文件路径（支持 JPG/PNG/BMP/TIFF）",
                    },
                },
                "required": ["filepath"],
            },
        ),
        Tool(
            name="compose_poster",
            description="从文案和图片生成完整海报（HTML 格式）。"
                        "生成包含内嵌 CSS 样式的完整 HTML 海报文件。"
                        "如果有 Playwright 可用，可以截图输出为 PNG。",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "海报标题",
                    },
                    "subtitle": {
                        "type": "string",
                        "description": "副标题（可选）",
                        "default": "",
                    },
                    "body": {
                        "type": "string",
                        "description": "正文内容（可选，支持 HTML 标签）",
                        "default": "",
                    },
                    "image_path": {
                        "type": "string",
                        "description": "图片路径（可选，用于海报中的插图）",
                        "default": "",
                    },
                    "style": {
                        "type": "string",
                        "description": "视觉风格：modern/tech/elegant/colorful/vintage",
                        "default": "modern",
                    },
                },
                "required": ["title"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(
    name: str,
    arguments: dict,
) -> list[TextContent]:
    """处理工具调用请求。

    Args:
        name: 工具名称。
        arguments: 工具参数字典。

    Returns:
        TextContent 列表。

    Raises:
        ValueError: 未知工具名。
    """
    from core.tools import generate_image_freeapi, ocr_image, compose_poster

    TOOL_MAP = {
        "generate_image_freeapi": generate_image_freeapi,
        "ocr_image": ocr_image,
        "compose_poster": compose_poster,
    }

    func = TOOL_MAP.get(name)
    if func is None:
        raise ValueError(
            f"未知工具: {name}，此服务器仅提供 "
            f"generate_image_freeapi/ocr_image/compose_poster 工具"
        )

    logger.info("执行工具: %s args=%s", name, {k: v for k, v in arguments.items() if k != "image_path"})
    result = _call_tool(func, arguments)

    return [TextContent(
        type="text",
        text=json.dumps(result, ensure_ascii=False),
    )]


# ══════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════

async def main() -> None:
    """启动 MCP Server（stdio 传输层）。"""
    logger.info("image_server 启动中...")

    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )

    logger.info("image_server 已关闭")


def _run_main() -> None:
    """同步入口（供 __main__ 块调用）。"""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("image_server 收到中断信号，退出")
    except Exception as e:
        logger.error("image_server 异常退出: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    _run_main()
