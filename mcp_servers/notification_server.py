#!/usr/bin/env python3
"""MCP Server: notification_server — 通知工具

独立的 MCP Server 进程，通过 stdio 传输层与星枢引擎通信。
提供邮件发送（SMTP）和短信发送（网关占位）能力。

启动方式:
    python -m mcp_servers.notification_server
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s %(name)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("notification_server")

# ──────────────────────────────────────────────
# MCP SDK 导入
# ──────────────────────────────────────────────
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
except ImportError:
    print("缺少 mcp Python 库，请运行: pip install mcp", file=sys.stderr)
    sys.exit(1)


# ══════════════════════════════════════════════════
# 工具实现
# ══════════════════════════════════════════════════


def _email_send(
    to: str,
    subject: str,
    body: str,
    smtp_host: str | None = None,
    smtp_port: int | None = None,
    smtp_user: str | None = None,
    smtp_pass: str | None = None,
    use_tls: bool = True,
) -> dict:
    """发送邮件（SMTP）。

    优先使用传入参数，否则从环境变量读取默认值：
      SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS

    Args:
        to: 收件人邮箱。
        subject: 邮件主题。
        body: 邮件正文（纯文本）。
        smtp_host: SMTP 服务器地址。
        smtp_port: SMTP 端口。
        smtp_user: SMTP 用户名。
        smtp_pass: SMTP 密码。
        use_tls: 是否使用 TLS（默认 True）。

    Returns:
        dict: 发送结果。
    """
    host = smtp_host or os.environ.get("SMTP_HOST", "")
    port = smtp_port or int(os.environ.get("SMTP_PORT", "587"))
    user = smtp_user or os.environ.get("SMTP_USER", "")
    pwd = smtp_pass or os.environ.get("SMTP_PASS", "")

    if not host or not user or not pwd:
        return {
            "success": False,
            "output": "",
            "error": "SMTP 未配置。请设置 SMTP_HOST/SMTP_USER/SMTP_PASS 环境变量或传入参数。",
        }

    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.header import Header

        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = user
        msg["To"] = to

        if use_tls:
            server = smtplib.SMTP(host, port)
            server.ehlo()
            server.starttls()
            server.ehlo()
        else:
            server = smtplib.SMTP(host, port)

        server.login(user, pwd)
        server.sendmail(user, [to], msg.as_string())
        server.quit()

        logger.info("邮件发送成功: to=%s subject=%s", to, subject)
        return {"success": True, "output": f"邮件已发送至 {to}", "error": None}

    except Exception as e:
        logger.error("邮件发送失败: %s", e)
        return {"success": False, "output": "", "error": f"邮件发送失败: {e}"}


def _sms_send(
    phone: str,
    message: str,
    provider: str = "placeholder",
) -> dict:
    """发送短信（占位实现，待接真实网关）。

    Args:
        phone: 接收手机号。
        message: 短信内容。
        provider: 短信服务商（placeholder / twilio / aliyun 等）。

    Returns:
        dict: 发送结果。
    """
    logger.info("短信发送(占位): phone=%s message=%s provider=%s", phone, message[:50], provider)
    # 占位：记录日志，返回模拟成功
    return {
        "success": True,
        "output": json.dumps({
            "phone": phone,
            "message_preview": message[:100],
            "provider": provider,
            "status": "simulated_sent",
            "note": "短信网关尚未接入，此为占位实现。接入真实网关后配置 SMS_PROVIDER/SMS_API_KEY 环境变量。",
        }, ensure_ascii=False),
        "error": None,
    }


# ══════════════════════════════════════════════════
# MCP Server 定义
# ══════════════════════════════════════════════════

app = Server("notification_server")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """声明此服务器提供的工具列表。"""
    return [
        Tool(
            name="email_send",
            description="Send email via SMTP. Requires SMTP_HOST/USER/PASS env vars / 发送邮件（SMTP）。"
                        "支持 TLS 加密，正文为纯文本。",
            inputSchema={
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "description": "收件人邮箱地址",
                    },
                    "subject": {
                        "type": "string",
                        "description": "邮件主题",
                    },
                    "body": {
                        "type": "string",
                        "description": "邮件正文（纯文本）",
                    },
                    "smtp_host": {
                        "type": "string",
                        "description": "SMTP server address (optional, defaults to SMTP_HOST env var) / SMTP 服务器地址",
                    },
                    "smtp_port": {
                        "type": "integer",
                        "description": "SMTP 端口（可选，默认 587）",
                    },
                    "smtp_user": {
                        "type": "string",
                        "description": "SMTP username (optional, defaults to SMTP_USER env var) / SMTP 用户名",
                    },
                    "smtp_pass": {
                        "type": "string",
                        "description": "SMTP password (optional, defaults to SMTP_PASS env var) / SMTP 密码",
                    },
                    "use_tls": {
                        "type": "boolean",
                        "description": "是否使用 TLS（默认 True）",
                        "default": True,
                    },
                },
                "required": ["to", "subject", "body"],
            },
        ),
        Tool(
            name="sms_send",
            description="Send SMS (placeholder). Uses mock gateway / 发送短信（占位实现）。"
                        "支持 provider 参数预留对接 Twilio/阿里云等。",
            inputSchema={
                "type": "object",
                "properties": {
                    "phone": {
                        "type": "string",
                        "description": "接收手机号（国际格式，如 +8613800138000）",
                    },
                    "message": {
                        "type": "string",
                        "description": "短信内容",
                    },
                    "provider": {
                        "type": "string",
                        "description": "短信服务商（placeholder 占位 / twilio / aliyun，默认 placeholder）",
                        "default": "placeholder",
                    },
                },
                "required": ["phone", "message"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(
    name: str,
    arguments: dict,
) -> list[TextContent]:
    """处理工具调用请求。"""
    if name not in ("email_send", "sms_send"):
        raise ValueError(f"未知工具: {name}，此服务器仅提供 email_send/sms_send 工具")

    if name == "email_send":
        to = arguments.get("to", "")
        subject = arguments.get("subject", "")
        body = arguments.get("body", "")
        if not to or not subject or not body:
            return [TextContent(type="text", text=json.dumps(
                {"success": False, "output": "", "error": "'to', 'subject', 'body' 参数不能为空"}
            ))]
        logger.info("发送邮件: to=%s subject=%s", to, subject)
        result = _email_send(
            to=to,
            subject=subject,
            body=body,
            smtp_host=arguments.get("smtp_host"),
            smtp_port=arguments.get("smtp_port"),
            smtp_user=arguments.get("smtp_user"),
            smtp_pass=arguments.get("smtp_pass"),
            use_tls=arguments.get("use_tls", True),
        )

    elif name == "sms_send":
        phone = arguments.get("phone", "")
        message = arguments.get("message", "")
        provider = arguments.get("provider", "placeholder")
        if not phone or not message:
            return [TextContent(type="text", text=json.dumps(
                {"success": False, "output": "", "error": "'phone', 'message' 参数不能为空"}
            ))]
        logger.info("发送短信: phone=%s provider=%s", phone, provider)
        result = _sms_send(phone=phone, message=message, provider=provider)

    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]


# ══════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════

async def main() -> None:
    """启动 MCP Server（stdio 传输层）。"""
    logger.info("notification_server 启动中...")

    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )

    logger.info("notification_server 已关闭")


def _run_main() -> None:
    """同步入口（供 __main__ 块调用）。"""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("notification_server 收到中断信号，退出")
    except Exception as e:
        logger.error("notification_server 异常退出: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    _run_main()
