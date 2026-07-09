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



# === data tools ===


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

