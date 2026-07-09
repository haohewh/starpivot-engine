#!/usr/bin/env python3
"""MCP Server: finance_server — 财务委员会工具

独立的 MCP Server 进程，通过 stdio 传输层与星枢引擎通信。
提供财务报表生成、审计查询、预算管理、发票管理和税务计算能力。

启动方式:
    python -m mcp_servers.finance_server

复用 core/starpivot/finance/committee.py 中的 FinanceCommittee 类。
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
logger = logging.getLogger("finance_server")

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
# MCP Server 定义
# ══════════════════════════════════════════════════

app = Server("finance_server")


@app.list_tools()
async def list_tools() -> list[Tool]:
    """声明此服务器提供的工具列表。"""
    return [
        Tool(
            name="finance_report",
            description="Generate financial statements: P&L, balance sheet, cash flow (JSON/CSV/Text) / 财务报表生成",
            inputSchema={
                "type": "object",
                "properties": {
                    "report_type": {
                        "type": "string",
                        "description": "报表类型: income（损益表）, balance（资产负债表）, cashflow（现金流量表）",
                        "default": "income",
                    },
                    "start_date": {
                        "type": "string",
                        "description": "开始日期 (YYYY-MM-DD，可选)",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "结束日期 (YYYY-MM-DD，可选)",
                    },
                    "format": {
                        "type": "string",
                        "description": "输出格式: json / csv / text（默认 json）",
                        "default": "json",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="finance_audit",
            description="Query audit logs with filters (operation type, operator, target, keyword) / 审计查询",
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "按操作类型筛选（如 budget_approve, invoice_verify, payment_execute）",
                    },
                    "operator": {
                        "type": "string",
                        "description": "按操作人筛选",
                    },
                    "target_type": {
                        "type": "string",
                        "description": "按目标类型筛选（budget / invoice / payment）",
                    },
                    "keyword": {
                        "type": "string",
                        "description": "关键词搜索（在详情中匹配）",
                    },
                    "start_date": {
                        "type": "string",
                        "description": "开始时间 (YYYY-MM-DD)",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "结束时间 (YYYY-MM-DD)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回条数限制（默认 50）",
                        "default": 50,
                    },
                    "offset": {
                        "type": "integer",
                        "description": "偏移量（默认 0）",
                        "default": 0,
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="finance_budget",
            description="Budget management: list, create, update budget items by department/fiscal year / 预算管理",
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "操作: list（列出，默认）, create（创建）, update（更新）",
                        "default": "list",
                    },
                    "department": {
                        "type": "string",
                        "description": "部门名称（筛选/创建时使用）",
                    },
                    "category": {
                        "type": "string",
                        "description": "预算类别（创建时使用）",
                    },
                    "total_amount": {
                        "type": "number",
                        "description": "预算总金额（创建/更新时使用）",
                    },
                    "fiscal_year": {
                        "type": "integer",
                        "description": "财年（默认 2026）",
                    },
                    "budget_id": {
                        "type": "string",
                        "description": "预算 ID（更新时使用）",
                    },
                    "status": {
                        "type": "string",
                        "description": "状态: active / frozen / closed（更新时使用）",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="finance_invoice",
            description="Invoice management: list, create, verify invoices / 发票管理：列出发票、录入发票、核验发票。",
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "操作: list（列出，默认）, create（录入）, verify（核验）",
                        "default": "list",
                    },
                    "status": {
                        "type": "string",
                        "description": "发票状态筛选: pending / verified / paid / cancelled",
                    },
                    "issuer": {
                        "type": "string",
                        "description": "开票方名称（筛选）",
                    },
                    "start_date": {
                        "type": "string",
                        "description": "开始日期",
                    },
                    "end_date": {
                        "type": "string",
                        "description": "结束日期",
                    },
                    "invoice_no": {
                        "type": "string",
                        "description": "发票号码（录入时使用）",
                    },
                    "amount": {
                        "type": "number",
                        "description": "发票金额（录入时使用）",
                    },
                    "tax_amount": {
                        "type": "number",
                        "description": "税额（录入时使用）",
                    },
                    "invoice_type": {
                        "type": "string",
                        "description": "发票类型（录入时使用，如 增值税专用发票）",
                    },
                    "invoice_id": {
                        "type": "string",
                        "description": "发票 ID（核验时使用）",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "返回条数限制（默认 50）",
                        "default": 50,
                    },
                    "offset": {
                        "type": "integer",
                        "description": "偏移量（默认 0）",
                        "default": 0,
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="finance_tax",
            description="Tax calculation: VAT, corporate income tax, personal income tax estimates / 税务计算",
            inputSchema={
                "type": "object",
                "properties": {
                    "tax_type": {
                        "type": "string",
                        "description": "税种: vat（增值税）, enterprise（企业所得税）, personal（个人所得税）",
                        "default": "vat",
                    },
                    "amount": {
                        "type": "number",
                        "description": "不含税金额（增值税/企业所得税用）",
                    },
                    "tax_payer_type": {
                        "type": "string",
                        "description": "纳税人类型: general（一般纳税人）, general_service（一般纳税人-服务）, small_scale（小规模）",
                        "default": "general",
                    },
                    "is_service": {
                        "type": "boolean",
                        "description": "是否为服务（一般纳税人服务税率 6%）",
                    },
                    "revenue": {
                        "type": "number",
                        "description": "营业收入（企业所得税用）",
                    },
                    "cost": {
                        "type": "number",
                        "description": "营业成本+费用（企业所得税用）",
                    },
                    "is_small_micro": {
                        "type": "boolean",
                        "description": "是否为小型微利企业",
                    },
                    "monthly_income": {
                        "type": "number",
                        "description": "月收入（个人所得税用）",
                    },
                    "deduction": {
                        "type": "number",
                        "description": "专项扣除+起征点（默认 5000）",
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
    valid_tools = ("finance_report", "finance_audit", "finance_budget", "finance_invoice", "finance_tax")
    if name not in valid_tools:
        raise ValueError(f"未知工具: {name}，此服务器仅提供 {', '.join(valid_tools)} 工具")

    from core.starpivot.finance.committee import FinanceCommittee
    committee = FinanceCommittee()

    if name == "finance_report":
        report_type = arguments.get("report_type", "income")
        start_date = arguments.get("start_date", "")
        end_date = arguments.get("end_date", "")
        fmt = arguments.get("format", "json")
        logger.info("财务报表: type=%s start=%s end=%s format=%s", report_type, start_date, end_date, fmt)
        result = committee.generate_report(report_type, start_date, end_date, fmt)

    elif name == "finance_audit":
        logger.info("审计查询: args=%s", arguments)
        result = committee.audit_query_func(**arguments)

    elif name == "finance_budget":
        action = arguments.get("action", "list")
        logger.info("预算管理: action=%s", action)
        if action == "list":
            result = committee.list_budgets(
                department=arguments.get("department", ""),
                fiscal_year=arguments.get("fiscal_year", 0),
            )
        elif action == "create":
            result = committee.create_budget(
                department=arguments.get("department", ""),
                category=arguments.get("category", ""),
                total_amount=arguments.get("total_amount", 0.0),
                fiscal_year=arguments.get("fiscal_year", 2026),
            )
        elif action == "update":
            result = committee.update_budget(
                budget_id=arguments.get("budget_id", ""),
                total_amount=arguments.get("total_amount"),
                status=arguments.get("status"),
            )
        else:
            result = {"success": False, "message": f"不支持的预算操作: {action}", "data": None}

    elif name == "finance_invoice":
        action = arguments.get("action", "list")
        logger.info("发票管理: action=%s", action)
        if action == "list":
            result = committee.list_invoices(
                status=arguments.get("status", ""),
                issuer=arguments.get("issuer", ""),
                start_date=arguments.get("start_date", ""),
                end_date=arguments.get("end_date", ""),
                limit=arguments.get("limit", 50),
                offset=arguments.get("offset", 0),
            )
        elif action == "create":
            result = committee.create_invoice(
                invoice_no=arguments.get("invoice_no"),
                type=arguments.get("invoice_type", "普通发票"),
                amount=arguments.get("amount", 0.0),
                tax_amount=arguments.get("tax_amount", 0.0),
                issuer=arguments.get("issuer", ""),
                receiver=arguments.get("receiver", ""),
            )
        elif action == "verify":
            result = committee.verify_invoice(
                invoice_id=arguments.get("invoice_id", ""),
            )
        else:
            result = {"success": False, "message": f"不支持的发票操作: {action}", "data": None}

    elif name == "finance_tax":
        tax_type = arguments.get("tax_type", "vat")
        logger.info("税务计算: type=%s", tax_type)
        if tax_type == "vat":
            result = committee.calculate_vat(
                amount=arguments.get("amount", 0.0),
                tax_payer_type=arguments.get("tax_payer_type", "general"),
                is_service=arguments.get("is_service", False),
            )
        elif tax_type == "enterprise":
            result = committee.calculate_enterprise_tax(
                revenue=arguments.get("revenue", 0.0),
                cost=arguments.get("cost", 0.0),
                is_small_micro=arguments.get("is_small_micro", False),
            )
        elif tax_type == "personal":
            result = committee.calculate_personal_tax(
                monthly_income=arguments.get("monthly_income", 0.0),
                deduction=arguments.get("deduction", 5000.0),
                has_other_income=arguments.get("has_other_income", False),
            )
        else:
            result = {"success": False, "message": f"不支持的税种: {tax_type}", "data": None}

    return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]


# ══════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════

async def main() -> None:
    """启动 MCP Server（stdio 传输层）。"""
    logger.info("finance_server 启动中...")

    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )

    logger.info("finance_server 已关闭")


def _run_main() -> None:
    """同步入口（供 __main__ 块调用）。"""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("finance_server 收到中断信号，退出")
    except Exception as e:
        logger.error("finance_server 异常退出: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    _run_main()
