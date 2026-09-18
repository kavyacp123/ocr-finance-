"""
Finance SQL Tool
================

WHY:   Numerical calculations, aggregations, and tabular lookups must be
       performed deterministically in SQL, NEVER by an LLM.
       The LLM must never execute arbitrary SQL — only approved operations
       implemented in this tool.

WHERE: Called by QueryExecutor when step.tool == ToolName.SQL.

WHAT IT RECEIVES: Operation name + arguments + authenticated organization_id.

WHAT IT OUTPUTS:  ToolResult containing structured records + Evidence objects.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Set
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, or_

from app.database.session import SessionLocal
from app.database.models import (
    InvoiceModel,
    InvoiceLineItemModel,
    PurchaseOrderModel,
    PaymentModel,
    VendorModel,
    DocumentLinkModel,
)
from app.intelligence.schemas import (
    ToolName,
    ToolOperation,
    ToolResult,
    Evidence,
    EvidenceSourceType,
)
from app.intelligence.tools.base import BaseFinanceTool


class FinanceSQLTool(BaseFinanceTool):
    """
    Approved SQL operations for financial data querying.
    Strictly isolated by organization_id on every query.
    """

    tool_name = ToolName.SQL
    supported_operations: Set[ToolOperation] = {
        ToolOperation.GET_VENDOR_TOTAL_SPEND,
        ToolOperation.GET_MONTHLY_VENDOR_SPEND,
        ToolOperation.GET_VENDOR_INVOICE_COUNT,
        ToolOperation.GET_UNPAID_INVOICES,
        ToolOperation.GET_OVERDUE_INVOICES,
        ToolOperation.GET_INVOICE_BY_NUMBER,
        ToolOperation.GET_PURCHASE_ORDER,
        ToolOperation.GET_PAYMENTS_FOR_INVOICE,
        ToolOperation.GET_TOP_VENDORS,
        ToolOperation.GET_INVOICES_FOR_PERIOD,
        ToolOperation.GET_INVOICE_LINE_ITEMS,
        ToolOperation.COMPARE_VENDOR_SPEND,
    }

    def __init__(self, session_factory: Callable[[], Session] = SessionLocal):
        self.session_factory = session_factory

    async def _execute(
        self,
        step_id: str,
        operation: ToolOperation,
        arguments: dict,
        organization_id: str,
    ) -> ToolResult:
        db: Session = self.session_factory()
        try:
            if operation == ToolOperation.GET_VENDOR_TOTAL_SPEND:
                return self._get_vendor_total_spend(step_id, db, arguments, organization_id)
            elif operation == ToolOperation.GET_MONTHLY_VENDOR_SPEND:
                return self._get_monthly_vendor_spend(step_id, db, arguments, organization_id)
            elif operation == ToolOperation.GET_VENDOR_INVOICE_COUNT:
                return self._get_vendor_invoice_count(step_id, db, arguments, organization_id)
            elif operation == ToolOperation.GET_UNPAID_INVOICES:
                return self._get_unpaid_invoices(step_id, db, arguments, organization_id)
            elif operation == ToolOperation.GET_OVERDUE_INVOICES:
                return self._get_overdue_invoices(step_id, db, arguments, organization_id)
            elif operation == ToolOperation.GET_INVOICE_BY_NUMBER:
                return self._get_invoice_by_number(step_id, db, arguments, organization_id)
            elif operation == ToolOperation.GET_PURCHASE_ORDER:
                return self._get_purchase_order(step_id, db, arguments, organization_id)
            elif operation == ToolOperation.GET_PAYMENTS_FOR_INVOICE:
                return self._get_payments_for_invoice(step_id, db, arguments, organization_id)
            elif operation == ToolOperation.GET_TOP_VENDORS:
                return self._get_top_vendors(step_id, db, arguments, organization_id)
            elif operation == ToolOperation.GET_INVOICES_FOR_PERIOD:
                return self._get_invoices_for_period(step_id, db, arguments, organization_id)
            elif operation == ToolOperation.GET_INVOICE_LINE_ITEMS:
                return self._get_invoice_line_items(step_id, db, arguments, organization_id)
            elif operation == ToolOperation.COMPARE_VENDOR_SPEND:
                return self._compare_vendor_spend(step_id, db, arguments, organization_id)
            else:
                return ToolResult(
                    step_id=step_id,
                    tool=self.tool_name,
                    operation=operation,
                    success=False,
                    error=f"Unhandled SQL operation: {operation.value}",
                    execution_time_ms=0,
                )
        finally:
            db.close()

    # ── Handlers ──────────────────────────────────────────────────────────

    def _get_vendor_total_spend(
        self, step_id: str, db: Session, args: dict, org_id: str
    ) -> ToolResult:
        vendor_id = args.get("vendor_id")
        vendor_name = args.get("vendor_name")
        start_date = args.get("start_date")
        end_date = args.get("end_date")

        q = db.query(InvoiceModel).filter(InvoiceModel.organization_id == org_id)

        if vendor_id:
            q = q.filter(InvoiceModel.vendor_id == vendor_id)
        elif vendor_name:
            norm = vendor_name.lower().strip()
            q = q.filter(
                or_(
                    InvoiceModel.vendor_name_normalized.contains(norm),
                    InvoiceModel.vendor_name_raw.ilike(f"%{vendor_name}%"),
                )
            )

        if start_date:
            s_date = date.fromisoformat(start_date) if isinstance(start_date, str) else start_date
            q = q.filter(InvoiceModel.invoice_date >= s_date)
        if end_date:
            e_date = date.fromisoformat(end_date) if isinstance(end_date, str) else end_date
            q = q.filter(InvoiceModel.invoice_date <= e_date)

        total = q.with_entities(func.sum(InvoiceModel.total_amount)).scalar() or Decimal("0.00")
        count = q.count()

        # Evidence
        evidence = [
            Evidence(
                evidence_id=self._make_evidence_id(),
                source_type=EvidenceSourceType.DATABASE_AGGREGATION,
                vendor_id=vendor_id,
                metric={
                    "name": "total_spend",
                    "value": str(total),
                    "invoice_count": count,
                    "start_date": str(start_date) if start_date else None,
                    "end_date": str(end_date) if end_date else None,
                },
                confidence=1.0,
                source_operation=ToolOperation.GET_VENDOR_TOTAL_SPEND.value,
            )
        ]

        return ToolResult(
            step_id=step_id,
            tool=self.tool_name,
            operation=ToolOperation.GET_VENDOR_TOTAL_SPEND,
            success=True,
            data={
                "vendor_id": vendor_id,
                "vendor_name": vendor_name,
                "total_spend": str(total),
                "invoice_count": count,
                "currency": "INR",
                "start_date": str(start_date) if start_date else None,
                "end_date": str(end_date) if end_date else None,
            },
            evidence=evidence,
            record_count=count,
            execution_time_ms=0,
        )

    def _get_monthly_vendor_spend(
        self, step_id: str, db: Session, args: dict, org_id: str
    ) -> ToolResult:
        vendor_id = args.get("vendor_id")
        vendor_name = args.get("vendor_name")
        start_date = args.get("start_date")
        end_date = args.get("end_date")

        q = db.query(InvoiceModel).filter(InvoiceModel.organization_id == org_id)
        if vendor_id:
            q = q.filter(InvoiceModel.vendor_id == vendor_id)
        elif vendor_name:
            norm = vendor_name.lower().strip()
            q = q.filter(
                or_(
                    InvoiceModel.vendor_name_normalized.contains(norm),
                    InvoiceModel.vendor_name_raw.ilike(f"%{vendor_name}%"),
                )
            )

        if start_date:
            s_date = date.fromisoformat(start_date) if isinstance(start_date, str) else start_date
            q = q.filter(InvoiceModel.invoice_date >= s_date)
        if end_date:
            e_date = date.fromisoformat(end_date) if isinstance(end_date, str) else end_date
            q = q.filter(InvoiceModel.invoice_date <= e_date)

        invoices = q.all()
        monthly_map: Dict[str, Decimal] = {}
        for inv in invoices:
            if inv.invoice_date and inv.total_amount:
                m_key = inv.invoice_date.strftime("%Y-%m")
                monthly_map[m_key] = monthly_map.get(m_key, Decimal("0.00")) + inv.total_amount

        breakdown = [
            {"month": m, "spend": str(monthly_map[m])}
            for m in sorted(monthly_map.keys())
        ]

        evidence = [
            Evidence(
                evidence_id=self._make_evidence_id(),
                source_type=EvidenceSourceType.DATABASE_AGGREGATION,
                vendor_id=vendor_id,
                metric={"name": "monthly_spend_breakdown", "data": breakdown},
                confidence=1.0,
                source_operation=ToolOperation.GET_MONTHLY_VENDOR_SPEND.value,
            )
        ]

        return ToolResult(
            step_id=step_id,
            tool=self.tool_name,
            operation=ToolOperation.GET_MONTHLY_VENDOR_SPEND,
            success=True,
            data={"vendor_id": vendor_id, "monthly_spend": breakdown},
            evidence=evidence,
            record_count=len(breakdown),
            execution_time_ms=0,
        )

    def _get_vendor_invoice_count(
        self, step_id: str, db: Session, args: dict, org_id: str
    ) -> ToolResult:
        vendor_id = args.get("vendor_id")
        q = db.query(InvoiceModel).filter(InvoiceModel.organization_id == org_id)
        if vendor_id:
            q = q.filter(InvoiceModel.vendor_id == vendor_id)
        count = q.count()
        return ToolResult(
            step_id=step_id,
            tool=self.tool_name,
            operation=ToolOperation.GET_VENDOR_INVOICE_COUNT,
            success=True,
            data={"vendor_id": vendor_id, "invoice_count": count},
            record_count=count,
            execution_time_ms=0,
        )

    def _get_unpaid_invoices(
        self, step_id: str, db: Session, args: dict, org_id: str
    ) -> ToolResult:
        vendor_id = args.get("vendor_id")
        q = db.query(InvoiceModel).filter(
            InvoiceModel.organization_id == org_id,
            InvoiceModel.payment_status.in_(["UNPAID", "PENDING", "PARTIALLY_PAID"]),
        )
        if vendor_id:
            q = q.filter(InvoiceModel.vendor_id == vendor_id)

        invoices = q.order_by(desc(InvoiceModel.created_at)).limit(100).all()
        data = []
        evidence = []
        for inv in invoices:
            data.append({
                "invoice_id": inv.id,
                "invoice_number": inv.invoice_number,
                "vendor_name": inv.vendor_name_raw or inv.vendor_name_normalized,
                "total_amount": str(inv.total_amount),
                "due_date": inv.due_date.isoformat() if inv.due_date else None,
                "payment_status": inv.payment_status,
            })
            evidence.append(
                Evidence(
                    evidence_id=self._make_evidence_id(),
                    source_type=EvidenceSourceType.DATABASE_RECORD,
                    document_id=inv.document_id,
                    invoice_id=inv.id,
                    vendor_id=inv.vendor_id,
                    database_record={"invoice_number": inv.invoice_number, "status": inv.payment_status},
                    confidence=1.0,
                    source_operation=ToolOperation.GET_UNPAID_INVOICES.value,
                )
            )

        return ToolResult(
            step_id=step_id,
            tool=self.tool_name,
            operation=ToolOperation.GET_UNPAID_INVOICES,
            success=True,
            data={"unpaid_invoices": data, "count": len(data)},
            evidence=evidence,
            record_count=len(data),
            execution_time_ms=0,
        )

    def _get_overdue_invoices(
        self, step_id: str, db: Session, args: dict, org_id: str
    ) -> ToolResult:
        as_of = date.today()
        if args.get("as_of_date"):
            as_of = date.fromisoformat(args["as_of_date"])

        q = db.query(InvoiceModel).filter(
            InvoiceModel.organization_id == org_id,
            InvoiceModel.payment_status.in_(["UNPAID", "PENDING", "PARTIALLY_PAID"]),
            InvoiceModel.due_date < as_of,
        )
        invoices = q.order_by(InvoiceModel.due_date.asc()).limit(100).all()
        data = [
            {
                "invoice_id": inv.id,
                "invoice_number": inv.invoice_number,
                "vendor_name": inv.vendor_name_raw or inv.vendor_name_normalized,
                "total_amount": str(inv.total_amount),
                "due_date": inv.due_date.isoformat() if inv.due_date else None,
                "days_overdue": (as_of - inv.due_date).days if inv.due_date else 0,
            }
            for inv in invoices
        ]
        return ToolResult(
            step_id=step_id,
            tool=self.tool_name,
            operation=ToolOperation.GET_OVERDUE_INVOICES,
            success=True,
            data={"overdue_invoices": data, "count": len(data)},
            record_count=len(data),
            execution_time_ms=0,
        )

    def _get_invoice_by_number(
        self, step_id: str, db: Session, args: dict, org_id: str
    ) -> ToolResult:
        inv_num = args.get("invoice_number", "").strip()
        inv = (
            db.query(InvoiceModel)
            .filter(
                InvoiceModel.organization_id == org_id,
                func.lower(InvoiceModel.invoice_number) == inv_num.lower(),
            )
            .first()
        )
        if not inv:
            return ToolResult(
                step_id=step_id,
                tool=self.tool_name,
                operation=ToolOperation.GET_INVOICE_BY_NUMBER,
                success=False,
                error=f"Invoice '{inv_num}' not found",
                record_count=0,
                execution_time_ms=0,
            )

        data = {
            "invoice_id": inv.id,
            "document_id": inv.document_id,
            "invoice_number": inv.invoice_number,
            "vendor_name": inv.vendor_name_raw or inv.vendor_name_normalized,
            "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
            "due_date": inv.due_date.isoformat() if inv.due_date else None,
            "total_amount": str(inv.total_amount),
            "currency": inv.currency,
            "payment_status": inv.payment_status,
            "po_number": inv.po_number,
        }
        evidence = [
            Evidence(
                evidence_id=self._make_evidence_id(),
                source_type=EvidenceSourceType.DATABASE_RECORD,
                document_id=inv.document_id,
                invoice_id=inv.id,
                vendor_id=inv.vendor_id,
                database_record=data,
                confidence=1.0,
                source_operation=ToolOperation.GET_INVOICE_BY_NUMBER.value,
            )
        ]
        return ToolResult(
            step_id=step_id,
            tool=self.tool_name,
            operation=ToolOperation.GET_INVOICE_BY_NUMBER,
            success=True,
            data=data,
            evidence=evidence,
            record_count=1,
            execution_time_ms=0,
        )

    def _get_purchase_order(
        self, step_id: str, db: Session, args: dict, org_id: str
    ) -> ToolResult:
        po_num = args.get("po_number", "").strip()
        po_id = args.get("po_id")
        q = db.query(PurchaseOrderModel).filter(PurchaseOrderModel.organization_id == org_id)
        if po_id:
            po = q.filter(PurchaseOrderModel.id == po_id).first()
        elif po_num:
            po = q.filter(func.lower(PurchaseOrderModel.po_number) == po_num.lower()).first()
        else:
            po = None

        if not po:
            return ToolResult(
                step_id=step_id,
                tool=self.tool_name,
                operation=ToolOperation.GET_PURCHASE_ORDER,
                success=False,
                error=f"Purchase order '{po_num or po_id}' not found",
                record_count=0,
                execution_time_ms=0,
            )

        data = {
            "po_id": po.id,
            "po_number": po.po_number,
            "vendor_name": po.vendor_name_raw or po.vendor_name_normalized,
            "po_date": po.po_date.isoformat() if po.po_date else None,
            "total_amount": str(po.total_amount),
            "status": po.status,
        }
        evidence = [
            Evidence(
                evidence_id=self._make_evidence_id(),
                source_type=EvidenceSourceType.DATABASE_RECORD,
                document_id=po.document_id,
                po_id=po.id,
                database_record=data,
                confidence=1.0,
                source_operation=ToolOperation.GET_PURCHASE_ORDER.value,
            )
        ]
        return ToolResult(
            step_id=step_id,
            tool=self.tool_name,
            operation=ToolOperation.GET_PURCHASE_ORDER,
            success=True,
            data=data,
            evidence=evidence,
            record_count=1,
            execution_time_ms=0,
        )

    def _get_payments_for_invoice(
        self, step_id: str, db: Session, args: dict, org_id: str
    ) -> ToolResult:
        invoice_id = args.get("invoice_id")
        invoice_number = args.get("invoice_number")

        inv = None
        if invoice_id:
            inv = db.query(InvoiceModel).filter(
                InvoiceModel.id == invoice_id,
                InvoiceModel.organization_id == org_id,
            ).first()
        elif invoice_number:
            inv = db.query(InvoiceModel).filter(
                InvoiceModel.invoice_number == invoice_number,
                InvoiceModel.organization_id == org_id,
            ).first()

        if not inv:
            return ToolResult(
                step_id=step_id,
                tool=self.tool_name,
                operation=ToolOperation.GET_PAYMENTS_FOR_INVOICE,
                success=False,
                error="Invoice not found",
                record_count=0,
                execution_time_ms=0,
            )

        # Look in DocumentLinkModel for links to Payment
        links = db.query(DocumentLinkModel).filter(
            DocumentLinkModel.organization_id == org_id,
            DocumentLinkModel.source_id == inv.id,
            DocumentLinkModel.target_type == "payment",
        ).all()

        payment_ids = [l.target_id for l in links if l.target_id]
        payments = db.query(PaymentModel).filter(
            PaymentModel.id.in_(payment_ids),
            PaymentModel.organization_id == org_id,
        ).all()

        pay_data = [
            {
                "payment_id": p.id,
                "payment_reference": p.payment_reference,
                "amount": str(p.amount),
                "payment_date": p.payment_date.isoformat() if p.payment_date else None,
                "status": p.status,
            }
            for p in payments
        ]

        evidence = [
            Evidence(
                evidence_id=self._make_evidence_id(),
                source_type=EvidenceSourceType.DATABASE_RECORD,
                payment_id=p.id,
                invoice_id=inv.id,
                database_record={"payment_reference": p.payment_reference, "amount": str(p.amount)},
                confidence=1.0,
                source_operation=ToolOperation.GET_PAYMENTS_FOR_INVOICE.value,
            )
            for p in payments
        ]

        return ToolResult(
            step_id=step_id,
            tool=self.tool_name,
            operation=ToolOperation.GET_PAYMENTS_FOR_INVOICE,
            success=True,
            data={"invoice_number": inv.invoice_number, "payments": pay_data},
            evidence=evidence,
            record_count=len(pay_data),
            execution_time_ms=0,
        )

    def _get_top_vendors(
        self, step_id: str, db: Session, args: dict, org_id: str
    ) -> ToolResult:
        limit = args.get("limit", 5)
        start_date = args.get("start_date")
        end_date = args.get("end_date")

        q = db.query(
            InvoiceModel.vendor_id,
            InvoiceModel.vendor_name_raw,
            InvoiceModel.vendor_name_normalized,
            func.sum(InvoiceModel.total_amount).label("total_spend"),
            func.count(InvoiceModel.id).label("invoice_count"),
        ).filter(InvoiceModel.organization_id == org_id)

        if start_date:
            s_date = date.fromisoformat(start_date) if isinstance(start_date, str) else start_date
            q = q.filter(InvoiceModel.invoice_date >= s_date)
        if end_date:
            e_date = date.fromisoformat(end_date) if isinstance(end_date, str) else end_date
            q = q.filter(InvoiceModel.invoice_date <= e_date)

        results = (
            q.group_by(
                InvoiceModel.vendor_id,
                InvoiceModel.vendor_name_raw,
                InvoiceModel.vendor_name_normalized,
            )
            .order_by(desc("total_spend"))
            .limit(limit)
            .all()
        )

        top_vendors = [
            {
                "vendor_id": r.vendor_id,
                "vendor_name": r.vendor_name_raw or r.vendor_name_normalized or "Unknown",
                "total_spend": str(r.total_spend or 0),
                "invoice_count": r.invoice_count,
            }
            for r in results
        ]

        evidence = [
            Evidence(
                evidence_id=self._make_evidence_id(),
                source_type=EvidenceSourceType.DATABASE_AGGREGATION,
                metric={"name": "top_vendors", "data": top_vendors},
                confidence=1.0,
                source_operation=ToolOperation.GET_TOP_VENDORS.value,
            )
        ]

        return ToolResult(
            step_id=step_id,
            tool=self.tool_name,
            operation=ToolOperation.GET_TOP_VENDORS,
            success=True,
            data={"top_vendors": top_vendors},
            evidence=evidence,
            record_count=len(top_vendors),
            execution_time_ms=0,
        )

    def _get_invoices_for_period(
        self, step_id: str, db: Session, args: dict, org_id: str
    ) -> ToolResult:
        start_date = args.get("start_date")
        end_date = args.get("end_date")
        vendor_id = args.get("vendor_id")
        limit = args.get("limit", 100)

        q = db.query(InvoiceModel).filter(InvoiceModel.organization_id == org_id)
        if vendor_id:
            q = q.filter(InvoiceModel.vendor_id == vendor_id)
        if start_date:
            s_date = date.fromisoformat(start_date) if isinstance(start_date, str) else start_date
            q = q.filter(InvoiceModel.invoice_date >= s_date)
        if end_date:
            e_date = date.fromisoformat(end_date) if isinstance(end_date, str) else end_date
            q = q.filter(InvoiceModel.invoice_date <= e_date)

        invoices = q.order_by(desc(InvoiceModel.invoice_date)).limit(limit).all()
        data = [
            {
                "invoice_id": inv.id,
                "invoice_number": inv.invoice_number,
                "vendor_name": inv.vendor_name_raw or inv.vendor_name_normalized,
                "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else None,
                "total_amount": str(inv.total_amount),
            }
            for inv in invoices
        ]
        return ToolResult(
            step_id=step_id,
            tool=self.tool_name,
            operation=ToolOperation.GET_INVOICES_FOR_PERIOD,
            success=True,
            data={"invoices": data, "count": len(data)},
            record_count=len(data),
            execution_time_ms=0,
        )

    def _get_invoice_line_items(
        self, step_id: str, db: Session, args: dict, org_id: str
    ) -> ToolResult:
        invoice_id = args.get("invoice_id")
        invoice_ids = args.get("invoice_ids", [])
        if invoice_id and invoice_id not in invoice_ids:
            invoice_ids.append(invoice_id)

        q = db.query(InvoiceLineItemModel).filter(
            InvoiceLineItemModel.organization_id == org_id,
            InvoiceLineItemModel.invoice_id.in_(invoice_ids),
        )
        items = q.all()
        data = [
            {
                "line_id": itm.id,
                "invoice_id": itm.invoice_id,
                "line_number": itm.line_number,
                "description": itm.description,
                "quantity": str(itm.quantity) if itm.quantity else "1",
                "unit_price": str(itm.unit_price) if itm.unit_price else "0.00",
                "total": str(itm.total) if itm.total else "0.00",
            }
            for itm in items
        ]
        return ToolResult(
            step_id=step_id,
            tool=self.tool_name,
            operation=ToolOperation.GET_INVOICE_LINE_ITEMS,
            success=True,
            data={"line_items": data},
            record_count=len(data),
            execution_time_ms=0,
        )

    def _compare_vendor_spend(
        self, step_id: str, db: Session, args: dict, org_id: str
    ) -> ToolResult:
        vendor_id = args.get("vendor_id")
        p_a_start = args.get("period_a_start")
        p_a_end = args.get("period_a_end")
        p_b_start = args.get("period_b_start")
        p_b_end = args.get("period_b_end")

        def _sum_period(s_str, e_str):
            q = db.query(func.sum(InvoiceModel.total_amount)).filter(
                InvoiceModel.organization_id == org_id
            )
            if vendor_id:
                q = q.filter(InvoiceModel.vendor_id == vendor_id)
            if s_str:
                q = q.filter(InvoiceModel.invoice_date >= date.fromisoformat(s_str))
            if e_str:
                q = q.filter(InvoiceModel.invoice_date <= date.fromisoformat(e_str))
            return q.scalar() or Decimal("0.00")

        spend_a = _sum_period(p_a_start, p_a_end)
        spend_b = _sum_period(p_b_start, p_b_end)
        diff = spend_b - spend_a
        pct_change = ((diff / spend_a) * 100) if spend_a > 0 else Decimal("0.00")

        evidence = [
            Evidence(
                evidence_id=self._make_evidence_id(),
                source_type=EvidenceSourceType.DATABASE_AGGREGATION,
                vendor_id=vendor_id,
                metric={
                    "period_a_spend": str(spend_a),
                    "period_b_spend": str(spend_b),
                    "diff": str(diff),
                    "pct_change": str(round(pct_change, 2)),
                },
                confidence=1.0,
                source_operation=ToolOperation.COMPARE_VENDOR_SPEND.value,
            )
        ]

        return ToolResult(
            step_id=step_id,
            tool=self.tool_name,
            operation=ToolOperation.COMPARE_VENDOR_SPEND,
            success=True,
            data={
                "vendor_id": vendor_id,
                "period_a_spend": str(spend_a),
                "period_b_spend": str(spend_b),
                "absolute_difference": str(diff),
                "percentage_change": str(round(pct_change, 2)),
            },
            evidence=evidence,
            record_count=2,
            execution_time_ms=0,
        )
