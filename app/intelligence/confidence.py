"""
Deterministic Confidence Calculator
====================================

WHY:   We must NEVER ask an LLM "how confident are you?".
       Confidence is computed deterministically from real system telemetry:
       - planner confidence (did entity resolution succeed? was there ambiguity?)
       - tool success rate (did all planned tools succeed?)
       - evidence density (do we have direct supporting evidence?)
       - data availability (did the query find matching records?)

WHERE: Called prior to returning the final FinanceAnswer.

WHAT IT RECEIVES: QueryPlan + List[ToolResult] + List[Evidence].

WHAT IT OUTPUTS:  Float between 0.0 and 1.0.
"""

from typing import List
from app.intelligence.schemas import QueryPlan, ToolResult, Evidence


class ConfidenceCalculator:
    """
    Computes grounded confidence based on execution signals.
    """

    @staticmethod
    def calculate(
        plan: QueryPlan,
        tool_results: List[ToolResult],
        evidence: List[Evidence],
    ) -> float:
        if not tool_results:
            return 0.1

        # 1. Planner quality factor (0.5 to 1.0)
        planner_factor = plan.planner_confidence
        if plan.ambiguities:
            planner_factor *= 0.8

        # 2. Tool success factor (ratio of succeeded steps)
        successful_steps = [r for r in tool_results if r.success]
        tool_factor = len(successful_steps) / len(tool_results)

        # 3. Data availability factor (did we find records or empty data?)
        total_records = sum(r.record_count for r in successful_steps)
        data_factor = 1.0 if total_records > 0 else 0.7

        # 4. Evidence quality factor
        if evidence:
            avg_ev_conf = sum(e.confidence for e in evidence) / len(evidence)
            evidence_factor = 0.8 + (0.2 * min(1.0, avg_ev_conf))
        else:
            evidence_factor = 0.6  # Penalize answers without explicit evidence

        combined = planner_factor * tool_factor * data_factor * evidence_factor
        return round(max(0.05, min(1.0, combined)), 2)
