#!/usr/bin/env python3
"""MCP Server: data_server — 文档转换与数据处理工具

独立的 MCP Server 进程，通过 stdio 传输层与星枢引擎通信。
提供文档格式转换、数据清洗和导出能力。

启动方式:
    python -m mcp_servers.data_server

convert_document 复用 core/tools.py 中的函数。
data_clean / export_csv / export_excel 内嵌实现。
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
import re
import sys
import tempfile
from datetime import datetime
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("data_server")

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


def _data_clean(
    data: str,
    operations: list[str] | None = None,
    output_format: str = "text",
) -> dict:
    """数据清洗：去重、去空行、格式化、标准化。
    
    支持的操作：
    - dedup: 去重（移除完全相同的行）
    - trim: 去除每行首尾空白
    - remove_empty: 移除空行
    - remove_duplicate_spaces: 合并多余空格
    - lowercase: 转为小写
    - uppercase: 转为大写
    - sort: 按字母顺序排序
    - reverse: 反转行顺序
    - strip_punctuation: 去除标点符号
    - remove_numbers: 移除数字
    - normalize_whitespace: 统一空白字符为空格
    
    Args:
        data: 原始文本数据（每行一条记录）。
        operations: 清洗操作列表，如 ["trim", "dedup", "remove_empty"]。
                    默认：["trim", "remove_empty", "dedup"]。
        output_format: 输出格式（"text" 纯文本, "json" JSON 数组）。
    
    Returns:
        dict: 清洗结果。
    """
    if operations is None:
        operations = ["trim", "remove_empty", "dedup"]

    try:
        lines = data.split("\n")
        original_count = len([l for l in lines if l.strip()])
        original_size = len(data)

        applied_ops = []

        for op in operations:
            op = op.strip().lower()

            if op == "trim":
                lines = [l.strip() for l in lines]
                applied_ops.append("trim")
            
            elif op == "remove_empty":
                lines = [l for l in lines if l]
                applied_ops.append("remove_empty")
            
            elif op == "dedup":
                seen = set()
                deduped = []
                for l in lines:
                    if l not in seen:
                        deduped.append(l)
                        seen.add(l)
                lines = deduped
                applied_ops.append("dedup")
            
            elif op == "remove_duplicate_spaces":
                lines = [re.sub(r' +', ' ', l) for l in lines]
                applied_ops.append("remove_duplicate_spaces")
            
            elif op == "lowercase":
                lines = [l.lower() for l in lines]
                applied_ops.append("lowercase")
            
            elif op == "uppercase":
                lines = [l.upper() for l in lines]
                applied_ops.append("uppercase")
            
            elif op == "sort":
                lines.sort()
                applied_ops.append("sort")
            
            elif op == "reverse":
                lines.reverse()
                applied_ops.append("reverse")
            
            elif op == "strip_punctuation":
                lines = [re.sub(r'[^\w\s]', '', l) for l in lines]
                applied_ops.append("strip_punctuation")
            
            elif op == "remove_numbers":
                lines = [re.sub(r'\d+', '', l) for l in lines]
                applied_ops.append("remove_numbers")
            
            elif op == "normalize_whitespace":
                lines = [re.sub(r'\s+', ' ', l).strip() for l in lines]
                applied_ops.append("normalize_whitespace")

        final_count = len([l for l in lines if l.strip()])
        cleaned_text = "\n".join(lines)

        result = {
            "original_lines": original_count,
            "final_lines": final_count,
            "removed_lines": original_count - final_count,
            "original_size": original_size,
            "final_size": len(cleaned_text),
            "operations_applied": applied_ops,
        }

        if output_format == "json":
            result["data"] = lines
            return {
                "success": True,
                "output": json.dumps(result, ensure_ascii=False),
                "error": None,
            }
        else:
            result["cleaned_text"] = cleaned_text
            summary = (
                f"清洗完成！\n"
                f"原始行数: {original_count} → 最终行数: {final_count} "
                f"(移除 {original_count - final_count} 行)\n"
                f"原始大小: {original_size} → 最终大小: {len(cleaned_text)} 字符\n"
                f"执行操作: {', '.join(applied_ops)}\n"
                f"\n=== 清洗结果 ===\n{cleaned_text[:5000]}"
            )
            if len(cleaned_text) > 5000:
                summary += "\n\n...（结果已截断，完整内容较长）"
            return {
                "success": True,
                "output": summary,
                "error": None,
            }

    except Exception as e:
        return {"success": False, "output": "", "error": f"数据清洗失败: {e}"}


def _export_csv(
    data: list[list[str]] | str,
    headers: list[str] | None = None,
    delimiter: str = ",",
    output_path: str | None = None,
) -> dict:
    """导出 CSV 文件。
    
    Args:
        data: 二维数组数据（list of lists），或字符串（自动解析为 TSV/CSV）。
        headers: CSV 表头（可选，默认使用第一行数据或自动生成）。
        delimiter: 分隔符（默认逗号，也可用制表符 "\\t"）。
        output_path: 输出文件路径（可选，默认保存到临时目录）。
    
    Returns:
        dict: 导出的文件路径和统计信息。
    """
    try:
        # 解析输入数据
        rows: list[list[str]] = []
        if isinstance(data, str):
            # 尝试自动解析
            lines = data.strip().split("\n")
            detected_delim = delimiter
            if not detected_delim or detected_delim == ",":
                # 自动检测分隔符
                if lines and "\t" in lines[0]:
                    detected_delim = "\t"
                elif "|" in lines[0]:
                    detected_delim = "|"
            
            for line in lines:
                if detected_delim == "\t":
                    row = line.split("\t")
                elif detected_delim == "|":
                    row = [c.strip() for c in line.split("|")]
                else:
                    row = list(csv.reader([line]))[0] if line.strip() else []
                if row:
                    rows.append(row)
        elif isinstance(data, list):
            rows = [[str(cell) for cell in row] for row in data if row]
        else:
            return {"success": False, "output": "", "error": "不支持的 data 格式，请提供字符串或二维数组"}

        if not rows:
            return {"success": False, "output": "", "error": "数据为空，无法导出"}

        # 处理表头
        if headers:
            # 使用指定的 headers
            pass
        else:
            # 检查第一行是否适合做表头
            headers = rows[0] if rows else []

        # 确定输出路径
        if not output_path:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            fd, output_path = tempfile.mkstemp(suffix=".csv", prefix=f"export_{timestamp}_")
            os.close(fd)

        # 写入 CSV
        with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, delimiter=delimiter)
            if headers:
                writer.writerow(headers)
            data_rows = rows if not headers else rows[1:]
            for row in data_rows:
                writer.writerow(row)

        file_size = os.path.getsize(output_path)
        return {
            "success": True,
            "output": json.dumps({
                "filepath": output_path,
                "rows": len(rows) - (1 if headers else 0),
                "columns": len(headers) if headers else len(rows[0]) if rows else 0,
                "file_size": file_size,
                "delimiter": delimiter,
            }, ensure_ascii=False),
            "error": None,
        }

    except Exception as e:
        return {"success": False, "output": "", "error": f"CSV 导出失败: {e}"}


def _export_excel(
    data: list[list[str]] | str,
    headers: list[str] | None = None,
    sheet_name: str = "Sheet1",
    output_path: str | None = None,
) -> dict:
    """导出 Excel (.xlsx) 文件。
    
    Args:
        data: 二维数组数据，或字符串（自动解析）。
        headers: 表头（可选）。
        sheet_name: 工作表名称（默认 "Sheet1"）。
        output_path: 输出文件路径（可选，默认保存到临时目录）。
    
    Returns:
        dict: 导出的文件路径和统计信息。
    """
    try:
        import openpyxl
    except ImportError:
        return {
            "success": False, "output": "",
            "error": "缺少 openpyxl，请运行: pip install openpyxl",
        }

    try:
        # 解析输入数据（同 CSV 逻辑）
        rows: list[list[str]] = []
        if isinstance(data, str):
            lines = data.strip().split("\n")
            for line in lines:
                if "\t" in line:
                    row = [c.strip() for c in line.split("\t")]
                elif "|" in line:
                    row = [c.strip() for c in line.split("|")]
                else:
                    row = list(csv.reader([line]))[0] if line.strip() else []
                if row:
                    rows.append(row)
        elif isinstance(data, list):
            rows = [[str(cell) for cell in row] for row in data if row]
        else:
            return {"success": False, "output": "", "error": "不支持的 data 格式"}

        if not rows:
            return {"success": False, "output": "", "error": "数据为空，无法导出"}

        # 创建工作簿
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = sheet_name

        # 写入表头
        start_row = 1
        if headers:
            for col_idx, header in enumerate(headers, 1):
                ws.cell(row=1, column=col_idx, value=header)
            start_row = 2

        # 写入数据
        data_rows = rows if not headers else rows[1:]
        for row_idx, row in enumerate(data_rows, start_row):
            for col_idx, cell_value in enumerate(row, 1):
                ws.cell(row=row_idx, column=col_idx, value=cell_value)

        # 自动调整列宽（粗略）
        for col in ws.columns:
            max_length = 0
            col_letter = col[0].column_letter
            for cell in col:
                try:
                    if cell.value:
                        max_length = max(max_length, len(str(cell.value)))
                except Exception:
                    pass
            adjusted_width = min(max_length + 3, 60)
            ws.column_dimensions[col_letter].width = adjusted_width

        # 确定输出路径
        if not output_path:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            fd, output_path = tempfile.mkstemp(suffix=".xlsx", prefix=f"export_{timestamp}_")
            os.close(fd)

        wb.save(output_path)
        file_size = os.path.getsize(output_path)

        return {
            "success": True,
            "output": json.dumps({
                "filepath": output_path,
                "rows": len(data_rows),
                "columns": len(headers) if headers else len(rows[0]) if rows else 0,
                "sheet": sheet_name,
                "file_size": file_size,
            }, ensure_ascii=False),
            "error": None,
        }

    except Exception as e:
        return {"success": False, "output": "", "error": f"Excel 导出失败: {e}"}


def _chart_generate(
    chart_type: str = "bar",
    title: str = "",
    x_label: str = "",
    y_label: str = "",
    labels: list[str] | None = None,
    values: list[float] | None = None,
    width: int = 800,
    height: int = 500,
) -> dict:
    """生成图表（matplotlib），返回 base64 编码的图片。

    支持的图表类型：
      - bar: 柱状图
      - line: 折线图
      - pie: 饼图
      - scatter: 散点图
      - horizontal_bar: 水平柱状图

    Args:
        chart_type: 图表类型（bar / line / pie / scatter / horizontal_bar）。
        title: 图表标题。
        x_label: X 轴标签。
        y_label: Y 轴标签。
        labels: 数据标签列表。
        values: 数据值列表。
        width: 图片宽度（像素，默认 800）。
        height: 图片高度（像素，默认 500）。

    Returns:
        dict: 包含 base64 编码图片的 JSON 字符串。
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        from io import BytesIO
        import base64
    except ImportError:
        return {
            "success": False, "output": "",
            "error": "缺少 matplotlib，请运行: pip install matplotlib numpy",
        }

    try:
        labels = labels or ["A", "B", "C", "D", "E"]
        values = values or [10, 20, 15, 25, 30]

        fig, ax = plt.subplots(figsize=(width / 100, height / 100), dpi=100)

        if chart_type == "bar":
            ax.bar(labels, values, color="steelblue", edgecolor="white")
            ax.set_xlabel(x_label or "类别")
            ax.set_ylabel(y_label or "数值")

        elif chart_type == "horizontal_bar":
            ax.barh(labels, values, color="steelblue", edgecolor="white")
            ax.set_xlabel(x_label or "数值")
            ax.set_ylabel(y_label or "类别")

        elif chart_type == "line":
            x_pos = np.arange(len(labels))
            ax.plot(labels, values, marker="o", linestyle="-", color="steelblue", linewidth=2)
            ax.set_xlabel(x_label or "类别")
            ax.set_ylabel(y_label or "数值")
            ax.grid(True, alpha=0.3)

        elif chart_type == "pie":
            colors = plt.cm.Set3(np.linspace(0, 1, len(labels)))
            wedges, texts, autotexts = ax.pie(
                values, labels=labels, autopct="%1.1f%%",
                colors=colors, startangle=90,
            )
            ax.axis("equal")

        elif chart_type == "scatter":
            x_pos = np.arange(len(values))
            ax.scatter(x_pos, values, c="steelblue", s=100, alpha=0.7)
            ax.set_xticks(x_pos)
            ax.set_xticklabels(labels)
            ax.set_xlabel(x_label or "类别")
            ax.set_ylabel(y_label or "数值")
            ax.grid(True, alpha=0.3)

        else:
            return {"success": False, "output": "", "error": f"不支持的图表类型: {chart_type}，支持: bar/line/pie/scatter/horizontal_bar"}

        if title:
            ax.set_title(title, fontsize=14, pad=15)

        fig.tight_layout()

        # 保存到 BytesIO，编码为 base64
        buf = BytesIO()
        fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)
        img_b64 = base64.b64encode(buf.read()).decode("utf-8")
        buf.close()

        result = {
            "chart_type": chart_type,
            "title": title,
            "width": width,
            "height": height,
            "image_base64": img_b64,
            "data_points": len(labels),
            "mime_type": "image/png",
        }

        return {
            "success": True,
            "output": json.dumps(result, ensure_ascii=False),
            "error": None,
        }

    except Exception as e:
        return {"success": False, "output": "", "error": f"图表生成失败: {e}"}


