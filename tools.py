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


def web_search(query: str, **kwargs) -> ToolResult:
    """用 Firecrawl API 执行网络搜索。

    优先从环境变量 FIRECRAWL_API_KEY 读取 API key，
    若未设置则返回提示信息。

    Args:
        query: 搜索关键词。

    Returns:
        ToolResult: success=True 时 output 为搜索结果文本。
    """
    api_key = os.environ.get("FIRECRAWL_API_KEY")
    if not api_key:
        return ToolResult(
            success=False,
            output="",
            error="FIRECRAWL_API_KEY 环境变量未设置，无法执行 web_search。"
                   "请先设置 ~/.hermes/.env 中的 FIRECRAWL_API_KEY 并加载环境变量。",
        )

    try:
        import requests
        resp = requests.post(
            "https://api.firecrawl.dev/v1/search",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"query": query, "pageSize": 5},
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("data", [])
            lines: list[str] = []
            for i, item in enumerate(results, 1):
                title = item.get("title", "无标题")
                url = item.get("url", "")
                snippet = item.get("description", item.get("snippet", ""))
                lines.append(f"{i}. {title}")
                if url:
                    lines.append(f"   链接: {url}")
                if snippet:
                    lines.append(f"   摘要: {snippet}")
                lines.append("")
            output = "\n".join(lines) if lines else "未找到相关结果。"
            return ToolResult(success=True, output=output)
        else:
            return ToolResult(
                success=False,
                output="",
                error=f"Firecrawl API 请求失败 (HTTP {resp.status_code}): {resp.text[:300]}",
            )
    except ImportError:
        return ToolResult(
            success=False,
            output="",
            error="缺少 requests 库，请运行: pip install requests",
        )
    except Exception as e:
        return ToolResult(success=False, output="", error=f"web_search 出错: {e}")


# ── 安全计算 ────────────────────────────────

# 允许的运算符节点白名单
_ALLOWED_OPS: tuple[type[ast.AST], ...] = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Constant,
    ast.Name,       # 允许变量名（如 pi, e），但只允许部分已知常量
)

_ALLOWED_BINOPS: dict[type[ast.operator], Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_ALLOWED_UNOPS: dict[type[ast.unaryop], Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

# 允许的数学常量
_SAFE_CONSTANTS: dict[str, float] = {
    "pi": 3.141592653589793,
    "e": 2.718281828459045,
}


def calculate(expression: str, **kwargs) -> ToolResult:
    """安全计算数学表达式。

    只允许数字、四则运算、幂、取模、括号和科学计数法，
    以及常量 pi 和 e。禁止 __import__、函数调用、属性访问等危险操作。

    Args:
        expression: 数学表达式字符串，如 "1+2*3" 或 "pi * 2**2"。

    Returns:
        ToolResult: success=True 时 output 为计算结果（字符串）。
    """
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as e:
        return ToolResult(success=False, output="", error=f"表达式语法错误: {e}")
    except Exception as e:
        return ToolResult(success=False, output="", error=f"表达式解析失败: {e}")

    # 递归校验 AST 节点安全性
    def _check(node: ast.AST, depth: int = 0) -> None:
        if depth > 20:
            raise ValueError("表达式嵌套过深")
        if isinstance(node, ast.Expression):
            _check(node.body, depth + 1)
        elif isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float)):
                raise ValueError(f"不支持的常量类型: {type(node.value).__name__}")
        elif isinstance(node, ast.BinOp):
            if type(node.op) not in _ALLOWED_BINOPS:
                raise ValueError(f"不支持的二元运算符: {type(node.op).__name__}")
            _check(node.left, depth + 1)
            _check(node.right, depth + 1)
        elif isinstance(node, ast.UnaryOp):
            if type(node.op) not in _ALLOWED_UNOPS:
                raise ValueError(f"不支持的一元运算符: {type(node.op).__name__}")
            _check(node.operand, depth + 1)
        elif isinstance(node, ast.Name):
            if node.id not in _SAFE_CONSTANTS:
                raise ValueError(f"不允许的变量/函数: {node.id}")
        else:
            raise ValueError(f"不支持的表达式节点: {type(node).__name__}")

    try:
        _check(tree)
    except ValueError as e:
        return ToolResult(success=False, output="", error=str(e))

    # 安全求值
    def _eval(node: ast.AST) -> float:
        if isinstance(node, ast.Constant):
            return float(node.value)
        elif isinstance(node, ast.BinOp):
            left = _eval(node.left)
            right = _eval(node.right)
            return _ALLOWED_BINOPS[type(node.op)](left, right)
        elif isinstance(node, ast.UnaryOp):
            operand = _eval(node.operand)
            return _ALLOWED_UNOPS[type(node.op)](operand)
        elif isinstance(node, ast.Name):
            return _SAFE_CONSTANTS[node.id]
        else:
            raise ValueError(f"无法求值的节点: {type(node).__name__}")

    try:
        result = _eval(tree.body)
        # 如果是整数则显示为整数
        if result == int(result):
            return ToolResult(success=True, output=str(int(result)))
        return ToolResult(success=True, output=str(result))
    except Exception as e:
        return ToolResult(success=False, output="", error=f"计算失败: {e}")


