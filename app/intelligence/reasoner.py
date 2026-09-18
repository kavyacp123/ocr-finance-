"""
Finance Reasoner
================

WHY:   For complex, multi-tool queries (e.g. "Why did AWS spending increase in August?"),
       we need to compare facts, identify delta drivers, and detect patterns across
       SQL, Anomaly, Rule, and Vector outputs WITHOUT letting an LLM invent numbers.
       This reasoner performs deterministic factual comparisons first.

WHERE: Called by AnswerGenerator when plan.requires_reasoning == True.

WHAT IT RECEIVES: QueryPlan + List[ToolResult].

WHAT IT OUTPUTS:  List of structured findings and metric comparisons.
"""

from decimal import Decimal
from typing import Any, Dict, List
from app.intelligence.schemas import QueryPlan, ToolResult, ToolOperation


class FinanceReasoner:
    """
    Synthesizes findings from multiple tool outputs using deterministic logic.
    """

    @staticmethod
    def analyze(plan: QueryPlan, tool_results: List[ToolResult]) -> Dict[str, Any]:
        findings: List[Dict[str, Any]] = []
        metrics: List[Dict[str, Any]] = []
        limitations: List[str] = []

        # Check for partial tool failures
        failed_tools = [r for r in tool_results if not r.success]
        for f in failed_tools:
            limitations.append(f"Tool '{f.tool.value}' operation '{f.operation.value}' failed: {f.error}")

        # Extract monthly spend data
        monthly_res = next((r for r in tool_results if r.operation == ToolOperation.GET_MONTHLY_VENDOR_SPEND), None)
        if monthly_res and monthly_res.success and monthly_res.data:
            breakdown = monthly_res.data.get("monthly_spend", [])
            if len(breakdown) >= 2:
                prev_m = breakdown[-2]
                curr_m = breakdown[-1]
                prev_spend = Decimal(prev_m["spend"])
                curr_spend = Decimal(curr_m["spend"])
                delta = curr_spend - prev_spend
                pct = ((delta / prev_spend) * 100) if prev_spend > 0 else Decimal("0.00")

                metrics.append({
                    "name": "spend_delta",
                    "previous_period": prev_m["month"],
                    "previous_spend": str(prev_spend),
                    "current_period": curr_m["month"],
                    "current_spend": str(curr_spend),
                    "absolute_change": str(delta),
                    "percentage_change": f"{round(pct, 2)}%",
                })

                if delta > 0:
                    findings.append({
                        "type": "SPEND_INCREASE",
                        "title": f"Spend increased by {round(pct, 1)}%",
                        "description": f"Spend rose from ₹{prev_spend} in {prev_m['month']} to ₹{curr_spend} in {curr_m['month']} (increase of ₹{delta}).",
                    })
                elif delta < 0:
                    findings.append({
                        "type": "SPEND_DECREASE",
                        "title": f"Spend decreased by {abs(round(pct, 1))}%",
                        "description": f"Spend dropped from ₹{prev_spend} in {prev_m['month']} to ₹{curr_spend} in {curr_m['month']}.",
                    })

        # Check anomaly results
        anomaly_res = next((r for r in tool_results if r.operation == ToolOperation.GET_VENDOR_ANOMALIES), None)
        if anomaly_res and anomaly_res.success and anomaly_res.data:
            anomalies = anomaly_res.data.get("anomalies", [])
            if anomalies:
                findings.append({
                    "type": "STATISTICAL_ANOMALY",
                    "title": f"{len(anomalies)} statistical outlier(s) detected",
                    "description": f"Found {len(anomalies)} flagged spend anomalies with z-score deviations for this vendor.",
                    "details": anomalies,
                })

        # Check rule violations
        rules_res = next((r for r in tool_results if r.operation in (
            ToolOperation.GET_VENDOR_RULE_VIOLATIONS,
            ToolOperation.GET_DOCUMENT_RULE_VIOLATIONS,
            ToolOperation.GET_PO_MISMATCHES,
        )), None)
        if rules_res and rules_res.success and rules_res.data:
            violations = rules_res.data.get("violations", [])
            if violations:
                findings.append({
                    "type": "RULE_VIOLATIONS",
                    "title": f"{len(violations)} rule violation(s) present",
                    "description": f"Observed business rule violations including: {', '.join(set(v['rule_id'] for v in violations))}.",
                    "details": violations,
                })

        return {
            "findings": findings,
            "metrics": metrics,
            "limitations": limitations,
        }