# ══════════════════════════════════════════════════
# MCP Server 定义
# ══════════════════════════════════════════════════

app = Server("data_server")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """声明此服务器提供的工具列表。"""
    return [
        Tool(
            name="convert_document",
            description="文档格式转换：将 PDF/DOCX/PPTX/XLSX/HTML/Markdown/CSV 等文档转换为纯文本。"
                        "使用 Markitdown 引擎，支持多种主流格式。"
                        "自动截断超过 10000 字符的内容。",
            inputSchema={
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "文档文件路径（支持 PDF/DOCX/PPTX/XLSX/HTML/MD/CSV/JSON/XML/图片）",
                    },
                },
                "required": ["filepath"],
            },
        ),
        Tool(
            name="data_clean",
            description="数据清洗与格式化。支持多种清洗操作：\n"
                        "- trim: 去除每行首尾空白\n"
                        "- remove_empty: 移除空行\n"
                        "- dedup: 去重（移除完全相同的行）\n"
                        "- sort: 按字母顺序排序\n"
                        "- lowercase / uppercase: 大小写转换\n"
                        "- strip_punctuation: 去除标点\n"
                        "- remove_numbers: 移除数字\n"
                        "- normalize_whitespace: 统一空白字符\n"
                        "- reverse: 反转行顺序",
            inputSchema={
                "type": "object",
                "properties": {
                    "data": {
                        "type": "string",
                        "description": "原始文本数据（每行一条记录）",
                    },
                    "operations": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "清洗操作列表，如 [\"trim\", \"remove_empty\", \"dedup\"]。"
                                       "默认：[trim, remove_empty, dedup]",
                    },
                    "output_format": {
                        "type": "string",
                        "description": "输出格式：'text' 纯文本（默认）或 'json' JSON 数组",
                        "default": "text",
                        "enum": ["text", "json"],
                    },
                },
                "required": ["data"],
            },
        ),
        Tool(
            name="export_csv",
            description="导出 CSV 文件。支持从字符串（自动检测分隔符）或二维数组导出。"
                        "可选指定表头和输出路径。",
            inputSchema={
                "type": "object",
                "properties": {
                    "data": {
                        "type": "string",
                        "description": "数据内容（字符串格式，每行一条记录，支持 CSV/TSV/管道符分隔），或 JSON 二维数组",
                    },
                    "headers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "CSV 表头（可选，默认自动推断）",
                    },
                    "delimiter": {
                        "type": "string",
                        "description": "分隔符（默认逗号，也可用制表符 \\t）",
                        "default": ",",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "输出文件路径（可选，默认保存到临时目录）",
                    },
                },
                "required": ["data"],
            },
        ),
        Tool(
            name="export_excel",
            description="导出 Excel (.xlsx) 文件。支持从字符串或二维数组导出。"
                        "自动调整列宽，支持指定工作表名称。",
            inputSchema={
                "type": "object",
                "properties": {
                    "data": {
                        "type": "string",
                        "description": "数据内容（字符串或 JSON 二维数组）",
                    },
                    "headers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Excel 表头（可选）",
                    },
                    "sheet_name": {
                        "type": "string",
                        "description": "工作表名称（默认 \"Sheet1\"）",
                        "default": "Sheet1",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "输出文件路径（可选，默认保存到临时目录）",
                    },
                },
                "required": ["data"],
            },
        ),
        Tool(
            name="chart_generate",
            description="生成图表（matplotlib），返回 base64 编码的 PNG 图片。"
                        "支持柱状图、折线图、饼图、散点图、水平柱状图。"
                        "需安装 matplotlib 和 numpy。",
            inputSchema={
                "type": "object",
                "properties": {
                    "chart_type": {
                        "type": "string",
                        "description": "图表类型: bar（柱状图）, line（折线图）, pie（饼图）, scatter（散点图）, horizontal_bar（水平柱状图）",
                        "default": "bar",
                    },
                    "title": {
                        "type": "string",
                        "description": "图表标题",
                    },
                    "x_label": {
                        "type": "string",
                        "description": "X 轴标签",
                    },
                    "y_label": {
                        "type": "string",
                        "description": "Y 轴标签",
                    },
                    "labels": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "数据标签列表（如 [\"Q1\", \"Q2\", \"Q3\", \"Q4\"]）",
                    },
                    "values": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "数据值列表（如 [100, 200, 150, 300]）",
                    },
                    "width": {
                        "type": "integer",
                        "description": "图片宽度（像素，默认 800）",
                        "default": 800,
                    },
                    "height": {
                        "type": "integer",
                        "description": "图片高度（像素，默认 500）",
                        "default": 500,
                    },
                },
                "required": [],
            },
        ),
    ]