def echo(text: str, **kwargs) -> ToolResult:
    """直接返回输入的文本。

    Args:
        text: 任意文本内容。

    Returns:
        ToolResult: success=True，output 为原文本。
    """
    return ToolResult(success=True, output=text)


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


# ──────────────────────────────────────────────
# 新集成工具：yt-dlp / markitdown / PaddleOCR
# ──────────────────────────────────────────────


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

# ──────────────────────────────────────────────
# 图片生成工具（无需GPU）
# ──────────────────────────────────────────────

def generate_image(description: str, style: str = "modern", width: int = 800, height: int = 600, **kwargs) -> ToolResult:
    """生成 SVG 图片（无需 GPU，无需外部API）。

    通过调用 LLM 生成 SVG 代码，保存到文件系统。
    支持多种风格：modern, minimal, colorful, sketch, vintage。

    Args:
        description: 图片内容描述（如"一座星空下的山峰"）。
        style: 视觉风格（modern/minimal/colorful/sketch/vintage）。
        width: SVG 画布宽度（默认 800）。
        height: SVG 画布高度（默认 600）。

    Returns:
        ToolResult: success=True 时 output 为 SVG 文件路径。
    """
    import os, json, tempfile, time, hashlib

    # 确保输出目录存在
    output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
    os.makedirs(output_dir, exist_ok=True)

    # 尝试用 LLM 生成 SVG
    try:
        from openai import OpenAI
        from config import settings

        client = OpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
        )

        # 构造 prompt：要求 LLM 生成纯 SVG 代码
        prompt = (
            f"你是一个 SVG 设计师。请根据以下描述生成一张 SVG 图片。\n\n"
            f"描述：{description}\n"
            f"风格：{style}\n"
            f"尺寸：{width}x{height}\n\n"
            f"要求：\n"
            f"1. 只输出纯 SVG 代码，不要用 markdown 包裹，不要加解释\n"
            f"2. SVG 代码必须包含 xmlns 声明，且 width=\"{width}\" height=\"{height}\"\n"
            f"3. 使用有意义的渐变、颜色和形状来表现描述内容\n"
            f"4. 不要在 SVG 中使用外部图片或字体引用\n"
            f"5. 可以只用矢量形状、路径、渐变构建丰富的视觉效果\n"
            f"6. 确保 SVG 合法且可以独立渲染"
        )

        resp = client.chat.completions.create(
            model=settings.default_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=4000,
        )

        svg_code = resp.choices[0].message.content.strip()

        # 清理：去掉可能的 markdown 包裹
        if svg_code.startswith("```svg"):
            svg_code = svg_code[6:]
        elif svg_code.startswith("```"):
            svg_code = svg_code[3:]
        if svg_code.endswith("```"):
            svg_code = svg_code[:-3]
        svg_code = svg_code.strip()

        # 验证是合法的 SVG
        if not svg_code.startswith("<svg") and not svg_code.startswith("<?xml"):
            # 尝试找 SVG 标签
            idx = svg_code.find("<svg")
            if idx >= 0:
                svg_code = svg_code[idx:]
            else:
                # 兜底：生成一个简单 SVG
                svg_code = _generate_fallback_svg(description, style, width, height)

    except Exception as e:
        # LLM 不可用时回退到内置生成
        svg_code = _generate_fallback_svg(description, style, width, height)

    # 生成文件名
    safe_name = hashlib.md5(description.encode()).hexdigest()[:12]
    timestamp = int(time.time())
    filename = f"img_{safe_name}_{timestamp}.svg"
    filepath = os.path.join(output_dir, filename)

    # 写入文件
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(svg_code)
        size = len(svg_code)
        return ToolResult(success=True, output=f"SVG 图片已生成: {filepath}\n大小: {size} 字符\n描述: {description}\n风格: {style}\n尺寸: {width}x{height}")
    except Exception as e:
        return ToolResult(success=False, output="", error=f"保存 SVG 图片失败: {e}")


