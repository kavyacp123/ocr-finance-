"""
Evidence Aggregator
===================

WHY:   Every answer delivered by the Copilot must cite auditable evidence.
       This aggregator collects evidence from all ToolResults, dedupes them,
       and provides structured access to provenance.

WHERE: Called after query execution, before answer generation.

WHAT IT RECEIVES: List[ToolResult] from the execution engine.

WHAT IT OUTPUTS:  Deduplicated, organized List[Evidence].
"""

from typing import List, Set
from app.intelligence.schemas import Evidence, ToolResult


class EvidenceAggregator:
    """
    Collects, deduplicates, and organizes evidence items across tool results.
    """

    @staticmethod
    def aggregate(tool_results: List[ToolResult]) -> List[Evidence]:
        all_evidence: List[Evidence] = []
        seen_keys: Set[str] = set()

        for res in tool_results:
            if not res.success or not res.evidence:
                continue

            for ev in res.evidence:
                # Deduplication key based on source coordinates or unique IDs
                key = f"{ev.source_type.value}:{ev.document_id}:{ev.region_id}:{ev.invoice_id}:{ev.po_id}:{ev.payment_id}"
                if ev.metric:
                    key += f":{ev.metric.get('name')}"

                if key not in seen_keys:
                    seen_keys.add(key)
                    all_evidence.append(ev)

        # Sort by confidence descending
        all_evidence.sort(key=lambda e: e.confidence, reverse=True)
        return all_evidence
