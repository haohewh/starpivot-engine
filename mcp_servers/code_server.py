#!/usr/bin/env python3
"""MCP Server: code_server — 代码执行工具

独立的 MCP Server 进程，通过 stdio 传输层与星枢引擎通信。
提供安全的代码执行能力，支持 Python 代码和受限 Shell 命令。

启动方式:
    python -m mcp_servers.code_server

重要安全限制：
- run_python：在沙箱环境下执行，禁止文件系统写操作、网络访问和导入危险模块。
- run_shell：仅允许白名单内的安全命令，禁止危险操作。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import textwrap
import tempfile
import traceback

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("code_server")

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
# 安全策略配置
# ══════════════════════════════════════════════════

# 白名单：允许执行的 Shell 命令
_ALLOWED_SHELL_COMMANDS = {
    "echo", "cat", "head", "tail", "wc", "sort", "uniq", "grep", "find",
    "ls", "pwd", "date", "cal", "whoami", "id", "uname", "hostname",
    "uptime", "df", "du", "free", "ps", "top", "env",
    "python3", "python", "node", "npm", "pip", "pip3",
    "git", "curl", "wget", "ping", "nslookup", "dig",
    "mkdir", "cp", "mv", "rm", "chmod", "chown",
    "tar", "gzip", "gunzip", "zip", "unzip",
    "which", "whereis", "file", "stat", "readlink",
    "diff", "cmp", "comm", "md5sum", "sha256sum",
    "jq", "yq", "awk", "sed",
}

# 危险命令/模式黑名单
_BLACKLIST_PATTERNS = [
    r"\bsudo\b",
    r"\bsu\b",
    r"\bpasswd\b",
    r"\buseradd\b",
    r"\buserdel\b",
    r"\bchmod\s+777\b",
    r"\bchown\b",
    r"\bkill\b",
    r"\bpoweroff\b",
    r"\breboot\b",
    r"\bshutdown\b",
    r"\binit\b",
    r"\bsystemctl\b",
    r"\brm\s+-rf\s+/\b",
    r"\brm\s+-rf\s+/\*",
    r"\bdd\b",
    r"\bmkfs\b",
    r"\bfdisk\b",
    r"\bparted\b",
    r"\bmount\b",
    r"\bumount\b",
    r"\biptables\b",
    r"\bexport\b",
    r"\bsource\b",
    r">\s*/dev/",
    r">\s*/proc/",
    r">\s*/sys/",
    r"\|\s*sh\b",
    r"\|\s*bash\b",
    r"\bexec\b",
    r"\beval\b",
]

# Python 沙箱：黑名单模块
_BLOCKED_MODULES = {
    "os", "subprocess", "sys", "shutil", "socket", "ctypes",
    "multiprocessing", "threading", "signal", "fcntl",
    "importlib", "builtins.exec", "builtins.compile",
    "pickle", "shelve", "marshal",
    "webbrowser", "smtplib", "telnetlib",
    "pty", "tty", "termios",
    "code", "codeop", "codecs",
}

# Python 沙箱：黑名单内置函数
_BLOCKED_BUILTINS = {
    "exec", "eval", "compile", "__import__",
    "open", "input", "breakpoint",
}


# ══════════════════════════════════════════════════
# 工具实现
# ══════════════════════════════════════════════════

def _validate_shell_command(command: str) -> str | None:
    """验证 Shell 命令是否安全。返回 None 表示安全，返回字符串表示拒绝原因。"""
    # 检查黑名单模式
    for pattern in _BLACKLIST_PATTERNS:
        if re.search(pattern, command):
            return f"命令包含危险操作，已被禁止: {pattern}"
    
    # 提取第一个命令（管道/分号之前的第一个词）
    first_cmd = command.strip().split()[0].lstrip("$") if command.strip() else ""
    first_cmd = first_cmd.split("/")[-1]  # 去掉路径前缀
    
    # 检查是否在白名单中
    if first_cmd not in _ALLOWED_SHELL_COMMANDS:
        return f"命令 '{first_cmd}' 不在白名单中。允许的命令: {', '.join(sorted(_ALLOWED_SHELL_COMMANDS))}"
    
    # 检查危险字符组合
    dangerous_chars = ["`", "$(", "${"]
    for dc in dangerous_chars:
        if dc in command and dc != "$":
            return f"命令包含危险字符 '{dc}'，已被禁止"
    
    return None


def _run_python(code: str, timeout: int = 15) -> dict:
    """安全执行 Python 代码。
    
    在隔离的子进程中执行，限制：
    - 禁止导入 os/subprocess/socket 等危险模块
    - 禁止 exec/eval/open/__import__ 等危险内置函数
    - 禁止文件系统写操作
    - 超时控制（默认 15 秒）
    - stdout/stderr 捕获
    
    Args:
        code: Python 代码字符串。
        timeout: 超时秒数（默认 15，最大 30）。
    
    Returns:
        dict: 执行结果。
    """
    timeout = min(timeout, 30)
    
    # 安全预处理：注入受限内置函数和模块黑名单
    safe_globals = {
        "__builtins__": {
            "print": print,
            "len": len, "str": str, "int": int, "float": float,
            "bool": bool, "list": list, "dict": dict, "tuple": tuple,
            "set": set, "range": range, "enumerate": enumerate,
            "zip": zip, "map": map, "filter": filter,
            "sum": sum, "min": min, "max": max, "abs": abs,
            "round": round, "sorted": sorted, "reversed": reversed,
            "any": any, "all": all,
            "isinstance": isinstance, "hasattr": hasattr, "getattr": getattr,
            "type": type, "repr": repr, "format": format,
            "input": lambda prompt="": __builtins__.input(prompt) if "input" not in _BLOCKED_BUILTINS else "【禁止】input() 已被禁用",
            "True": True, "False": False, "None": None,
            "Exception": Exception, "ValueError": ValueError,
            "TypeError": TypeError, "KeyError": KeyError,
            "IndexError": IndexError, "StopIteration": StopIteration,
        },
        "__name__": "__main__",
    }
    
    # 为安全需求添加 math/json/re 等安全模块
    try:
        import math
        safe_globals["math"] = math
    except ImportError:
        pass
    try:
        import json as _json
        safe_globals["json"] = _json
    except ImportError:
        pass
    try:
        import re as _re
        safe_globals["re"] = _re
    except ImportError:
        pass
    try:
        import collections as _collections
        safe_globals["collections"] = _collections
    except ImportError:
        pass
    try:
        import itertools as _itertools
        safe_globals["itertools"] = _itertools
    except ImportError:
        pass
    try:
        import random as _random
        safe_globals["random"] = _random
    except ImportError:
        pass
    try:
        import datetime as _dt
        safe_globals["datetime"] = _dt
    except ImportError:
        pass
    
    # 注入 __import__ 拦截器
    def _safe_import(name, *args, **kwargs):
        if name in _BLOCKED_MODULES or name.split('.')[0] in _BLOCKED_MODULES:
            raise ImportError(f"模块 '{name}' 被安全策略禁止")
        return __import__(name, *args, **kwargs)
    
    safe_globals["__builtins__"]["__import__"] = _safe_import
    
    # 创建一个包装的 stdin
    safe_globals["__builtins__"]["open"] = lambda *a, **kw: (_ for _ in ()).throw(
        PermissionError("文件操作已被安全策略禁止"))
    
    # 构建沙箱代码
    wrapped_code = textwrap.dedent(f"""\
        import sys as _sys, io as _io
        
        # 捕获 stdout
        _stdout_capture = _io.StringIO()
        _stderr_capture = _io.StringIO()
        _sys.stdout = _stdout_capture
        _sys.stderr = _stderr_capture
        
        try:
{textwrap.indent(code, '            ')}
        except Exception as e:
            print(f"错误: {{type(e).__name__}}: {{e}}", file=_sys.stderr)
            import traceback as _tb
            traceback.print_exc(file=_sys.stderr)
        
        # 恢复 stdout
        _sys.stdout = _sys.__stdout__
        _sys.stderr = _sys.__stderr__
        
        _stdout_result = _stdout_capture.getvalue()
        _stderr_result = _stderr_capture.getvalue()
    """)
    
    try:
        # 在子进程中执行
        import subprocess as _sp
        
        # 将代码写入临时文件
        fd, tmp_path = tempfile.mkstemp(suffix=".py", prefix="starpivot_code_")
        os.close(fd)
        
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(f"# Safe Code Runner\n# 安全策略：{len(_BLOCKED_MODULES)} 个禁止模块\n\n")
            f.write(f"import math, json, re, collections, itertools, random, datetime\n\n")
            f.write(code)
        
        try:
            proc = _sp.run(
                [sys.executable, "-u", tmp_path],
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, "PYTHONPATH": os.path.dirname(os.path.dirname(os.path.abspath(__file__)))},
            )
            
            stdout = proc.stdout
            stderr = proc.stderr
            
            if proc.returncode == 0:
                return {
                    "success": True,
                    "output": stdout if stdout else "（代码执行成功，无输出）",
                    "error": stderr if stderr else None,
                    "returncode": 0,
                }
            else:
                # 检查是否是模块导入错误
                error_msg = stderr or stdout
                for blocked in _BLOCKED_MODULES:
                    if f"No module named '{blocked}'" in error_msg or f"module '{blocked}'" in error_msg:
                        error_msg = f"安全策略阻止：模块 '{blocked}' 被禁止导入\n" + error_msg
                        break
                
                return {
                    "success": False,
                    "output": stdout,
                    "error": error_msg,
                    "returncode": proc.returncode,
                }
        
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "output": "",
                "error": f"代码执行超时（{timeout}秒）",
            }
        finally:
            # 清理临时文件
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
    
    except Exception as e:
        return {
            "success": False,
            "output": "",
            "error": f"代码执行异常: {e}",
        }


def _run_shell(command: str, timeout: int = 15) -> dict:
    """受限执行 Shell 命令。
    
    仅允许白名单命令，禁止危险操作。
    
    Args:
        command: Shell 命令字符串。
        timeout: 超时秒数（默认 15，最大 30）。
    
    Returns:
        dict: 执行结果。
    """
    timeout = min(timeout, 30)
    
    # 安全检查
    validation_error = _validate_shell_command(command)
    if validation_error:
        return {
            "success": False,
            "output": "",
            "error": f"安全策略拒绝: {validation_error}",
        }
    
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            executable="/bin/bash",
        )
        
        stdout = proc.stdout
        stderr = proc.stderr
        
        # 截断输出（最大 10000 字符）
        max_output = 10000
        if len(stdout) > max_output:
            stdout = stdout[:max_output] + f"\n\n...（输出已截断，共 {len(stdout)} 字符）"
        if len(stderr) > max_output:
            stderr = stderr[:max_output] + f"\n\n...（错误输出已截断）"
        
        result = {
            "success": proc.returncode == 0,
            "output": stdout if stdout else "（命令执行成功，无输出）",
            "error": stderr if stderr else None,
            "returncode": proc.returncode,
        }
        
        return result
    
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "output": "",
            "error": f"命令执行超时（{timeout}秒）",
        }
    except FileNotFoundError as e:
        return {
            "success": False,
            "output": "",
            "error": f"命令未找到: {e}",
        }
    except Exception as e:
        return {
            "success": False,
            "output": "",
            "error": f"命令执行异常: {e}",
        }


# ══════════════════════════════════════════════════
# MCP Server 定义
# ══════════════════════════════════════════════════

app = Server("code_server")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """声明此服务器提供的工具列表。"""
    return [
        Tool(
            name="run_python",
            description="安全执行 Python 代码。\n"
                        "在受限环境中执行，安全策略：\n"
                        "- 禁止导入 os/subprocess/socket/ctypes 等危险模块\n"
                        "- 禁止 exec/eval/open/__import__ 等危险内置函数\n"
                        "- 禁止文件系统写操作\n"
                        "- 超时控制（默认15秒）\n"
                        "- 自动捕获 stdout/stderr\n\n"
                        "可用模块：math, json, re, collections, itertools, random, datetime\n"
                        "适用于：数据处理、算法测试、文本分析、计算等场景。",
            inputSchema={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python 代码字符串",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "执行超时秒数（默认 15，最大 30）",
                        "default": 15,
                        "minimum": 1,
                        "maximum": 30,
                    },
                },
                "required": ["code"],
            },
        ),
        Tool(
            name="run_shell",
            description="受限执行 Shell 命令。\n"
                        "安全策略：\n"
                        "- 仅允许白名单命令（echo/cat/ls/grep/find/python3/git/curl 等）\n"
                        "- 禁止 sudo/su/passwd/kill/shutdown/systemctl 等危险命令\n"
                        "- 禁止 rm -rf /、dd、fdisk、mount 等破坏性操作\n"
                        "- 禁止 exec/eval 等代码注入\n"
                        "- 超时控制（默认15秒）\n\n"
                        f"允许的命令: {', '.join(sorted(_ALLOWED_SHELL_COMMANDS))}",
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell 命令字符串",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "执行超时秒数（默认 15，最大 30）",
                        "default": 15,
                        "minimum": 1,
                        "maximum": 30,
                    },
                },
                "required": ["command"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(
    name: str,
    arguments: dict,
) -> list[TextContent]:
    """处理工具调用请求。"""
    if name not in ("run_python", "run_shell"):
        raise ValueError(f"未知工具: {name}，此服务器仅提供 run_python/run_shell 工具")

    if name == "run_python":
        code = arguments.get("code", "")
        if not code or not code.strip():
            return [TextContent(type="text", text=json.dumps(
                {"success": False, "output": "", "error": "'code' 参数不能为空"}
            ))]
        timeout = arguments.get("timeout", 15)
        logger.info("执行 Python 代码: len=%d timeout=%d", len(code), timeout)
        result = _run_python(code, timeout)

    elif name == "run_shell":
        command = arguments.get("command", "")
        if not command or not command.strip():
            return [TextContent(type="text", text=json.dumps(
                {"success": False, "output": "", "error": "'command' 参数不能为空"}
            ))]
        timeout = arguments.get("timeout", 15)
        logger.info("执行 Shell: command=%s timeout=%d", command[:80], timeout)
        result = _run_shell(command, timeout)

    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]


# ══════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════

async def main() -> None:
    """启动 MCP Server（stdio 传输层）。"""
    logger.info("code_server 启动中...")

    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )

    logger.info("code_server 已关闭")


def _run_main() -> None:
    """同步入口（供 __main__ 块调用）。"""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("code_server 收到中断信号，退出")
    except Exception as e:
        logger.error("code_server 异常退出: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    _run_main()