def _generate_fallback_svg(description: str, style: str, width: int, height: int) -> str:
    """当 LLM 不可用时，生成一个简单的占位 SVG。"""
    # 根据风格选择颜色主题
    if style == "vintage":
        bg = "#f5e6c8"
        fg1 = "#8B4513"
        fg2 = "#D2691E"
    elif style == "colorful":
        bg = "#1a1a2e"
        fg1 = "#e94560"
        fg2 = "#0f3460"
    elif style == "minimal":
        bg = "#f8f9fa"
        fg1 = "#343a40"
        fg2 = "#6c757d"
    elif style == "sketch":
        bg = "#ffffff"
        fg1 = "#2d3436"
        fg2 = "#636e72"
    else:  # modern
        bg = "#0a0a23"
        fg1 = "#00d2ff"
        fg2 = "#3a7bd5"

    title = description[:50] if len(description) > 50 else description
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">
  <defs>
    <linearGradient id="bgGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:{bg};stop-opacity:1" />
      <stop offset="100%" style="stop-color:{fg2};stop-opacity:0.3" />
    </linearGradient>
    <linearGradient id="accentGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:{fg1};stop-opacity:0.8" />
      <stop offset="100%" style="stop-color:{fg2};stop-opacity:0.6" />
    </linearGradient>
  </defs>
  <!-- 背景 -->
  <rect width="{width}" height="{height}" fill="url(#bgGrad)" rx="8"/>
  <!-- 装饰圆 -->
  <circle cx="{width*0.2}" cy="{height*0.3}" r="{min(width,height)*0.15}" fill="url(#accentGrad)" opacity="0.4"/>
  <circle cx="{width*0.8}" cy="{height*0.7}" r="{min(width,height)*0.1}" fill="url(#accentGrad)" opacity="0.3"/>
  <circle cx="{width*0.5}" cy="{height*0.5}" r="{min(width,height)*0.08}" fill="{fg1}" opacity="0.5"/>
  <!-- 文字 -->
  <text x="{width/2}" y="{height/2}" text-anchor="middle" dominant-baseline="middle"
        font-family="sans-serif" font-size="{min(width,height)*0.04}" fill="{fg1}"
        opacity="0.9">{title}</text>
  <text x="{width/2}" y="{height*0.6}" text-anchor="middle" dominant-baseline="middle"
        font-family="sans-serif" font-size="{min(width,height)*0.02}" fill="{fg1}"
        opacity="0.6">Style: {style}</text>
