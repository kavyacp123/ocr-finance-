"""
Finance Copilot Service
=======================

WHY:   Unified entry point for natural language financial questions.
       Orchestrates the entire Phase 6 pipeline:
         Question
            ↓
         QueryPlanner (Dates + Entities + Intent + Steps DAG)
            ↓
         QueryExecutor (Async DAG execution with timeouts & tenant isolation)
            ↓
         EvidenceAggregator (Deduplication & Provenance mapping)
            ↓
         AnswerGenerator (Factual grounded synthesis + confidence calculation)
            ↓
         FinanceAnswer + ConversationContext update

WHERE: Initialized at app startup in app.state.copilot; called by POST /copilot/ask.

WHAT IT RECEIVES: User question, organization_id, optional ConversationContext.

WHAT IT OUTPUTS:  FinanceAnswer (structured, evidence-backed).
"""

from typing import Dict, Optional, Tuple
from sqlalchemy.orm import Session

from app.database.session import SessionLocal
from app.intelligence.schemas import (
    FinanceAnswer,
    ConversationContext,
    ToolName,
    QueryPlan,
)
from app.intelligence.planner import QueryPlanner
from app.intelligence.executor import QueryExecutor
from app.intelligence.evidence import EvidenceAggregator
from app.intelligence.answer_generator import AnswerGenerator
from app.intelligence.tools.base import BaseFinanceTool
from app.intelligence.tools.sql_tool import FinanceSQLTool
from app.intelligence.tools.graph_tool import FinanceGraphTool
from app.intelligence.tools.vector_tool import FinanceVectorTool
from app.intelligence.tools.analytics_tool import FinanceAnalyticsTool
from app.intelligence.tools.rules_tool import FinanceRulesTool
from app.intelligence.tools.anomaly_tool import FinanceAnomalyTool
from app.utils.logging import logger


class FinanceCopilotService:
    """
    Production-grade Financial Intelligence Assistant.
    """

    def __init__(
        self,
        planner: Optional[QueryPlanner] = None,
        tools: Optional[Dict[ToolName, BaseFinanceTool]] = None,
        session_factory=SessionLocal,
    ):
        self.session_factory = session_factory
        self.planner = planner or QueryPlanner()
        self.tools = tools or {}
        self.executor = QueryExecutor(self.tools)

    @classmethod
    def create_default(
        cls,
        graph_adapter=None,
        vector_store=None,
        rule_engine=None,
        anomaly_detector=None,
        session_factory=SessionLocal,
    ) -> "FinanceCopilotService":
        """
        Factory to instantiate with all standard tools wired up.
        """
        tools: Dict[ToolName, BaseFinanceTool] = {
            ToolName.SQL: FinanceSQLTool(session_factory=session_factory),
            ToolName.GRAPH: FinanceGraphTool(graph_adapter=graph_adapter),
            ToolName.VECTOR: FinanceVectorTool(vector_store=vector_store),
            ToolName.ANALYTICS: FinanceAnalyticsTool(session_factory=session_factory),
            ToolName.RULES: FinanceRulesTool(session_factory=session_factory, rule_engine=rule_engine),
            ToolName.ANOMALY: FinanceAnomalyTool(session_factory=session_factory, anomaly_detector=anomaly_detector),
        }
        return cls(tools=tools, session_factory=session_factory)

    async def ask(
        self,
        question: str,
        organization_id: str,
        context: Optional[ConversationContext] = None,
    ) -> Tuple[FinanceAnswer, ConversationContext]:
        """
        Process a user question through the complete copilot pipeline.
        """
        db: Session = self.session_factory()
        try:
            # 1. Plan
            plan: QueryPlan = self.planner.plan(
                question=question,
                db=db,
                organization_id=organization_id,
                context=context,
            )
        finally:
            db.close()

        # 2. Execute steps
        tool_results = await self.executor.execute(
            plan=plan,
            organization_id=organization_id,
        )

        # 3. Aggregate evidence
        evidence = EvidenceAggregator.aggregate(tool_results)

        # 4. Generate grounded answer
        answer = AnswerGenerator.generate(
            question=question,
            plan=plan,
            tool_results=tool_results,
            evidence=evidence,
        )

        # 5. Update conversation context
        new_context = self._update_context(context or ConversationContext(), plan)

        logger.info(
            f"COPILOT: Answered '{question[:50]}' with intent={answer.intent.value}, "
            f"evidence_count={len(answer.evidence)}, confidence={answer.confidence}"
        )
        return answer, new_context

    @staticmethod
    def _update_context(
        ctx: ConversationContext, plan: QueryPlan
    ) -> ConversationContext:
        ctx.last_query_id = plan.query_id
        ctx.last_intent = plan.intent
        if plan.time_range:
            ctx.last_date_range = plan.time_range
        if "vendor_id" in plan.entities:
            ctx.last_vendor_id = plan.entities["vendor_id"]
            ctx.last_vendor_name = plan.entities.get("vendor_name")
        if "invoice_id" in plan.entities:
            ctx.last_invoice_id = plan.entities["invoice_id"]
        if "po_id" in plan.entities:
            ctx.last_po_id = plan.entities["po_id"]
        return ctx
