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



# === image tools ===


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

