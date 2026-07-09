#!/usr/bin/env python3
"""MCP Server: audio_server — 语音合成与识别工具

独立的 MCP Server 进程，通过 stdio 传输层与星枢引擎通信。
提供语音合成（TTS）和语音识别（STT）能力。

启动方式:
    python -m mcp_servers.audio_server

agent_speak 复用 core/tools.py 中的函数。
speech_recognition 内嵌实现（支持本地文件或 URL）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("audio_server")

# ──────────────────────────────────────────────
# MCP SDK 导入
# ──────────────────────────────────────────────
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import (
        Tool,
        TextContent,
    )
except ImportError:
    print(
        "缺少 mcp Python 库，请运行: pip install mcp",
        file=sys.stderr,
    )
    sys.exit(1)


# ══════════════════════════════════════════════════
# 工具实现
# ══════════════════════════════════════════════════

def _call_tools_func(func_name: str, args: dict) -> dict:
    """调用 core/tools.py 中的函数。
    
    Args:
        func_name: tools.py 中的函数名。
        args: 函数参数字典。
    
    Returns:
        dict: 标准工具结果。
    """
    import core.tools as tools
    try:
        func = getattr(tools, func_name)
        result = func(**args)
        if hasattr(result, 'to_dict'):
            return result.to_dict()
        if isinstance(result, dict):
            return result
        return {"success": True, "output": str(result), "error": None}
    except Exception as e:
        return {"success": False, "output": "", "error": f"{func_name} 执行异常: {e}"}


def _speech_recognition(audio_path: str, language: str = "zh") -> dict:
    """语音识别：将音频文件转写为文字。
    
    使用 whisper（faster-whisper 或 openai-whisper）实现本地语音识别。
    支持常见音频格式：MP3、WAV、M4A、FLAC、OGG 等。
    如果本地没有 whisper 模型，则回退提示用户安装。
    
    Args:
        audio_path: 音频文件路径（本地路径）。
        language: 语言代码（默认 "zh" 中文，"en" 英文，"ja" 日文等）。
    
    Returns:
        dict: 识别结果。
    """
    if not os.path.exists(audio_path):
        return {"success": False, "output": "", "error": f"音频文件不存在: {audio_path}"}

    # 方式 1：尝试 faster-whisper（更快、内存更省）
    try:
        from faster_whisper import WhisperModel
        model_size = "base"  # small/medium/large-v3 可选
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments, info = model.transcribe(audio_path, language=language, beam_size=5)
        texts = []
        for seg in segments:
            texts.append(seg.text)
        full_text = "".join(texts)
        detected_lang = info.language if info else language
        return {
            "success": True,
            "output": json.dumps({
                "text": full_text,
                "language": detected_lang,
                "duration_seconds": info.duration if info else None,
            }, ensure_ascii=False),
            "error": None,
        }
    except ImportError:
        pass
    except Exception as e:
        return {"success": False, "output": "", "error": f"faster-whisper 识别失败: {e}"}

    # 方式 2：尝试 openai-whisper
    try:
        import whisper
        model = whisper.load_model("base")
        result = model.transcribe(audio_path, language=language)
        return {
            "success": True,
            "output": json.dumps({
                "text": result.get("text", "").strip(),
                "language": result.get("language", language),
                "duration_seconds": result.get("duration", None),
            }, ensure_ascii=False),
            "error": None,
        }
    except ImportError:
        pass
    except Exception as e:
        return {"success": False, "output": "", "error": f"whisper 识别失败: {e}"}

    # 方式 3：尝试 speech_recognition 库（Google STT 免费版）
    try:
        import speech_recognition as sr
        recognizer = sr.Recognizer()
        with sr.AudioFile(audio_path) as source:
            audio_data = recognizer.record(source)
        text = recognizer.recognize_google(audio_data, language=f"{language}-{language.upper()}")
        return {
            "success": True,
            "output": json.dumps({"text": text, "language": language, "source": "google_stt"}, ensure_ascii=False),
            "error": None,
        }
    except ImportError:
        pass
    except sr.UnknownValueError:
        return {"success": False, "output": "", "error": "语音识别无法理解该音频内容"}
    except sr.RequestError as e:
        return {"success": False, "output": "", "error": f"语音识别服务请求失败: {e}"}
    except Exception as e:
        return {"success": False, "output": "", "error": f"语音识别失败: {e}"}

    return {
        "success": False,
        "output": "",
        "error": "缺少语音识别库，请安装: pip install faster-whisper (推荐) 或 openai-whisper 或 SpeechRecognition",
    }


# ══════════════════════════════════════════════════
# MCP Server 定义
# ══════════════════════════════════════════════════

app = Server("audio_server")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """声明此服务器提供的工具列表。"""
    return [
        Tool(
            name="agent_speak",
            description="语音合成（TTS）：将文字转为语音 MP3 文件。"
                        "使用 Edge TTS 引擎，免费且无需 GPU。"
                        "支持多种中文声音（女声/男声）。",
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "要转为语音的文字内容",
                    },
                    "voice": {
                        "type": "string",
                        "description": "声音名称。可选: zh-CN-XiaoxiaoNeural(女声,默认), "
                                       "zh-CN-XiaoyiNeural(女声), zh-CN-YunjianNeural(男声), "
                                       "zh-CN-YunxiNeural(男声), zh-CN-YunxiaNeural(女声), "
                                       "zh-CN-YunyangNeural(男声)",
                        "default": "zh-CN-XiaoxiaoNeural",
                    },
                },
                "required": ["text"],
            },
        ),
        Tool(
            name="speech_recognition",
            description="语音识别（STT）：将音频文件转写为文字。"
                        "支持 MP3/WAV/M4A/FLAC/OGG 等格式。"
                        "自动检测并优先使用 faster-whisper → openai-whisper → Google STT。",
            inputSchema={
                "type": "object",
                "properties": {
                    "audio_path": {
                        "type": "string",
                        "description": "音频文件路径（本地文件系统路径）",
                    },
                    "language": {
                        "type": "string",
                        "description": "语言代码（zh=中文, en=英文, ja=日文, ko=韩文 等，默认 zh）",
                        "default": "zh",
                    },
                },
                "required": ["audio_path"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(
    name: str,
    arguments: dict,
) -> list[TextContent]:
    """处理工具调用请求。"""
    if name not in ("agent_speak", "speech_recognition"):
        raise ValueError(f"未知工具: {name}，此服务器仅提供 agent_speak/speech_recognition 工具")

    if name == "agent_speak":
        text = arguments.get("text", "")
        if not text or not text.strip():
            return [TextContent(type="text", text=json.dumps(
                {"success": False, "output": "", "error": "'text' 参数不能为空"}
            ))]
        voice = arguments.get("voice", "zh-CN-XiaoxiaoNeural")
        logger.info("语音合成: text=%s voice=%s", text[:50], voice)
        result = _call_tools_func("agent_speak", {"text": text, "voice": voice})

    elif name == "speech_recognition":
        audio_path = arguments.get("audio_path", "")
        if not audio_path:
            return [TextContent(type="text", text=json.dumps(
                {"success": False, "output": "", "error": "'audio_path' 参数不能为空"}
            ))]
        language = arguments.get("language", "zh")
        logger.info("语音识别: audio=%s lang=%s", audio_path, language)
        result = _speech_recognition(audio_path, language)

    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]


# ══════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════

async def main() -> None:
    """启动 MCP Server（stdio 传输层）。"""
    logger.info("audio_server 启动中...")

    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )

    logger.info("audio_server 已关闭")


def _run_main() -> None:
    """同步入口（供 __main__ 块调用）。"""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("audio_server 收到中断信号，退出")
    except Exception as e:
        logger.error("audio_server 异常退出: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    _run_main()
