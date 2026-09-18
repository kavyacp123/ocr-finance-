"""
Grounded Answer Generator
=========================

WHY:   The system must NEVER produce unsupported financial claims.
       The answer generator receives ONLY the query plan, tool outputs, and evidence.
       It uses deterministic synthesis first, ensuring that financial facts, numbers,
       and relationships are exactly as retrieved by the tools.
       If information is missing, it states it explicitly under limitations.

WHERE: Final step before returning FinanceAnswer to the user.

WHAT IT RECEIVES: Question + QueryPlan + List[ToolResult] + List[Evidence].

WHAT IT OUTPUTS:  A structured FinanceAnswer.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional

from app.intelligence.schemas import (
    FinanceAnswer,
    QueryPlan,
    QueryIntent,
    ToolResult,
    Evidence,
    ToolOperation,
)
from app.intelligence.confidence import ConfidenceCalculator
from app.intelligence.reasoner import FinanceReasoner


class AnswerGenerator:
    """
    Synthesizes factual, grounded answers strictly from tool outputs and evidence.
    """

    @classmethod
    def generate(
        cls,
        question: str,
        plan: QueryPlan,
        tool_results: List[ToolResult],
        evidence: List[Evidence],
    ) -> FinanceAnswer:
        # Check for tool failures
        limitations: List[str] = list(plan.ambiguities)
        failed_tools = [r for r in tool_results if not r.success]
        for f in failed_tools:
            limitations.append(f"{f.tool.value} operation '{f.operation.value}' was unsuccessful: {f.error}")

        # Compute confidence
        confidence = ConfidenceCalculator.calculate(plan, tool_results, evidence)

        # Build response based on intent
        intent = plan.intent
        metrics: List[Dict[str, Any]] = []
        findings: List[Dict[str, Any]] = []
        answer_text = ""

        # Use reasoner for complex queries
        if plan.requires_reasoning:
            reasoned = FinanceReasoner.analyze(plan, tool_results)
            findings.extend(reasoned["findings"])
            metrics.extend(reasoned["metrics"])
            limitations.extend(reasoned["limitations"])

        # Intent-specific deterministic formatters
        if intent == QueryIntent.VENDOR_SPEND:
            answer_text, metrics = cls._format_vendor_spend(plan, tool_results)
        elif intent == QueryIntent.TOTAL_SPEND:
            answer_text, metrics = cls._format_total_spend(tool_results)
        elif intent == QueryIntent.TOP_VENDORS:
            answer_text, metrics = cls._format_top_vendors(tool_results)
        elif intent == QueryIntent.UNPAID_INVOICES:
            answer_text, metrics = cls._format_unpaid_invoices(tool_results)
        elif intent == QueryIntent.OVERDUE_INVOICES:
            answer_text, metrics = cls._format_overdue_invoices(tool_results)
        elif intent == QueryIntent.INVOICE_LOOKUP:
            answer_text = cls._format_invoice_lookup(tool_results)
        elif intent == QueryIntent.PO_LOOKUP:
            answer_text = cls._format_po_lookup(tool_results)
        elif intent == QueryIntent.ENTITY_RELATIONSHIP:
            answer_text = cls._format_relationships(tool_results)
        elif intent == QueryIntent.SEMANTIC_DOCUMENT_SEARCH:
            answer_text = cls._format_semantic_search(plan, tool_results)
        elif intent == QueryIntent.RULE_VIOLATIONS:
            answer_text, findings = cls._format_rule_violations(tool_results)
        elif intent == QueryIntent.ANOMALIES:
            answer_text, findings = cls._format_anomalies(tool_results)
        elif intent == QueryIntent.SPEND_COMPARISON:
            answer_text, metrics = cls._format_spend_comparison(tool_results)
        elif intent in (QueryIntent.INVESTIGATION_REQUEST, QueryIntent.SPEND_CHANGE_EXPLANATION):
            answer_text = cls._format_investigation(plan, metrics, findings)
        else:
            answer_text = cls._format_generic(tool_results)

        if not answer_text:
            answer_text = "No financial records matching your query were found."

        return FinanceAnswer(
            query_id=plan.query_id,
            question=question,
            answer=answer_text,
            intent=plan.intent,
            metrics=metrics,
            findings=findings,
            evidence=evidence,
            confidence=confidence,
            limitations=limitations,
            query_plan=plan,
        )

    # ── Deterministic Formatters ──────────────────────────────────────────

    @staticmethod
    def _format_vendor_spend(plan: QueryPlan, results: List[ToolResult]) -> (str, List[Dict[str, Any]]):
        res = next((r for r in results if r.operation == ToolOperation.GET_VENDOR_TOTAL_SPEND), None)
        if not res or not res.success or not res.data:
            return "Unable to calculate vendor spend.", []

        d = res.data
        vendor = d.get("vendor_name") or plan.entities.get("vendor_name") or "the vendor"
        spend = d.get("total_spend", "0.00")
        count = d.get("invoice_count", 0)
        currency = d.get("currency", "INR")

        period_desc = ""
        if d.get("start_date") and d.get("end_date"):
            period_desc = f" between {d['start_date']} and {d['end_date']}"

        text = f"Total spend with {vendor}{period_desc} was {currency} {spend} across {count} invoice(s)."
        metrics = [{
            "name": "total_spend",
            "vendor": vendor,
            "value": spend,
            "currency": currency,
            "invoice_count": count,
        }]
        return text, metrics

    @staticmethod
    def _format_total_spend(results: List[ToolResult]) -> (str, List[Dict[str, Any]]):
        res = next((r for r in results if r.operation == ToolOperation.ANALYTICS_TOTAL_SPEND), None)
        if not res or not res.success or not res.data:
            return "Unable to retrieve total organization spend.", []

        d = res.data
        spend = d.get("total_invoice_spend", 0.0)
        invs = d.get("total_invoices", 0)
        pos = d.get("total_purchase_orders", 0)

        text = f"Total organization spend across all processed invoices is ₹{spend:,.2f} across {invs} invoice(s) and {pos} purchase order(s)."
        metrics = [{"name": "total_spend", "value": str(spend), "total_invoices": invs, "total_purchase_orders": pos}]
        return text, metrics

    @staticmethod
    def _format_top_vendors(results: List[ToolResult]) -> (str, List[Dict[str, Any]]):
        res = next((r for r in results if r.operation == ToolOperation.GET_TOP_VENDORS), None)
        if not res or not res.success or not res.data:
            return "Unable to retrieve top vendors.", []

        vendors = res.data.get("top_vendors", [])
        if not vendors:
            return "No vendor spending data available.", []

        lines = [f"Top {len(vendors)} vendors by spend:"]
        for idx, v in enumerate(vendors, 1):
            lines.append(f"{idx}. {v['vendor_name']}: ₹{v['total_spend']} ({v['invoice_count']} invoices)")

        return "\n".join(lines), vendors

    @staticmethod
    def _format_unpaid_invoices(results: List[ToolResult]) -> (str, List[Dict[str, Any]]):
        res = next((r for r in results if r.operation == ToolOperation.GET_UNPAID_INVOICES), None)
        if not res or not res.success or not res.data:
            return "Unable to retrieve unpaid invoices.", []

        invoices = res.data.get("unpaid_invoices", [])
        if not invoices:
            return "There are no unpaid invoices currently recorded.", []

        known_amounts = [
            Decimal(str(i["total_amount"]))
            for i in invoices
            if i.get("total_amount") is not None
        ]
        total_unpaid = sum(known_amounts, Decimal("0.00"))
        unknown_count = len(invoices) - len(known_amounts)
        if known_amounts:
            amount_note = f" totaling ₹{total_unpaid}"
            if unknown_count:
                amount_note += f" across {len(known_amounts)} invoice(s) with known totals"
        else:
            amount_note = " with no known totals"
        lines = [f"Found {len(invoices)} unpaid or partially paid invoice(s){amount_note}:"]
        for inv in invoices[:10]:
            invoice_number = inv.get("invoice_number") or inv.get("invoice_id")
            vendor_name = inv.get("vendor_name") or "Unknown vendor"
            total_amount = inv.get("total_amount")
            amount = f"₹{total_amount}" if total_amount is not None else "N/A"
            lines.append(f"- {invoice_number} ({vendor_name}): {amount}, due {inv['due_date'] or 'N/A'}")

        if len(invoices) > 10:
            lines.append(f"... and {len(invoices) - 10} more.")

        metrics = [{"name": "unpaid_total", "value": str(total_unpaid), "count": len(invoices)}]
        return "\n".join(lines), metrics

    @staticmethod
    def _format_overdue_invoices(results: List[ToolResult]) -> (str, List[Dict[str, Any]]):
        res = next((r for r in results if r.operation == ToolOperation.GET_OVERDUE_INVOICES), None)
        if not res or not res.success or not res.data:
            return "Unable to retrieve overdue invoices.", []

        invoices = res.data.get("overdue_invoices", [])
        if not invoices:
            return "No overdue invoices found.", []

        lines = [f"Found {len(invoices)} overdue invoice(s):"]
        for inv in invoices[:10]:
            lines.append(f"- {inv['invoice_number']} ({inv['vendor_name']}): ₹{inv['total_amount']}, {inv['days_overdue']} days overdue")

        return "\n".join(lines), [{"name": "overdue_count", "value": len(invoices)}]

    @staticmethod
    def _format_invoice_lookup(results: List[ToolResult]) -> str:
        res = next((r for r in results if r.operation == ToolOperation.GET_INVOICE_BY_NUMBER), None)
        if not res or not res.success or not res.data:
            return "Invoice not found or could not be retrieved."

        d = res.data
        return (
            f"Invoice {d['invoice_number']} from {d['vendor_name']}:\n"
            f"- Date: {d.get('invoice_date') or 'N/A'}\n"
            f"- Total: {d.get('currency', 'INR')} {d.get('total_amount')}\n"
            f"- Status: {d.get('payment_status')}\n"
            f"- PO Reference: {d.get('po_number') or 'None'}"
        )

    @staticmethod
    def _format_po_lookup(results: List[ToolResult]) -> str:
        res = next((r for r in results if r.operation == ToolOperation.GET_PURCHASE_ORDER), None)
        if not res or not res.success or not res.data:
            return "Purchase Order not found."

        d = res.data
        return (
            f"Purchase Order {d['po_number']} with {d['vendor_name']}:\n"
            f"- Date: {d.get('po_date') or 'N/A'}\n"
            f"- Total: ₹{d.get('total_amount')}\n"
            f"- Status: {d.get('status')}"
        )

    @staticmethod
    def _format_relationships(results: List[ToolResult]) -> str:
        res = next((r for r in results if r.tool.value == "GRAPH"), None)
        if not res or not res.success or not res.data:
            return "Unable to trace entity relationships from knowledge graph."

        nodes = res.data.get("nodes", [])
        edges = res.data.get("edges", [])
        return (
            f"Graph trace retrieved {len(nodes)} connected node(s) and {len(edges)} relationship(s).\n"
            f"Connected entities: {', '.join(set(n.get('label', 'Entity') + ':' + str(n.get('id')) for n in nodes[:8]))}"
        )

    @staticmethod
    def _format_semantic_search(plan: QueryPlan, results: List[ToolResult]) -> str:
        res = next((r for r in results if r.tool.value == "VECTOR"), None)
        if not res or not res.success or not res.data:
            return "No semantically matching document passages found."

        items = res.data
        if not items:
            return "No matching document regions found."

        lines = [f"Found {len(items)} matching document passage(s):"]
        for idx, it in enumerate(items[:5], 1):
            raw_text = it.get("text") or it.get("matched_text") or it.get("content", "")
            text_snippet = raw_text.replace("\n", " ")[:120]
            raw_score = it.get("similarity_score") if "similarity_score" in it else it.get("score", 0.0)
            score = round(float(raw_score), 3)
            page = it.get("page_number", 1)
            lines.append(f"{idx}. (score {score}, page {page}): \"{text_snippet}...\"")

        return "\n".join(lines)

    @staticmethod
    def _format_rule_violations(results: List[ToolResult]) -> (str, List[Dict[str, Any]]):
        res = next((r for r in results if r.tool.value == "RULES"), None)
        if not res or not res.success or not res.data:
            return "Unable to retrieve rule violations.", []

        violations = res.data.get("violations", [])
        if not violations:
            return "No business rule violations found for the specified criteria.", []

        lines = [f"Found {len(violations)} rule violation(s):"]
        for v in violations[:8]:
            lines.append(f"- [{v['severity']}] {v['rule_name']} on {v['entity_type']} {v['entity_id']}")

        return "\n".join(lines), violations

    @staticmethod
    def _format_anomalies(results: List[ToolResult]) -> (str, List[Dict[str, Any]]):
        res = next((r for r in results if r.tool.value == "ANOMALY"), None)
        if not res or not res.success or not res.data:
            return "Unable to retrieve anomaly records.", []

        anomalies = res.data.get("anomalies", [])
        if not anomalies:
            return "No statistical spending anomalies were detected.", []

        lines = [f"Found {len(anomalies)} statistical outlier(s):"]
        for a in anomalies[:8]:
            lines.append(f"- {a['anomaly_type']}: observed ₹{a['observed_value']} (z-score: {a.get('z_score', 'N/A')})")

        return "\n".join(lines), anomalies

    @staticmethod
    def _format_spend_comparison(results: List[ToolResult]) -> (str, List[Dict[str, Any]]):
        res = next((r for r in results if r.operation == ToolOperation.COMPARE_VENDOR_SPEND), None)
        if not res or not res.success or not res.data:
            return "Unable to compare spending periods.", []

        d = res.data
        a = d.get("period_a_spend", "0.00")
        b = d.get("period_b_spend", "0.00")
        diff = d.get("absolute_difference", "0.00")
        pct = d.get("percentage_change", "0.00")

        text = (
            f"Spend Comparison:\n"
            f"- Baseline: ₹{a}\n"
            f"- Comparison: ₹{b}\n"
            f"- Absolute change: ₹{diff} ({pct}%)"
        )
        return text, [d]

    @staticmethod
    def _format_investigation(plan: QueryPlan, metrics: List[Dict[str, Any]], findings: List[Dict[str, Any]]) -> str:
        lines = [f"Investigation analysis for: \"{plan.original_question}\""]
        if metrics:
            for m in metrics:
                if m.get("name") == "spend_delta":
                    lines.append(f"- Spend changed from ₹{m['previous_spend']} ({m['previous_period']}) to ₹{m['current_spend']} ({m['current_period']}), delta: ₹{m['absolute_change']} ({m['percentage_change']}).")

        if findings:
            lines.append("\nKey Findings:")
            for f in findings:
                lines.append(f"- {f.get('title')}: {f.get('description')}")
        else:
            lines.append("- No abnormal discrepancies or rule violations were observed in the examined data.")

        return "\n".join(lines)

    @staticmethod
    def _format_generic(results: List[ToolResult]) -> str:
        successful = [r for r in results if r.success]
        if not successful:
            return "Unable to retrieve data for the requested query."
        return f"Query executed successfully with {len(successful)} tool operations."
