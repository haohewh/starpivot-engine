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



# === media tools ===


def agent_speak(text: str, voice: str = "zh-CN-XiaoxiaoNeural", **kwargs) -> ToolResult:
    """使用 Edge TTS 将文字转为语音（免费，CPU运行，无需GPU）。

    支持 8 个中文声音：
    - zh-CN-XiaoxiaoNeural (默认，女声)
    - zh-CN-XiaoyiNeural (女声)
    - zh-CN-YunjianNeural (男声)
    - zh-CN-YunxiNeural (男声)
    - zh-CN-YunxiaNeural (女声)
    - zh-CN-YunyangNeural (男声)

    Args:
        text: 要转为语音的文字
        voice: 声音名称（默认 Xiaoxiao）

    Returns:
        ToolResult: output 为音频文件路径
    """
    import asyncio, os, tempfile
    try:
        import edge_tts
        fd, path = tempfile.mkstemp(suffix='.mp3')
        os.close(fd)
        async def do_tts():
            tts = edge_tts.Communicate(text, voice=voice)
            await tts.save(path)
        asyncio.run(do_tts())
        size = os.path.getsize(path)
        return ToolResult(success=True, output=f"语音已生成: {path} ({size} bytes)")
    except Exception as e:
        return ToolResult(success=False, output="", error=f"TTS 失败: {e}")



def download_video(url: str, **kwargs) -> ToolResult:
    """使用 yt-dlp 下载视频/音频。

    支持 YouTube、Bilibili 等数百个网站。
    下载文件保存在临时目录，返回本地路径。

    Args:
        url: 视频页面 URL。

    Returns:
        ToolResult: success=True 时 output 为下载后的文件路径。
    """
    import tempfile, os
    try:
        import yt_dlp

        tmpdir = tempfile.mkdtemp(prefix="starpivot_dl_")
        ydl_opts = {
            "outtmpl": os.path.join(tmpdir, "%(title)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            # 处理可能的 ext 修正
            if not os.path.exists(filename):
                files = os.listdir(tmpdir)
                if files:
                    filename = os.path.join(tmpdir, files[0])
                else:
                    raise FileNotFoundError(f"下载完成但未找到文件: {tmpdir}")

        size = os.path.getsize(filename)
        title = info.get("title", url)
        return ToolResult(
            success=True,
            output=f"视频已下载: {filename}\n标题: {title}\n大小: {size} bytes\n时长: {info.get('duration', 'N/A')}秒",
        )
    except ImportError:
        return ToolResult(
            success=False, output="",
            error="缺少 yt-dlp，请运行: pip install yt-dlp",
        )
    except Exception as e:
        return ToolResult(success=False, output="", error=f"视频下载失败: {e}")



def convert_document(filepath: str, **kwargs) -> ToolResult:
    """使用 Markitdown 将文档转换为纯文本。

    支持格式：PDF、DOCX、PPTX、XLSX、HTML、Markdown、CSV、JSON、XML、图片（OCR）等。

    Args:
        filepath: 文档文件路径。

    Returns:
        ToolResult: success=True 时 output 为文档提取出的文本内容。
    """
    try:
        from markitdown import MarkItDown
        md = MarkItDown()
        result = md.convert(filepath)
        content = result.text_content
        # 截断到 10000 字符避免 token 浪费
        truncated = content[:10000]
        if len(content) > 10000:
            truncated += "\n\n...（内容已截断，完整内容较长）"
        return ToolResult(success=True, output=truncated)
    except ImportError:
        return ToolResult(
            success=False, output="",
            error="缺少 markitdown，请运行: pip install markitdown",
        )
    except FileNotFoundError:
        return ToolResult(success=False, output="", error=f"文件不存在: {filepath}")
    except Exception as e:
        return ToolResult(success=False, output="", error=f"文档转换失败: {e}")



def ocr_image(filepath: str, **kwargs) -> ToolResult:
    """使用 RapidOCR 识别图片中的文字。

    基于 ONNX Runtime，无需 GPU，无需 PyTorch。
    支持中英文混合识别，速度快，精度高。
    支持常见图片格式：JPG、PNG、BMP、TIFF。

    Args:
        filepath: 图片文件路径。

    Returns:
        ToolResult: success=True 时 output 为识别到的文字内容。
    """
    try:
        from rapidocr_onnxruntime import RapidOCR
        engine = RapidOCR()
        result, elapse = engine(filepath)
        if not result:
            return ToolResult(success=True, output="未能识别到文字（可能图片中无文字或质量过低）")
        lines = []
        for box, text, conf in result:
            if conf and conf > 0.3:
                lines.append(text)
        output = "\n".join(lines)
        return ToolResult(success=True, output=output[:5000])
    except ImportError:
        return ToolResult(success=False, output="",
                          error="缺少 rapidocr，请运行: pip install rapidocr-onnxruntime")
    except FileNotFoundError:
        return ToolResult(success=False, output="",
                          error=f"图片文件不存在: {filepath}")
    except Exception as e:
        return ToolResult(success=False, output="", error=f"OCR 识别失败: {e}")

