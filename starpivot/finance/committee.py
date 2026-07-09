"""财务委员会 — Finance Committee。

财务内部工具集：
  - 报表生成 (finance_report)
  - 审计查询 (finance_audit)
  - 预算管理 (finance_budget)
  - 发票管理 (finance_invoice)
  - 税务计算 (finance_tax)
"""

from __future__ import annotations

import csv
import io
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════════════════════════════
# 数据模型
# ════════════════════════════════════════════════════════════════════


@dataclass
class FinanceRecord:
    """财务记录。"""
    id: str = ""
    type: str = ""           # income / expense / transfer
    amount: float = 0.0
    category: str = ""       # 分类
    description: str = ""
    date: str = ""
    created_at: str = ""


@dataclass
class BudgetItem:
    """预算项。"""
    id: str = ""
    department: str = ""
    category: str = ""
    total_amount: float = 0.0
    used_amount: float = 0.0
    fiscal_year: int = 2026
    status: str = "active"   # active / frozen / closed


@dataclass
class InvoiceRecord:
    """发票记录。"""
    id: str = ""
    invoice_no: str = ""
    type: str = ""           # 增值税专用发票 / 普通发票 / 电子发票
    amount: float = 0.0
    tax_amount: float = 0.0
    issuer: str = ""
    receiver: str = ""
    status: str = "pending"  # pending / verified / paid / cancelled
    date: str = ""


@dataclass
class AuditEntry:
    """审计条目。"""
    id: str = ""
    action: str = ""
    operator: str = ""
    target_type: str = ""
    target_id: str = ""
    details: str = ""
    timestamp: str = ""


# ════════════════════════════════════════════════════════════════════
# 报表生成器
# ════════════════════════════════════════════════════════════════════