</svg>"""


# ──────────────────────────────────────────────
# 海报合成工具（HTML + Playwright 截图）
# ──────────────────────────────────────────────

def compose_poster(title: str, subtitle: str = "", body: str = "", image_path: str = "", style: str = "modern", **kwargs) -> ToolResult:
    """从文案和图片生成完整海报（HTML 格式）。

    生成包含内嵌 CSS 样式的完整 HTML 海报文件。
    如果有 Playwright MCP 服务可用，可以截图输出为 PNG。

    Args:
        title: 海报标题。
        subtitle: 副标题（可选）。
        body: 正文内容（可选，支持 HTML 标签）。
        image_path: 图片路径（可选，用于海报中的插图）。
        style: 视觉风格（modern/tech/elegant/colorful/vintage）。

    Returns:
        ToolResult: success=True 时 output 为 HTML 文件路径。
    """
    import os, time, hashlib

    # 确保输出目录存在
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_dir = os.path.join(base_dir, "output")
    os.makedirs(output_dir, exist_ok=True)

    # 生成 HTML 海报
    html_content = _build_poster_html(title, subtitle, body, image_path, style)

    # 生成文件名
    safe_name = hashlib.md5(title.encode()).hexdigest()[:12]
    timestamp = int(time.time())
    html_filename = f"poster_{safe_name}_{timestamp}.html"
    html_filepath = os.path.join(output_dir, html_filename)

    try:
        with open(html_filepath, "w", encoding="utf-8") as f:
            f.write(html_content)
    except Exception as e:
        return ToolResult(success=False, output="", error=f"保存 HTML 海报失败: {e}")

    # 尝试使用 Playwright 截图
    png_path = None
    try:
        # 尝试通过 Playwright MCP 截图
        from playwright.sync_api import sync_playwright
        png_filename = f"poster_{safe_name}_{timestamp}.png"
        png_filepath = os.path.join(output_dir, png_filename)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1080, "height": 1920})
            page.goto(f"file://{html_filepath}")
            page.wait_for_load_state("networkidle")
            page.screenshot(path=png_filepath, full_page=True)
            browser.close()
        png_path = png_filepath
    except ImportError:
        # Playwright 未安装，只返回 HTML
        pass
    except Exception as e:
        # Playwright 出错也不影响，HTML 已经生成
        pass

    result_parts = [f"HTML 海报已生成: {html_filepath}"]
    if png_path:
        result_parts.append(f"PNG 截图已生成: {png_path}")
    else:
        result_parts.append("（提示：可用浏览器打开 HTML 文件查看效果，或安装 Playwright 后自动截图）")

    return ToolResult(success=True, output="\n".join(result_parts))


def _build_poster_html(title: str, subtitle: str, body: str, image_path: str, style: str) -> str:
    """构建海报 HTML 内容。"""
    # 根据风格选择配色
    if style == "elegant":
        bg = "#faf8f5"
        primary = "#2c1810"
        accent = "#c17817"
        font_family = "'Georgia', 'Noto Serif SC', serif"
        title_size = "48px"
    elif style == "tech":
        bg = "#0a0e27"
        primary = "#e0e6ff"
        accent = "#00d4ff"
        font_family = "'Inter', 'SF Pro', sans-serif"
        title_size = "56px"
    elif style == "colorful":
        bg = "#1a1a2e"
        primary = "#ffffff"
        accent = "#e94560"
        font_family = "'Poppins', 'Noto Sans SC', sans-serif"
        title_size = "52px"
    elif style == "vintage":
        bg = "#f0e6d3"
        primary = "#3d2b1f"
        accent = "#8b4513"
        font_family = "'Playfair Display', 'Noto Serif SC', serif"
        title_size = "50px"
    else:  # modern
        bg = "#ffffff"
        primary = "#1a1a2e"
        accent = "#3a7bd5"
        font_family = "'Inter', 'Noto Sans SC', sans-serif"
        title_size = "54px"

    # 图片 HTML（如果有）
    img_html = ""
    if image_path and os.path.exists(image_path):
        ext = os.path.splitext(image_path)[1].lower()
        if ext in ('.svg',):
            import base64
            with open(image_path, 'r', encoding='utf-8') as f:
                svg_content = f.read()
            b64 = base64.b64encode(svg_content.encode()).decode()
            img_html = f'<div class="poster-image"><img src="data:image/svg+xml;base64,{b64}" alt="海报插图"></div>'
        else:
            import base64
            with open(image_path, 'rb') as f:
                img_data = f.read()
            mime = f"image/{ext[1:]}" if ext[1:] in ('png','jpg','jpeg','gif','webp') else "image/png"
            b64 = base64.b64encode(img_data).decode()
            img_html = f'<div class="poster-image"><img src="data:{mime};base64,{b64}" alt="海报插图"></div>'

    # 正文 HTML
    body_html = f"<p>{body}</p>" if body else ""

    if subtitle:
        subtitle_html = f'<div class="subtitle">{subtitle}</div>'
    else:
        subtitle_html = ""

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} - 海报</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700;900&family=Noto+Sans+SC:wght@300;400;500;700;900&family=Noto+Serif+SC:wght@400;700;900&family=Playfair+Display:wght@400;700;900&family=Georgia&display=swap');

  * {{ margin: 0; padding: 0; box-sizing: border-box; }}

  body {{
    background: {bg};
    color: {primary};
    font-family: {font_family};
    display: flex;
    justify-content: center;
    align-items: center;
    min-height: 100vh;
    padding: 20px;
  }}

  .poster {{
    width: 1080px;
    min-height: 1440px;
    background: {bg};
    position: relative;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    padding: 80px 60px;
    box-shadow: 0 20px 60px rgba(0,0,0,0.1);
  }}

  .poster::before {{
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0; height: 6px;
    background: linear-gradient(90deg, {accent}, transparent);
  }}

  .title {{
    font-size: {title_size};
    font-weight: 900;
    color: {primary};
    text-align: center;
    line-height: 1.2;
    margin-bottom: 20px;
    max-width: 900px;
  }}

  .subtitle {{
    font-size: 28px;
    font-weight: 400;
    color: {accent};
    text-align: center;
    margin-bottom: 40px;
    letter-spacing: 2px;
  }}

  .poster-image {{
    width: 80%;
    max-width: 800px;
    margin: 30px auto;
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 10px 40px rgba(0,0,0,0.1);
  }}

  .poster-image img {{
    width: 100%;
    height: auto;
    display: block;
  }}

  .body {{
    font-size: 22px;
    line-height: 1.8;
    text-align: center;
    max-width: 800px;
    margin-top: 20px;
    opacity: 0.85;
  }}

  .body p {{
    margin-bottom: 16px;
  }}

  .footer {{
    position: absolute;
    bottom: 40px;
    font-size: 14px;
    color: {primary};
    opacity: 0.4;
    letter-spacing: 1px;
  }}
</style>
</head>
<body>
<div class="poster">
  <div class="title">{title}</div>
  {subtitle_html}
  {img_html}
  <div class="body">{body_html}</div>
  <div class="footer">AI Generated Poster</div>
</div>
</body>
</html>"""


