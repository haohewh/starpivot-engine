#!/usr/bin/env python3
"""MCP Server: media_server — 视频下载与处理工具

独立的 MCP Server 进程，通过 stdio 传输层与星枢引擎通信。
提供视频下载和视频转文字能力。

启动方式:
    python -m mcp_servers.media_server

download_video 复用 core/tools.py 中的函数。
video_to_text 内嵌实现（下载音频 + 语音识别）。
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
logger = logging.getLogger("media_server")

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
    """调用 core/tools.py 中的函数。"""
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


def _generate_video(
    prompt: str,
    duration: int = 10,
    resolution: str = "720p",
    model: str = "minimax",
) -> dict:
    """AI 视频生成（占位实现）。

    调用外部 AI 视频生成 API（如 MiniMax 视频生成），当前为模拟占位。
    后续接入真实 API 后替换底层实现。

    Args:
        prompt: 视频内容描述提示词。
        duration: 视频时长（秒，默认 10）。
        resolution: 分辨率（720p / 1080p，默认 720p）。
        model: 视频生成模型（minimax / runway / pika，默认 minimax）。

    Returns:
        dict: 生成结果，包含视频 URL 或本地路径。
    """
    logger.info("视频生成: prompt=%s duration=%ds resolution=%s model=%s",
                prompt[:80], duration, resolution, model)

    # 占位：返回模拟数据
    return {
        "success": True,
        "output": json.dumps({
            "prompt": prompt,
            "duration": duration,
            "resolution": resolution,
            "model": model,
            "video_url": f"https://mock.video-gen.com/output/{hash(prompt)}.mp4",
            "status": "generated",
            "note": "此为占位实现。后续接入 MiniMax 视频生成 API 后返回真实视频 URL。",
        }, ensure_ascii=False),
        "error": None,
    }


def _video_to_text(video_path: str, language: str = "zh") -> dict:
    """视频转文字：提取视频中的音频并转写为文字。
    
    工作流程：
    1. 使用 ffmpeg 从视频中提取音频（WAV格式）
    2. 使用 faster-whisper（或备用方案）转写音频为文字
    
    Args:
        video_path: 视频文件路径（本地文件系统路径）。
        language: 语言代码（默认 "zh" 中文）。
    
    Returns:
        dict: 识别结果，包含文本、语言、时长等信息。
    """
    if not os.path.exists(video_path):
        return {"success": False, "output": "", "error": f"视频文件不存在: {video_path}"}

    # ── 第一步：提取音频 ──
    import subprocess
    audio_path = None
    try:
        fd, audio_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)

        cmd = [
            "ffmpeg", "-i", video_path,
            "-vn",                    # 不处理视频
            "-acodec", "pcm_s16le",   # WAV 音频格式
            "-ar", "16000",           # 16kHz 采样率（whisper 推荐）
            "-ac", "1",               # 单声道
            "-y",                     # 覆盖输出
            audio_path,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            return {
                "success": False, "output": "",
                "error": f"ffmpeg 音频提取失败: {proc.stderr[:500]}",
            }

        if not os.path.exists(audio_path):
            return {"success": False, "output": "", "error": "音频提取失败：输出文件未生成"}

        audio_size = os.path.getsize(audio_path)
        logger.info("音频提取成功: %s (%d bytes)", audio_path, audio_size)

    except FileNotFoundError:
        return {"success": False, "output": "", "error": "缺少 ffmpeg，请安装: sudo apt install ffmpeg"}
    except subprocess.TimeoutExpired:
        return {"success": False, "output": "", "error": "ffmpeg 音频提取超时（超过120秒）"}
    except Exception as e:
        return {"success": False, "output": "", "error": f"音频提取异常: {e}"}

    # ── 第二步：语音识别 ──
    try:
        # 优先 faster-whisper
        try:
            from faster_whisper import WhisperModel
            model = WhisperModel("base", device="cpu", compute_type="int8")
            segments, info = model.transcribe(audio_path, language=language, beam_size=5)
            texts = []
            segment_details = []
            for seg in segments:
                texts.append(seg.text)
                segment_details.append({
                    "start": round(seg.start, 2),
                    "end": round(seg.end, 2),
                    "text": seg.text,
                })
            full_text = "".join(texts)
            result = {
                "success": True,
                "output": json.dumps({
                    "text": full_text,
                    "language": info.language if info else language,
                    "duration_seconds": info.duration if info else None,
                    "segments": segment_details,
                }, ensure_ascii=False),
                "error": None,
            }
        except ImportError:
            # 回退 openai-whisper
            import whisper
            model = whisper.load_model("base")
            transcribe_result = model.transcribe(audio_path, language=language)
            full_text = transcribe_result.get("text", "").strip()
            result = {
                "success": True,
                "output": json.dumps({
                    "text": full_text,
                    "language": transcribe_result.get("language", language),
                    "duration_seconds": transcribe_result.get("duration", None),
                    "segments": [],
                }, ensure_ascii=False),
                "error": None,
            }

        # 清理临时音频文件
        try:
            os.unlink(audio_path)
        except Exception:
            pass

        return result

    except ImportError:
        # 两个 whisper 都没有
        return {
            "success": False, "output": "",
            "error": "缺少语音识别库，请安装: pip install faster-whisper (推荐) 或 openai-whisper\n"
                     f"音频已临时保存在: {audio_path}",
        }
    except Exception as e:
        return {
            "success": False, "output": "",
            "error": f"语音识别失败: {e}\n音频临时保存在: {audio_path}",
        }


# ══════════════════════════════════════════════════
# MCP Server 定义
# ══════════════════════════════════════════════════

app = Server("media_server")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """声明此服务器提供的工具列表。"""
    return [
        Tool(
            name="download_video",
            description="下载视频/音频：使用 yt-dlp 从 YouTube、Bilibili 等数百个网站下载视频。"
                        "下载文件保存在临时目录，返回本地路径。",
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "视频页面 URL（如 YouTube、Bilibili、抖音等）",
                    },
                },
                "required": ["url"],
            },
        ),
        Tool(
            name="video_to_text",
            description="视频转文字：从视频文件中提取音频并转写为文字。"
                        "使用 ffmpeg 提取音频 + whisper 语音识别。"
                        "支持 MP4/MKV/AVI/MOV/FLV 等常见视频格式。"
                        "返回带时间戳的文字分段。",
            inputSchema={
                "type": "object",
                "properties": {
                    "video_path": {
                        "type": "string",
                        "description": "视频文件路径（本地文件系统路径）",
                    },
                    "language": {
                        "type": "string",
                        "description": "语言代码（zh=中文, en=英文, ja=日文, 默认 zh）",
                        "default": "zh",
                    },
                },
                "required": ["video_path"],
            },
        ),
        Tool(
            name="generate_video",
            description="AI 视频生成：根据文字描述自动生成视频（占位实现）。"
                        "支持指定时长、分辨率和模型。"
                        "当前为模拟占位，后续接入 MiniMax 等 AI 视频生成 API。",
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "视频内容描述提示词",
                    },
                    "duration": {
                        "type": "integer",
                        "description": "视频时长（秒，默认 10）",
                        "default": 10,
                    },
                    "resolution": {
                        "type": "string",
                        "description": "分辨率（720p / 1080p，默认 720p）",
                        "default": "720p",
                    },
                    "model": {
                        "type": "string",
                        "description": "视频生成模型（minimax / runway / pika，默认 minimax）",
                        "default": "minimax",
                    },
                },
                "required": ["prompt"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(
    name: str,
    arguments: dict,
) -> list[TextContent]:
    """处理工具调用请求。"""
    if name not in ("download_video", "video_to_text", "generate_video"):
        raise ValueError(f"未知工具: {name}，此服务器仅提供 download_video/video_to_text/generate_video 工具")

    if name == "download_video":
        url = arguments.get("url", "")
        if not url or not url.strip():
            return [TextContent(type="text", text=json.dumps(
                {"success": False, "output": "", "error": "'url' 参数不能为空"}
            ))]
        logger.info("下载视频: url=%s", url[:80])
        result = _call_tools_func("download_video", {"url": url})

    elif name == "video_to_text":
        video_path = arguments.get("video_path", "")
        if not video_path:
            return [TextContent(type="text", text=json.dumps(
                {"success": False, "output": "", "error": "'video_path' 参数不能为空"}
            ))]
        language = arguments.get("language", "zh")
        logger.info("视频转文字: video=%s lang=%s", video_path, language)
        result = _video_to_text(video_path, language)

    elif name == "generate_video":
        prompt = arguments.get("prompt", "")
        if not prompt:
            return [TextContent(type="text", text=json.dumps(
                {"success": False, "output": "", "error": "'prompt' 参数不能为空"}
            ))]
        duration = arguments.get("duration", 10)
        resolution = arguments.get("resolution", "720p")
        model = arguments.get("model", "minimax")
        logger.info("视频生成: prompt=%s duration=%d", prompt[:80], duration)
        result = _generate_video(prompt, duration, resolution, model)

    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]


# ══════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════

async def main() -> None:
    """启动 MCP Server（stdio 传输层）。"""
    logger.info("media_server 启动中...")

    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )

    logger.info("media_server 已关闭")


def _run_main() -> None:
    """同步入口（供 __main__ 块调用）。"""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("media_server 收到中断信号，退出")
    except Exception as e:
        logger.error("media_server 异常退出: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    _run_main()