class ReportGenerator:
    """财务报表生成器。"""

    def __init__(self) -> None:
        self._records: list[FinanceRecord] = []

    def add_record(self, record: FinanceRecord) -> None:
        self._records.append(record)

    def load_records(self, records: list[FinanceRecord]) -> None:
        self._records = records

    def generate_income_statement(
        self,
        start_date: str = "",
        end_date: str = "",
        format: str = "json",
    ) -> dict:
        """生成损益表 / 利润表。

        Args:
            start_date: 开始日期 (YYYY-MM-DD)。
            end_date: 结束日期 (YYYY-MM-DD)。
            format: 输出格式 (json / csv / text)。

        Returns:
            dict: {success, message, data: {report, ...}}
        """
        filtered = self._filter_by_date(start_date, end_date)
        total_income = sum(r.amount for r in filtered if r.type == "income")
        total_expense = sum(r.amount for r in filtered if r.type == "expense")
        net_profit = total_income - total_expense

        # 按类别汇总
        by_category: dict[str, float] = {}
        for r in filtered:
            by_category[r.category] = by_category.get(r.category, 0.0) + r.amount

        report = {
            "title": "损益表",
            "period": f"{start_date or '开始'} ~ {end_date or '至今'}",
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "summary": {
                "total_income": round(total_income, 2),
                "total_expense": round(total_expense, 2),
                "net_profit": round(net_profit, 2),
                "record_count": len(filtered),
            },
            "by_category": {k: round(v, 2) for k, v in by_category.items()},
        }

        if format == "csv":
            return self._to_csv(report)
        elif format == "text":
            return self._to_text(report)

        return {"success": True, "message": "损益表生成成功", "data": report}

    def generate_balance_sheet(self, date: str = "") -> dict:
        """生成资产负债表（简版）。

        Args:
            date: 截止日期 (YYYY-MM-DD)。

        Returns:
            dict: 资产负债表数据。
        """
        filtered = self._filter_by_date("", date)
        total_assets = sum(r.amount for r in filtered if r.type == "income")
        total_liabilities = sum(r.amount for r in filtered if r.type == "expense")
        equity = total_assets - total_liabilities

        report = {
            "title": "资产负债表（简版）",
            "as_of_date": date or time.strftime("%Y-%m-%d"),
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "assets": round(total_assets, 2),
            "liabilities": round(total_liabilities, 2),
            "equity": round(equity, 2),
            "record_count": len(filtered),
        }
        return {"success": True, "message": "资产负债表生成成功", "data": report}

    def generate_cashflow(self, start_date: str = "", end_date: str = "") -> dict:
        """生成现金流量表。

        Returns:
            dict: 现金流量表数据。
        """
        filtered = self._filter_by_date(start_date, end_date)
        operating_in = sum(r.amount for r in filtered if r.type == "income" and "经营" in r.category)
        operating_out = sum(r.amount for r in filtered if r.type == "expense" and "经营" in r.category)
        investing_in = sum(r.amount for r in filtered if r.type == "income" and "投资" in r.category)
        investing_out = sum(r.amount for r in filtered if r.type == "expense" and "投资" in r.category)

        report = {
            "title": "现金流量表（简版）",
            "period": f"{start_date or '开始'} ~ {end_date or '至今'}",
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "operating_net": round(operating_in - operating_out, 2),
            "investing_net": round(investing_in - investing_out, 2),
            "net_change": round((operating_in - operating_out) + (investing_in - investing_out), 2),
        }
        return {"success": True, "message": "现金流量表生成成功", "data": report}

    # ── 内部工具 ──────────────────────────

    def _filter_by_date(self, start: str = "", end: str = "") -> list[FinanceRecord]:
        if not start and not end:
            return self._records
        filtered = self._records
        if start:
            filtered = [r for r in filtered if r.date >= start]
        if end:
            filtered = [r for r in filtered if r.date <= end]
        return filtered

    def _to_csv(self, report: dict) -> dict:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["指标", "值"])
        for key, value in report.get("summary", {}).items():
            writer.writerow([key, value])
        writer.writerow([])
        writer.writerow(["类别", "金额"])
        for cat, amt in report.get("by_category", {}).items():
            writer.writerow([cat, amt])
        csv_content = output.getvalue()
        return {"success": True, "message": "CSV 报表生成成功", "data": {"csv": csv_content}}

    def _to_text(self, report: dict) -> dict:
        lines = [
            f"=== {report.get('title', '报表')} ===",
            f"期间: {report.get('period', '')}",
            f"生成时间: {report.get('generated_at', '')}",
            "---",
        ]
        for key, value in report.get("summary", {}).items():
            lines.append(f"{key}: {value}")
        lines.append("--- 按类别 ---")
        for cat, amt in report.get("by_category", {}).items():
            lines.append(f"  {cat}: {amt}")
        return {"success": True, "message": "文本报表生成成功", "data": {"text": "\n".join(lines)}}


# ════════════════════════════════════════════════════════════════════
# 审计查询
# ════════════════════════════════════════════════════════════════════