@app.call_tool()
async def call_tool(
    name: str,
    arguments: dict,
) -> list[TextContent]:
    """处理工具调用请求。"""
    valid_tools = ("convert_document", "data_clean", "export_csv", "export_excel", "chart_generate")
    if name not in valid_tools:
        raise ValueError(f"未知工具: {name}，此服务器仅提供 {', '.join(valid_tools)} 工具")

    if name == "convert_document":
        filepath = arguments.get("filepath", "")
        if not filepath:
            return [TextContent(type="text", text=json.dumps(
                {"success": False, "output": "", "error": "'filepath' 参数不能为空"}
            ))]
        logger.info("文档转换: filepath=%s", filepath)
        result = _call_tools_func("convert_document", {"filepath": filepath})

    elif name == "data_clean":
        data = arguments.get("data", "")
        if not data:
            return [TextContent(type="text", text=json.dumps(
                {"success": False, "output": "", "error": "'data' 参数不能为空"}
            ))]
        operations = arguments.get("operations")
        output_format = arguments.get("output_format", "text")
        logger.info("数据清洗: ops=%s format=%s", operations, output_format)
        result = _data_clean(data, operations, output_format)

    elif name == "export_csv":
        data = arguments.get("data", "")
        if not data:
            return [TextContent(type="text", text=json.dumps(
                {"success": False, "output": "", "error": "'data' 参数不能为空"}
            ))]
        headers = arguments.get("headers")
        delimiter = arguments.get("delimiter", ",")
        output_path = arguments.get("output_path")
        logger.info("导出 CSV: delimiter=%s", delimiter)
        result = _export_csv(data, headers, delimiter, output_path)

    elif name == "export_excel":
        data = arguments.get("data", "")
        if not data:
            return [TextContent(type="text", text=json.dumps(
                {"success": False, "output": "", "error": "'data' 参数不能为空"}
            ))]
        headers = arguments.get("headers")
        sheet_name = arguments.get("sheet_name", "Sheet1")
        output_path = arguments.get("output_path")
        logger.info("导出 Excel: sheet=%s", sheet_name)
        result = _export_excel(data, headers, sheet_name, output_path)

    elif name == "chart_generate":
        chart_type = arguments.get("chart_type", "bar")
        title = arguments.get("title", "")
        x_label = arguments.get("x_label", "")
        y_label = arguments.get("y_label", "")
        labels = arguments.get("labels")
        values = arguments.get("values")
        width = arguments.get("width", 800)
        height = arguments.get("height", 500)
        logger.info("图表生成: type=%s title=%s", chart_type, title)
        result = _chart_generate(chart_type, title, x_label, y_label, labels, values, width, height)

    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]


# ══════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════

async def main() -> None:
    """启动 MCP Server（stdio 传输层）。"""
    logger.info("data_server 启动中...")

    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )

    logger.info("data_server 已关闭")


def _run_main() -> None:
    """同步入口（供 __main__ 块调用）。"""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("data_server 收到中断信号，退出")
    except Exception as e:
        logger.error("data_server 异常退出: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    _run_main()
