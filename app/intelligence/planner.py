"""
Deterministic Query Planner
===========================

WHY:   We must NEVER send every question directly to an LLM.
       The planner inspects the user question, resolves dates and entities,
       and builds a deterministic QueryPlan DAG that calls approved tools.
       LLM planning is only a fallback for queries that pattern recognition cannot resolve.

WHERE: Called by FinanceCopilotService as the first step of processing.

WHAT IT RECEIVES: User question + DB session + organization_id + optional ConversationContext.

WHAT IT OUTPUTS:  A strongly typed QueryPlan with strict QuerySteps.
"""

import re
import uuid
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session

from app.intelligence.schemas import (
    QueryPlan,
    QueryStep,
    QueryIntent,
    ToolName,
    ToolOperation,
    TimeRange,
    ConversationContext,
)
from app.intelligence.date_parser import DateParser
from app.intelligence.entity_parser import EntityParser
from app.utils.logging import logger


class QueryPlanner:
    """
    Hybrid Query Planner:
      Stage A: Deterministic regex and keyword pattern recognition (fast, zero hallucination).
      Stage B: Fallback heuristic for complex queries.
    """

    def __init__(self):
        self.date_parser = DateParser()
        self.entity_parser = EntityParser()

    def plan(
        self,
        question: str,
        db: Session,
        organization_id: str,
        context: Optional[ConversationContext] = None,
    ) -> QueryPlan:
        query_id = f"qry_{uuid.uuid4().hex[:12]}"
        normalized_q = question.strip()

        # 1. Parse Dates
        time_range = self.date_parser.parse(normalized_q)
        # Follow-up context support: if no date in question but previous date exists and question is comparative/follow-up
        if not time_range and context and context.last_date_range:
            if any(w in normalized_q.lower() for w in ["what about", "and for", "same period", "how about"]):
                time_range = context.last_date_range

        # 2. Parse Entities
        entities = self.entity_parser.parse(normalized_q, db, organization_id)
        # Follow-up context support: if no vendor in question but exists in context
        if "vendor_id" not in entities and context and context.last_vendor_id:
            # If the user asks something like "what about July?" or "show their invoices"
            if any(w in normalized_q.lower() for w in ["their", "that vendor", "it", "what about", "how about", "same"]):
                entities["vendor_id"] = context.last_vendor_id
                entities["vendor_name"] = context.last_vendor_name

        # 3. Classify Intent
        intent = self._classify_intent(normalized_q, entities)

        # 4. Generate Steps DAG
        steps, requires_reasoning = self._build_steps(
            intent=intent,
            entities=entities,
            time_range=time_range,
            question=normalized_q,
            organization_id=organization_id,
        )

        ambiguities = []
        if "vendor_name_unresolved" in entities:
            ambiguities.append(f"Vendor '{entities['vendor_name_unresolved']}' could not be resolved to a known vendor.")

        confidence = 1.0 if not ambiguities else 0.75

        plan = QueryPlan(
            query_id=query_id,
            original_question=question,
            normalized_question=normalized_q,
            intent=intent,
            entities=entities,
            time_range=time_range,
            steps=steps,
            requires_reasoning=requires_reasoning,
            requires_evidence=True,
            ambiguities=ambiguities,
            planner_confidence=confidence,
        )

        logger.info(f"PLANNER: Planned query {query_id} -> Intent={intent.value}, Steps={len(steps)}")
        return plan

    def _classify_intent(self, text: str, entities: Dict[str, Any]) -> QueryIntent:
        lower = text.lower()

        # Investigation / Explain spend change
        if any(p in lower for p in [
            "why did", "why has", "explain why", "reason for", "spending increase",
            "spend increase", "why spend", "investigate", "what caused", "why was"
        ]):
            return QueryIntent.INVESTIGATION_REQUEST

        # Anomalies
        if any(p in lower for p in ["unusual", "anomalous", "anomaly", "anomalies", "outlier"]):
            return QueryIntent.ANOMALIES

        # Rule violations / PO mismatches
        if any(p in lower for p in ["mismatch", "rule violation", "broke rule", "missing po", "without po", "violations"]):
            return QueryIntent.RULE_VIOLATIONS

        # Unpaid / Overdue invoices
        if any(p in lower for p in ["overdue", "past due"]):
            return QueryIntent.OVERDUE_INVOICES
        if any(p in lower for p in ["unpaid", "pending payment", "not paid", "outstanding invoices"]):
            return QueryIntent.UNPAID_INVOICES

        # Compare spend
        if any(p in lower for p in ["compare", "difference between", "versus", "vs"]):
            return QueryIntent.SPEND_COMPARISON

        # Top vendors / rankings
        if any(p in lower for p in ["top vendor", "highest spend", "most spend", "top 5", "top 10", "biggest vendor"]):
            return QueryIntent.TOP_VENDORS

        # Relationships / Graph
        if any(p in lower for p in [
            "connected to", "relation", "relationship", "linked to", "associated with",
            "path between", "vendor network", "belong to invoices", "which payments belong"
        ]):
            return QueryIntent.ENTITY_RELATIONSHIP

        # Semantic document search / line items
        if any(p in lower for p in [
            "mentioning", "containing", "related to", "about", "find invoices",
            "search for", "gpu", "migration", "consulting", "infrastructure"
        ]):
            return QueryIntent.SEMANTIC_DOCUMENT_SEARCH

        # Invoices / PO / Payment lookup
        if "invoice_number" in entities or any(p in lower for p in ["invoice details", "show invoice", "lookup invoice"]):
            return QueryIntent.INVOICE_LOOKUP
        if "po_number" in entities or any(p in lower for p in ["show po", "po details", "purchase order"]):
            return QueryIntent.PO_LOOKUP
        if "payment_reference" in entities:
            return QueryIntent.PAYMENT_LOOKUP

        # Spend queries
        if any(p in lower for p in ["how much", "total spend", "spend with", "cost us", "spent on", "total spent"]):
            if entities.get("vendor_id") or entities.get("vendor_name") or entities.get("vendor_name_unresolved"):
                return QueryIntent.VENDOR_SPEND
            return QueryIntent.TOTAL_SPEND

        if "month" in lower or "monthly" in lower:
            return QueryIntent.MONTHLY_SPEND

        return QueryIntent.GENERAL_FINANCE_QUERY

    def _build_steps(
        self,
        intent: QueryIntent,
        entities: Dict[str, Any],
        time_range: Optional[TimeRange],
        question: str,
        organization_id: str,
    ) -> (List[QueryStep], bool):
        steps: List[QueryStep] = []
        requires_reasoning = False

        start_date = time_range.start_date if time_range else None
        end_date = time_range.end_date if time_range else None
        vendor_id = entities.get("vendor_id")
        vendor_name = entities.get("vendor_name") or entities.get("vendor_name_unresolved")

        if intent == QueryIntent.VENDOR_SPEND:
            steps.append(
                QueryStep(
                    step_id="step_1",
                    tool=ToolName.SQL,
                    operation=ToolOperation.GET_VENDOR_TOTAL_SPEND,
                    arguments={
                        "vendor_id": vendor_id,
                        "vendor_name": vendor_name,
                        "start_date": start_date,
                        "end_date": end_date,
                    },
                    description=f"Calculate total spend with {vendor_name or 'vendor'} via SQL",
                )
            )

        elif intent == QueryIntent.TOTAL_SPEND:
            steps.append(
                QueryStep(
                    step_id="step_1",
                    tool=ToolName.ANALYTICS,
                    operation=ToolOperation.ANALYTICS_TOTAL_SPEND,
                    arguments={},
                    description="Get total organization spend summary",
                )
            )

        elif intent == QueryIntent.MONTHLY_SPEND:
            steps.append(
                QueryStep(
                    step_id="step_1",
                    tool=ToolName.SQL,
                    operation=ToolOperation.GET_MONTHLY_VENDOR_SPEND,
                    arguments={
                        "vendor_id": vendor_id,
                        "vendor_name": vendor_name,
                        "start_date": start_date,
                        "end_date": end_date,
                    },
                    description="Get monthly spend breakdown",
                )
            )

        elif intent == QueryIntent.TOP_VENDORS:
            steps.append(
                QueryStep(
                    step_id="step_1",
                    tool=ToolName.SQL,
                    operation=ToolOperation.GET_TOP_VENDORS,
                    arguments={
                        "limit": 5,
                        "start_date": start_date,
                        "end_date": end_date,
                    },
                    description="Get top vendors by spend",
                )
            )

        elif intent == QueryIntent.UNPAID_INVOICES:
            steps.append(
                QueryStep(
                    step_id="step_1",
                    tool=ToolName.SQL,
                    operation=ToolOperation.GET_UNPAID_INVOICES,
                    arguments={"vendor_id": vendor_id},
                    description="Retrieve unpaid invoices from database",
                )
            )

        elif intent == QueryIntent.OVERDUE_INVOICES:
            steps.append(
                QueryStep(
                    step_id="step_1",
                    tool=ToolName.SQL,
                    operation=ToolOperation.GET_OVERDUE_INVOICES,
                    arguments={},
                    description="Retrieve overdue invoices from database",
                )
            )

        elif intent == QueryIntent.INVOICE_LOOKUP:
            if entities.get("invoice_number"):
                steps.append(
                    QueryStep(
                        step_id="step_1",
                        tool=ToolName.SQL,
                        operation=ToolOperation.GET_INVOICE_BY_NUMBER,
                        arguments={"invoice_number": entities["invoice_number"]},
                        description=f"Lookup invoice {entities['invoice_number']}",
                    )
                )
            else:
                steps.append(
                    QueryStep(
                        step_id="step_1",
                        tool=ToolName.SQL,
                        operation=ToolOperation.GET_INVOICES_FOR_PERIOD,
                        arguments={"vendor_id": vendor_id, "start_date": start_date, "end_date": end_date},
                        description="List invoices matching criteria",
                    )
                )

        elif intent == QueryIntent.PO_LOOKUP:
            steps.append(
                QueryStep(
                    step_id="step_1",
                    tool=ToolName.SQL,
                    operation=ToolOperation.GET_PURCHASE_ORDER,
                    arguments={"po_number": entities.get("po_number"), "po_id": entities.get("po_id")},
                    description="Lookup purchase order",
                )
            )

        elif intent == QueryIntent.ENTITY_RELATIONSHIP:
            if entities.get("invoice_id"):
                steps.append(
                    QueryStep(
                        step_id="step_1",
                        tool=ToolName.GRAPH,
                        operation=ToolOperation.GET_INVOICE_RELATIONSHIPS,
                        arguments={"invoice_id": entities["invoice_id"]},
                        description=f"Trace relationships for invoice {entities['invoice_id']}",
                    )
                )
            elif vendor_id:
                steps.append(
                    QueryStep(
                        step_id="step_1",
                        tool=ToolName.GRAPH,
                        operation=ToolOperation.GET_VENDOR_NETWORK,
                        arguments={"vendor_id": vendor_id},
                        description=f"Retrieve entity network for vendor {vendor_name}",
                    )
                )
            else:
                # Default to finding connected documents
                steps.append(
                    QueryStep(
                        step_id="step_1",
                        tool=ToolName.GRAPH,
                        operation=ToolOperation.GET_CONNECTED_DOCUMENTS,
                        arguments={"entity_id": entities.get("invoice_number") or entities.get("po_number") or "root"},
                        description="Query knowledge graph for connected entities",
                    )
                )

        elif intent == QueryIntent.SEMANTIC_DOCUMENT_SEARCH:
            # Extract key search terms from question
            cleaned_query = self._extract_semantic_query(question)
            steps.append(
                QueryStep(
                    step_id="step_1",
                    tool=ToolName.VECTOR,
                    operation=ToolOperation.SEMANTIC_SEARCH,
                    arguments={
                        "query": cleaned_query,
                        "vendor_id": vendor_id,
                        "top_k": 10,
                    },
                    description=f"Semantic search for '{cleaned_query}' across indexed documents",
                )
            )

        elif intent == QueryIntent.RULE_VIOLATIONS:
            if "mismatch" in question.lower():
                steps.append(
                    QueryStep(
                        step_id="step_1",
                        tool=ToolName.RULES,
                        operation=ToolOperation.GET_PO_MISMATCHES,
                        arguments={"vendor_id": vendor_id},
                        description="Retrieve PO amount mismatch violations",
                    )
                )
            else:
                steps.append(
                    QueryStep(
                        step_id="step_1",
                        tool=ToolName.RULES,
                        operation=ToolOperation.GET_VENDOR_RULE_VIOLATIONS if vendor_id else ToolOperation.GET_DOCUMENT_RULE_VIOLATIONS,
                        arguments={"vendor_id": vendor_id},
                        description="Retrieve rule violations from rules engine",
                    )
                )

        elif intent == QueryIntent.ANOMALIES:
            steps.append(
                QueryStep(
                    step_id="step_1",
                    tool=ToolName.ANOMALY,
                    operation=ToolOperation.GET_VENDOR_ANOMALIES,
                    arguments={"vendor_id": vendor_id},
                    description=f"Retrieve statistical anomalies for {vendor_name or 'vendors'}",
                )
            )

        elif intent in (QueryIntent.INVESTIGATION_REQUEST, QueryIntent.SPEND_CHANGE_EXPLANATION):
            requires_reasoning = True
            # Multi-tool hybrid execution DAG:
            # Step 1: SQL spend breakdown
            steps.append(
                QueryStep(
                    step_id="step_1",
                    tool=ToolName.SQL,
                    operation=ToolOperation.GET_MONTHLY_VENDOR_SPEND,
                    arguments={"vendor_id": vendor_id, "vendor_name": vendor_name},
                    description="Analyze historical monthly spend pattern",
                )
            )
            # Step 2: Anomaly detection (can run concurrently)
            steps.append(
                QueryStep(
                    step_id="step_2",
                    tool=ToolName.ANOMALY,
                    operation=ToolOperation.GET_VENDOR_ANOMALIES,
                    arguments={"vendor_id": vendor_id},
                    description="Check for statistical spending anomalies",
                )
            )
            # Step 3: Rule violations
            steps.append(
                QueryStep(
                    step_id="step_3",
                    tool=ToolName.RULES,
                    operation=ToolOperation.GET_VENDOR_RULE_VIOLATIONS,
                    arguments={"vendor_id": vendor_id},
                    description="Check for business rule violations or mismatches",
                )
            )
            # Step 4: Vector search for contextual line-item keywords
            steps.append(
                QueryStep(
                    step_id="step_4",
                    tool=ToolName.VECTOR,
                    operation=ToolOperation.LINE_ITEM_SEARCH,
                    arguments={"query": "infrastructure cloud consulting license server compute", "vendor_id": vendor_id, "top_k": 5},
                    description="Search semantic line-item context",
                )
            )

        else:
            # General fallback: SQL spend + recent invoices
            steps.append(
                QueryStep(
                    step_id="step_1",
                    tool=ToolName.SQL,
                    operation=ToolOperation.GET_INVOICES_FOR_PERIOD,
                    arguments={"vendor_id": vendor_id, "start_date": start_date, "end_date": end_date},
                    description="Retrieve relevant invoices",
                )
            )

        return steps, requires_reasoning

    @staticmethod
    def _extract_semantic_query(question: str) -> str:
        lower = question.lower()
        # Strip common prefixes
        for prefix in [
            "find invoices mentioning", "find invoices related to", "find invoices containing",
            "find invoice mentioning", "show invoices mentioning", "search for", "find",
            "invoices with", "invoices about"
        ]:
            if prefix in lower:
                return question[lower.find(prefix) + len(prefix):].strip(" ?.,")
        return question.strip(" ?.,")