class AuditQuery:
    """审计记录查询器。"""

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []
        self._load_sample_data()

    def _load_sample_data(self) -> None:
        """加载样本审计数据。"""
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        self._entries = [
            AuditEntry(id="audit_001", action="budget_approve", operator="admin",
                       target_type="budget", target_id="budget_001",
                       details="审批通过 2026 年 Q2 市场部预算", timestamp=now),
            AuditEntry(id="audit_002", action="invoice_verify", operator="finance_wang",
                       target_type="invoice", target_id="inv_001",
                       details="发票验证通过 - 华为云服务费", timestamp=now),
            AuditEntry(id="audit_003", action="payment_execute", operator="system",
                       target_type="payment", target_id="pay_001",
                       details="支付执行 - 阿里云 ￥12,800.00", timestamp=now),
        ]

    def add_entry(self, entry: AuditEntry) -> None:
        """添加审计记录。"""
        entry.id = entry.id or f"audit_{uuid.uuid4().hex[:8]}"
        entry.timestamp = entry.timestamp or time.strftime("%Y-%m-%d %H:%M:%S")
        self._entries.append(entry)

    def query(
        self,
        action: str = "",
        operator: str = "",
        target_type: str = "",
        start_date: str = "",
        end_date: str = "",
        keyword: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """查询审计记录。

        Args:
            action: 按操作类型筛选。
            operator: 按操作人筛选。
            target_type: 按目标类型筛选。
            start_date/end_date: 时间范围。
            keyword: 关键词搜索。
            limit/offset: 分页。

        Returns:
            dict: {success, message, data: {list, total, ...}}
        """
        filtered = self._entries
        if action:
            filtered = [e for e in filtered if action in e.action]
        if operator:
            filtered = [e for e in filtered if operator in e.operator]
        if target_type:
            filtered = [e for e in filtered if target_type in e.target_type]
        if keyword:
            filtered = [e for e in filtered if keyword.lower() in e.details.lower()]
        if start_date:
            filtered = [e for e in filtered if e.timestamp >= start_date]
        if end_date:
            filtered = [e for e in filtered if e.timestamp <= end_date]

        total = len(filtered)
        paged = filtered[offset:offset + limit]
        return {
            "success": True,
            "message": f"查询到 {total} 条记录",
            "data": {
                "list": [
                    {
                        "id": e.id,
                        "action": e.action,
                        "operator": e.operator,
                        "target_type": e.target_type,
                        "target_id": e.target_id,
                        "details": e.details,
                        "timestamp": e.timestamp,
                    }
                    for e in paged
                ],
                "total": total,
                "offset": offset,
                "limit": limit,
            },
        }


# ════════════════════════════════════════════════════════════════════
# 预算管理
# ════════════════════════════════════════════════════════════════════


class BudgetManager:
    """预算管理器。"""

    def __init__(self) -> None:
        self._budgets: dict[str, BudgetItem] = {}
        self._load_sample_data()

    def _load_sample_data(self) -> None:
        items = [
            BudgetItem(id="budget_001", department="技术部", category="云服务",
                       total_amount=500000, used_amount=280000, fiscal_year=2026),
            BudgetItem(id="budget_002", department="市场部", category="推广",
                       total_amount=300000, used_amount=120000, fiscal_year=2026),
            BudgetItem(id="budget_003", department="财务部", category="办公",
                       total_amount=50000, used_amount=18000, fiscal_year=2026),
        ]
        for item in items:
            self._budgets[item.id] = item

    def list_budgets(self, department: str = "", fiscal_year: int = 0) -> dict:
        """列出预算项。

        Returns:
            dict: {success, message, data: {list, summary}}
        """
        filtered = list(self._budgets.values())
        if department:
            filtered = [b for b in filtered if department in b.department]
        if fiscal_year:
            filtered = [b for b in filtered if b.fiscal_year == fiscal_year]

        total_budget = sum(b.total_amount for b in filtered)
        total_used = sum(b.used_amount for b in filtered)
        return {
            "success": True,
            "message": f"共 {len(filtered)} 个预算项",
            "data": {
                "list": [
                    {
                        "id": b.id,
                        "department": b.department,
                        "category": b.category,
                        "total_amount": b.total_amount,
                        "used_amount": b.used_amount,
                        "remaining": round(b.total_amount - b.used_amount, 2),
                        "usage_rate": f"{round(b.used_amount / b.total_amount * 100, 1)}%" if b.total_amount else "0%",
                        "fiscal_year": b.fiscal_year,
                        "status": b.status,
                    }
                    for b in filtered
                ],
                "summary": {
                    "total_budget": total_budget,
                    "total_used": total_used,
                    "total_remaining": round(total_budget - total_used, 2),
                    "overall_usage": f"{round(total_used / total_budget * 100, 1)}%" if total_budget else "0%",
                },
            },
        }

    def create_budget(self, department: str, category: str,
                      total_amount: float, fiscal_year: int = 2026) -> dict:
        """创建新预算项。"""
        item = BudgetItem(
            id=f"budget_{uuid.uuid4().hex[:8]}",
            department=department,
            category=category,
            total_amount=total_amount,
            fiscal_year=fiscal_year,
        )
        self._budgets[item.id] = item
        logger.info("预算创建: %s %s %s %.2f", department, category, fiscal_year, total_amount)
        return {
            "success": True,
            "message": "预算创建成功",
            "data": {
                "id": item.id,
                "department": department,
                "category": category,
                "total_amount": total_amount,
                "fiscal_year": fiscal_year,
            },
        }

    def update_budget(self, budget_id: str, **kwargs: Any) -> dict:
        """更新预算项。"""
        item = self._budgets.get(budget_id)
        if not item:
            return {"success": False, "message": f"预算项 {budget_id} 不存在", "data": None}
        for key, value in kwargs.items():
            if hasattr(item, key):
                setattr(item, key, value)
        return {
            "success": True,
            "message": "预算更新成功",
            "data": {"id": budget_id, "updated_fields": list(kwargs.keys())},
        }


# ════════════════════════════════════════════════════════════════════
# 发票管理
# ════════════════════════════════════════════════════════════════════


class InvoiceManager:
    """发票管理器。"""

    def __init__(self) -> None:
        self._invoices: dict[str, InvoiceRecord] = {}
        self._load_sample_data()

    def _load_sample_data(self) -> None:
        now = time.strftime("%Y-%m-%d")
        items = [
            InvoiceRecord(id="inv_001", invoice_no="4400245678", type="增值税专用发票",
                          amount=12800, tax_amount=1664, issuer="华为云",
                          receiver="星枢科技", status="verified", date=now),
            InvoiceRecord(id="inv_002", invoice_no="4400245679", type="普通发票",
                          amount=3600, tax_amount=0, issuer="阿里云",
                          receiver="星枢科技", status="paid", date=now),
        ]
        for item in items:
            self._invoices[item.id] = item

    def list_invoices(self, status: str = "", issuer: str = "",
                       start_date: str = "", end_date: str = "",
                       limit: int = 50, offset: int = 0) -> dict:
        """列出发票。

        Returns:
            dict: {success, message, data: {list, total, summary}}
        """
        filtered = list(self._invoices.values())
        if status:
            filtered = [i for i in filtered if i.status == status]
        if issuer:
            filtered = [i for i in filtered if issuer.lower() in i.issuer.lower()]
        if start_date:
            filtered = [i for i in filtered if i.date >= start_date]
        if end_date:
            filtered = [i for i in filtered if i.date <= end_date]

        total = len(filtered)
        total_amount = sum(i.amount for i in filtered)
        total_tax = sum(i.tax_amount for i in filtered)
        paged = filtered[offset:offset + limit]

        return {
            "success": True,
            "message": f"共 {total} 张发票",
            "data": {
                "list": [
                    {
                        "id": i.id,
                        "invoice_no": i.invoice_no,
                        "type": i.type,
                        "amount": i.amount,
                        "tax_amount": i.tax_amount,
                        "total": round(i.amount + i.tax_amount, 2),
                        "issuer": i.issuer,
                        "receiver": i.receiver,
                        "status": i.status,
                        "date": i.date,
                    }
                    for i in paged
                ],
                "total": total,
                "total_amount": round(total_amount, 2),
                "total_tax": round(total_tax, 2),
            },
        }

    def create_invoice(self, **kwargs: Any) -> dict:
        """创建（录入）发票。"""
        inv = InvoiceRecord(
            id=f"inv_{uuid.uuid4().hex[:8]}",
            invoice_no=kwargs.get("invoice_no", f"INV{int(time.time())}"),
            type=kwargs.get("type", "普通发票"),
            amount=kwargs.get("amount", 0.0),
            tax_amount=kwargs.get("tax_amount", 0.0),
            issuer=kwargs.get("issuer", ""),
            receiver=kwargs.get("receiver", ""),
            status="pending",
            date=kwargs.get("date", time.strftime("%Y-%m-%d")),
        )
        self._invoices[inv.id] = inv
        return {
            "success": True,
            "message": f"发票 {inv.invoice_no} 录入成功",
            "data": {"id": inv.id, "invoice_no": inv.invoice_no, "status": inv.status},
        }

    def verify_invoice(self, invoice_id: str) -> dict:
        """核验发票。"""
        inv = self._invoices.get(invoice_id)
        if not inv:
            return {"success": False, "message": f"发票 {invoice_id} 不存在", "data": None}
        inv.status = "verified"
        return {
            "success": True,
            "message": f"发票 {inv.invoice_no} 核验通过",
            "data": {"id": invoice_id, "status": "verified"},
        }


# ════════════════════════════════════════════════════════════════════
# 税务计算
# ════════════════════════════════════════════════════════════════════


class TaxCalculator:
    """税务计算器。

    支持：
      - 增值税计算（一般纳税人 / 小规模）
      - 企业所得税估算
      - 个人所得税（工资薪金 / 劳务报酬）
    """

    # 税率表
    VAT_RATES = {
        "general": 0.13,      # 一般纳税人（商品）
        "general_service": 0.06,  # 一般纳税人（服务）
        "small_scale": 0.03,  # 小规模纳税人
    }
    ENTERPRISE_RATE = 0.25   # 企业所得税 25%
    ENTERPRISE_SMALL_RATE = 0.05  # 小型微利企业优惠税率

    def calculate_vat(
        self,
        amount: float,
        tax_payer_type: str = "general",
        is_service: bool = False,
    ) -> dict:
        """计算增值税。

        Args:
            amount: 不含税金额。
            tax_payer_type: 纳税人类型 (general / general_service / small_scale)。
            is_service: 是否为服务（一般纳税人服务税率 6%）。

        Returns:
            dict: {success, data: {tax_rate, tax_amount, total_amount, ...}}
        """
        if tax_payer_type == "general":
            rate = self.VAT_RATES["general_service"] if is_service else self.VAT_RATES["general"]
        else:
            rate = self.VAT_RATES.get(tax_payer_type, 0.03)

        tax_amount = round(amount * rate, 2)
        total = round(amount + tax_amount, 2)
        return {
            "success": True,
            "message": f"增值税计算完成（税率 {rate*100}%）",
            "data": {
                "base_amount": amount,
                "tax_payer_type": tax_payer_type,
                "tax_rate": rate,
                "tax_amount": tax_amount,
                "total_amount": total,
            },
        }

    def calculate_enterprise_tax(
        self,
        revenue: float,
        cost: float,
        is_small_micro: bool = False,
    ) -> dict:
        """估算企业所得税。

        Args:
            revenue: 营业收入。
            cost: 营业成本+费用。
            is_small_micro: 是否为小型微利企业。

        Returns:
            dict: 税负估算。
        """
        profit = revenue - cost
        if profit <= 0:
            return {
                "success": True,
                "message": "企业处于亏损状态，无需缴纳所得税",
                "data": {
                    "revenue": revenue,
                    "cost": cost,
                    "profit": profit,
                    "tax_rate": 0,
                    "tax_amount": 0,
                    "profit_after_tax": profit,
                },
            }

        rate = self.ENTERPRISE_SMALL_RATE if is_small_micro else self.ENTERPRISE_RATE
        tax = round(profit * rate, 2)
        return {
            "success": True,
            "message": f"企业所得税估算完成（税率 {rate*100}%）",
            "data": {
                "revenue": revenue,
                "cost": cost,
                "profit": round(profit, 2),
                "tax_rate": rate,
                "tax_amount": tax,
                "profit_after_tax": round(profit - tax, 2),
            },
        }

    def calculate_personal_tax(
        self,
        monthly_income: float,
        deduction: float = 5000,
        has_other_income: bool = False,
    ) -> dict:
        """计算当月个人所得税（工资薪金，简易估算）。

        Args:
            monthly_income: 月收入（元）。
            deduction: 专项扣除+起征点（默认 5000）。
            has_other_income: 是否有其他收入。

        Returns:
            dict: 个税估算。
        """
        taxable = max(0, monthly_income - deduction)
        # 简易 7 级累进
        if taxable <= 3000:
            rate, quick_deduct = 0.03, 0
        elif taxable <= 12000:
            rate, quick_deduct = 0.10, 210
        elif taxable <= 25000:
            rate, quick_deduct = 0.20, 1410
        elif taxable <= 35000:
            rate, quick_deduct = 0.25, 2660
        elif taxable <= 55000:
            rate, quick_deduct = 0.30, 4410
        elif taxable <= 80000:
            rate, quick_deduct = 0.35, 7160
        else:
            rate, quick_deduct = 0.45, 15160

        tax = round(taxable * rate - quick_deduct, 2)
        net_income = round(monthly_income - tax, 2)
        return {
            "success": True,
            "message": "个人所得税估算完成",
            "data": {
                "monthly_income": monthly_income,
                "deduction": deduction,
                "taxable_income": taxable,
                "tax_rate": rate,
                "quick_deduct": quick_deduct,
                "tax_amount": max(0, tax),
                "net_income": net_income if tax >= 0 else monthly_income,
            },
        }


# ════════════════════════════════════════════════════════════════════
# 财务委员会
# ════════════════════════════════════════════════════════════════════


class FinanceCommittee:
    """财务委员会 — 统一入口。

    组合全部财务工具，通过 MCP Server 暴露。
    """

    def __init__(self) -> None:
        self.report_generator = ReportGenerator()
        self.audit_query = AuditQuery()
        self.budget_manager = BudgetManager()
        self.invoice_manager = InvoiceManager()
        self.tax_calculator = TaxCalculator()

        # 初始化样本数据
        self._load_sample_records()

    def _load_sample_records(self) -> None:
        sample_records = [
            FinanceRecord(id="rec_001", type="income", amount=500000,
                          category="营业收入", description="Q1 软件销售",
                          date="2026-01-15"),
            FinanceRecord(id="rec_002", type="expense", amount=120000,
                          category="经营成本", description="云服务器费用",
                          date="2026-01-20"),
            FinanceRecord(id="rec_003", type="expense", amount=80000,
                          category="经营成本", description="人力成本",
                          date="2026-02-01"),
            FinanceRecord(id="rec_004", type="income", amount=300000,
                          category="营业收入", description="Q2 预收款",
                          date="2026-03-01"),
        ]
        for r in sample_records:
            self.report_generator.add_record(r)

    # ── 各工具入口 ────────────────────────

    def generate_report(self, report_type: str = "income",
                        start_date: str = "", end_date: str = "",
                        format: str = "json") -> dict:
        """生成财务报表。"""
        if report_type == "income":
            return self.report_generator.generate_income_statement(start_date, end_date, format)
        elif report_type == "balance":
            return self.report_generator.generate_balance_sheet(end_date or start_date)
        elif report_type == "cashflow":
            return self.report_generator.generate_cashflow(start_date, end_date)
        return {"success": False, "message": f"不支持的报表类型: {report_type}", "data": None}

    def audit_query_func(self, **kwargs: Any) -> dict:
        """查询审计记录。"""
        return self.audit_query.query(**kwargs)

    def list_budgets(self, **kwargs: Any) -> dict:
        """列出预算。"""
        return self.budget_manager.list_budgets(**kwargs)

    def create_budget(self, **kwargs: Any) -> dict:
        """创建预算。"""
        return self.budget_manager.create_budget(**kwargs)

    def update_budget(self, **kwargs: Any) -> dict:
        """更新预算。"""
        return self.budget_manager.update_budget(**kwargs)

    def list_invoices(self, **kwargs: Any) -> dict:
        """列出发票。"""
        return self.invoice_manager.list_invoices(**kwargs)

    def create_invoice(self, **kwargs: Any) -> dict:
        """创建发票。"""
        return self.invoice_manager.create_invoice(**kwargs)

    def verify_invoice(self, invoice_id: str) -> dict:
        """核验发票。"""
        return self.invoice_manager.verify_invoice(invoice_id)

    def calculate_vat(self, **kwargs: Any) -> dict:
        """计算增值税。"""
        return self.tax_calculator.calculate_vat(**kwargs)

    def calculate_enterprise_tax(self, **kwargs: Any) -> dict:
        """计算企业所得税。"""
        return self.tax_calculator.calculate_enterprise_tax(**kwargs)

    def calculate_personal_tax(self, **kwargs: Any) -> dict:
        """计算个人所得税。"""
        return self.tax_calculator.calculate_personal_tax(**kwargs)
