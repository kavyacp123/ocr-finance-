"""
Finance Vector Search Tool
==========================

WHY:   Semantic text questions ("Find invoices mentioning GPU compute",
       "migration consulting") cannot be answered by SQL.
       This tool queries the Phase 5 VectorStore and returns results
       with exact OCR region bounding boxes and provenance.

WHERE: Called by QueryExecutor when step.tool == ToolName.VECTOR.

WHAT IT RECEIVES: Query string + filters + organization_id.

WHAT IT OUTPUTS:  ToolResult with matched chunks and OCR_REGION Evidence.
"""

from typing import Any, Dict, List, Optional, Set

from app.finance.vector.store import VectorStore
from app.intelligence.schemas import (
    ToolName,
    ToolOperation,
    ToolResult,
    Evidence,
    EvidenceSourceType,
)
from app.intelligence.tools.base import BaseFinanceTool
from app.utils.logging import logger


class FinanceVectorTool(BaseFinanceTool):
    """
    Semantic vector retrieval tool wrapping the Phase 5 VectorStore.
    """

    tool_name = ToolName.VECTOR
    supported_operations: Set[ToolOperation] = {
        ToolOperation.SEMANTIC_SEARCH,
        ToolOperation.LINE_ITEM_SEARCH,
        ToolOperation.DOCUMENT_SEARCH,
        ToolOperation.EVIDENCE_SEARCH,
    }

    def __init__(self, vector_store: Optional[VectorStore] = None):
        self.vector_store = vector_store

    async def _execute(
        self,
        step_id: str,
        operation: ToolOperation,
        arguments: dict,
        organization_id: str,
    ) -> ToolResult:
        if not self.vector_store:
            return ToolResult(
                step_id=step_id,
                tool=self.tool_name,
                operation=operation,
                success=False,
                error="Vector store not configured or unavailable",
                execution_time_ms=0,
            )

        query = arguments.get("query", "").strip()
        top_k = arguments.get("top_k", 10)
        filters = arguments.get("filters", {})

        if operation == ToolOperation.EVIDENCE_SEARCH:
            doc_id = arguments.get("document_id")
            if not doc_id:
                return ToolResult(
                    step_id=step_id,
                    tool=self.tool_name,
                    operation=operation,
                    success=False,
                    error="document_id required for EVIDENCE_SEARCH",
                    execution_time_ms=0,
                )
            items = self.vector_store.get_evidence(document_id=doc_id, query=query, top_k=top_k)
            evidence = [
                Evidence(
                    evidence_id=self._make_evidence_id(),
                    source_type=EvidenceSourceType.OCR_REGION,
                    document_id=it.document_id,
                    page_number=it.page_number,
                    region_id=it.region_id,
                    bbox=it.bbox,
                    source_text=it.matched_text,
                    confidence=float(it.similarity_score),
                    source_operation=ToolOperation.EVIDENCE_SEARCH.value,
                )
                for it in items
            ]
            return ToolResult(
                step_id=step_id,
                tool=self.tool_name,
                operation=operation,
                success=True,
                data=[it.model_dump() for it in items],
                evidence=evidence,
                record_count=len(items),
                execution_time_ms=0,
            )

        # Apply specific filters per operation
        merged_filters = dict(filters)
        if operation == ToolOperation.LINE_ITEM_SEARCH:
            merged_filters["chunk_type"] = "line_item"
        elif operation == ToolOperation.DOCUMENT_SEARCH:
            merged_filters["chunk_type"] = "document"

        vendor_id = arguments.get("vendor_id")
        if vendor_id:
            merged_filters["vendor_id"] = vendor_id

        results = self.vector_store.search(
            query=query,
            organization_id=organization_id,
            top_k=top_k,
            filters=merged_filters if merged_filters else None,
        )

        evidence = []
        for r in results:
            ev = Evidence(
                evidence_id=self._make_evidence_id(),
                source_type=EvidenceSourceType.OCR_REGION if r.bbox else EvidenceSourceType.VECTOR_CHUNK,
                document_id=r.document_id,
                invoice_id=r.metadata.get("invoice_id"),
                vendor_id=r.metadata.get("vendor_id"),
                page_number=r.page_number,
                region_id=r.region_id,
                bbox=r.bbox,
                source_text=r.text,
                confidence=float(r.similarity_score),
                source_operation=operation.value,
            )
            evidence.append(ev)

        return ToolResult(
            step_id=step_id,
            tool=self.tool_name,
            operation=operation,
            success=True,
            data=[r.model_dump() for r in results],
            evidence=evidence,
            record_count=len(results),
            execution_time_ms=0,
        )