# ──────────────────────────────────────────────
# 新集成工具
# ──────────────────────────────────────────────

def agent_reach_web_read(url: str, **kwargs) -> ToolResult:
    """读取任意网页内容，支持超时和兜底。"""
    try:
        content = None
        # 方式1：Agent-Reach WebChannel（threading 超时）
        try:
            from agent_reach.channels.web import WebChannel
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(lambda: WebChannel().read(url))
                content = future.result(timeout=8)
        except Exception:
            pass
        
        # 方式2：兜底 - 直接用 requests 读
        if not content:
            import requests
            from bs4 import BeautifulSoup
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            resp = requests.get(url, timeout=10, headers=headers)
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            content = soup.get_text(separator="\n", strip=True)
        
        truncated = content[:5000]
        if len(content) > 5000:
            truncated += "\n\n...（内容已截断，完整内容较长）"
        return ToolResult(success=True, output=truncated)
    except ImportError:
        return ToolResult(
            success=False, output="",
            error="缺少 agent_reach 模块，请运行: pip install git+https://github.com/Panniantong/Agent-Reach.git",
        )
    except Exception as e:
        return ToolResult(success=False, output="", error=f"Agent-Reach 网页读取失败: {e}")


def agent_reach_search(query: str, **kwargs) -> ToolResult:
    """搜索互联网（通过 Bing 搜索，无需 API Key）。

    直接请求 Bing 搜索引擎，解析 HTML 提取结果标题、链接和摘要。
    在中国境内可正常访问 cn.bing.com，无需 API Key 或额外安装。

    Args:
        query: 搜索关键词。

    Returns:
        ToolResult: success=True 时 output 为搜索结果。
    """
    try:
        from urllib.parse import quote
        import requests
        from bs4 import BeautifulSoup

        url = "https://cn.bing.com/search?q=" + quote(query)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        resp = requests.get(url, headers=headers, timeout=8)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        results = soup.select("li.b_algo")
        lines: list[str] = []

        if not results:
            # 兜底：尝试另一种常见的 Bing 结果选择器
            results = soup.select(".b_algo")

        for i, item in enumerate(results[:10], 1):
            title_el = item.select_one("h2 a")
            snippet_el = item.select_one(".b_caption p")
            if title_el:
                title = title_el.get_text(strip=True)
                link = title_el.get("href", "")
                snippet = snippet_el.get_text(strip=True) if snippet_el else ""
                lines.append(f"{i}. {title}")
                if link:
                    lines.append(f"   链接: {link}")
                if snippet:
                    lines.append(f"   摘要: {snippet[:300]}")
                lines.append("")

        if not lines:
            # 如果还是没结果，退回到原始 HTML 文本提取
            body_text = soup.get_text(separator="\n", strip=True)
            lines.append("未解析到结构化搜索结果，返回页面文本片段：")
            lines.append(body_text[:1500])

        output = "\n".join(lines)
        return ToolResult(success=True, output=output)

    except ImportError as e:
        return ToolResult(
            success=False, output="",
            error=f"缺少依赖库: {e}，请运行: pip install requests beautifulsoup4",
        )
    except Exception as e:
        return ToolResult(success=False, output="", error=f"Bing 搜索失败: {e}")



# ──────────────────────────────────────────────
# 工具注册表
# ──────────────────────────────────────────────

# name -> (func, params_desc)
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


# name -> (func, params_desc)
_TOOL_REGISTRY: dict[str, tuple[Any, list[dict[str, Any]]]] = {
    "read_file": (
        read_file,
        [
            {
                "name": "path",
                "type": "string",
                "description": "要读取的文件路径",
                "required": True,
            },
        ],
    ),
    "write_file": (
        write_file,
        [
            {
                "name": "path",
                "type": "string",
                "description": "要写入的文件路径",
                "required": True,
            },
            {
                "name": "content",
                "type": "string",
                "description": "要写入的文件内容",
                "required": True,
            },
        ],
    ),
    "list_files": (
        list_files,
        [
            {
                "name": "path",
                "type": "string",
                "description": "目录路径（默认当前目录）",
                "required": False,
                "default": ".",
            },
        ],
    ),
    "web_search": (
        web_search,
        [
            {
                "name": "query",
                "type": "string",
                "description": "搜索关键词",
                "required": True,
            },
        ],
    ),
    "calculate": (
        calculate,
        [
            {
                "name": "expression",
                "type": "string",
                "description": "数学表达式（只允许数字、运算符、括号、pi/e）",
                "required": True,
            },
        ],
    ),
    "echo": (
        echo,
        [
            {
                "name": "text",
                "type": "string",
                "description": "要回显的文本",
                "required": True,
            },
        ],
    ),
    "agent_speak": (
        agent_speak,
        [
            {
                "name": "text",
                "type": "string",
                "description": "要转为语音的文字",
                "required": True,
            },
            {
                "name": "voice",
                "type": "string",
                "description": "声音名称，默认 zh-CN-XiaoxiaoNeural（女声），可选 zh-CN-YunxiNeural（男声）等",
                "required": False,
                "default": "zh-CN-XiaoxiaoNeural",
            },
        ],
    ),
    "agent_reach_web_read": (
        agent_reach_web_read,
        [
            {
                "name": "url",
                "type": "string",
                "description": "要读取的网页 URL（如 https://example.com/article）",
                "required": True,
            },
        ],
    ),
    "agent_reach_search": (
        agent_reach_search,
        [
            {
                "name": "query",
                "type": "string",
                "description": "搜索关键词",
                "required": True,
            },
        ],
    ),
    "download_video": (
        download_video,
        [
            {
                "name": "url",
                "type": "string",
                "description": "视频页面 URL（如 YouTube、Bilibili 等）",
                "required": True,
            },
        ],
    ),
    "convert_document": (
        convert_document,
        [
            {
                "name": "filepath",
                "type": "string",
                "description": "文档文件路径（支持 PDF/DOCX/PPTX/XLSX/HTML/MD/CSV 等）",
                "required": True,
            },
        ],
    ),
}


# ──────────────────────────────────────────────
# 统一入口
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
