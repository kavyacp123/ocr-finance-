"""
Finance Investigation Engine
============================

WHY:   Orchestrates the multi-step financial investigation state machine.
       Coordinates between Phase 6 tools and Phase 7 analyzers without
       reinventing access layers or allowing LLM calculations.

WHERE: Initialized at startup and called by POST /investigate.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.database.session import SessionLocal
from app.intelligence.schemas import (
    ToolName,
    ToolOperation,
    TimeRange,
)
from app.intelligence.tools.base import BaseFinanceTool
from app.intelligence.tools.sql_tool import FinanceSQLTool
from app.intelligence.tools.graph_tool import FinanceGraphTool
from app.intelligence.tools.vector_tool import FinanceVectorTool
from app.intelligence.tools.rules_tool import FinanceRulesTool
from app.intelligence.tools.anomaly_tool import FinanceAnomalyTool

from app.investigations.schemas import (
    InvestigationPlan,
    InvestigationReport,
    InvestigationState,
)
from app.investigations.planner import InvestigationPlanner
from app.investigations.context import InvestigationContext
from app.investigations.state_machine import InvestigationStateMachine
from app.investigations.analyzers.spend_delta import SpendDeltaAnalyzer
from app.investigations.analyzers.line_item_matcher import LineItemMatcher
from app.investigations.analyzers.price_change import PriceChangeAnalyzer
from app.investigations.analyzers.quantity_change import QuantityChangeAnalyzer
from app.investigations.analyzers.duplicate_checker import DuplicateChecker
from app.investigations.analyzers.rule_checker import RuleChecker
from app.investigations.analyzers.anomaly_checker import AnomalyChecker
from app.investigations.findings import FindingEngine
from app.investigations.report import InvestigationReportBuilder
from app.utils.logging import logger


class FinanceInvestigationEngine:
    """
    Constrained Multi-Step Financial Investigation Orchestrator.
    """

    def __init__(
        self,
        planner: Optional[InvestigationPlanner] = None,
        sql_tool: Optional[FinanceSQLTool] = None,
        graph_tool: Optional[FinanceGraphTool] = None,
        vector_tool: Optional[FinanceVectorTool] = None,
        rules_tool: Optional[FinanceRulesTool] = None,
        anomaly_tool: Optional[FinanceAnomalyTool] = None,
        session_factory=SessionLocal,
    ):
        self.planner = planner or InvestigationPlanner()
        self.sql_tool = sql_tool or FinanceSQLTool(session_factory=session_factory)
        self.graph_tool = graph_tool or FinanceGraphTool()
        self.vector_tool = vector_tool or FinanceVectorTool()
        self.rules_tool = rules_tool or FinanceRulesTool(session_factory=session_factory)
        self.anomaly_tool = anomaly_tool or FinanceAnomalyTool(session_factory=session_factory)
        self.session_factory = session_factory

    async def investigate(
        self,
        question: str,
        organization_id: str,
        scope: Optional[Dict[str, Any]] = None,
    ) -> InvestigationReport:
        """
        Main entry point: Plans and executes a multi-step investigation.
        """
        db: Session = self.session_factory()
        try:
            # 1. Planning State
            plan = self.planner.plan(
                question=question,
                db=db,
                organization_id=organization_id,
                scope=scope,
            )
        finally:
            db.close()

        # 2. Context Initialization
        context = InvestigationContext(
            investigation_id=plan.investigation_id,
            organization_id=organization_id,
            current_state=InvestigationState.PLANNING,
            vendor_id=plan.subject.get("vendor_id"),
            vendor_name=plan.subject.get("vendor_name"),
            target_period=plan.time_range,
            baseline_period=plan.baseline_period,
            hypotheses=plan.hypotheses,
        )

        logger.info(f"INVESTIGATION_START: ID={plan.investigation_id} Type={plan.investigation_type.value}")

        try:
            # Step 1: Collect Baseline Spend & Invoices
            await self._run_baseline_collection(context)

            # Step 2: Collect Target Period Spend & Invoices
            await self._run_target_collection(context)

            # Step 3: Spend Delta Comparison
            self._run_comparison(context)

            # Step 4: Match Line Items & Check Price/Quantity Drivers
            self._run_line_item_analysis(context)

            # Step 5: Duplicate Invoices Check
            self._run_duplicate_check(context)

            # Step 6: Rules & PO Mismatch Check
            self._run_rule_check(context)

            # Step 7: Statistical Anomalies Check
            self._run_anomaly_check(context)

            # Step 8: Knowledge Graph Relationship Trace (if relevant)
            await self._run_relationship_check(context)

            # Step 9: Vector Evidence Search
            await self._run_vector_evidence_collection(context)

            # Step 10: Synthesize Findings & Drivers
            self._run_findings_synthesis(context)

            # Finalize State
            InvestigationStateMachine.transition(context.current_state, InvestigationState.COMPLETED, context.step_count)
            context.current_state = InvestigationState.COMPLETED

        except Exception as e:
            logger.error(f"INVESTIGATION_FAILED: ID={context.investigation_id} Error={e}", exc_info=True)
            context.current_state = InvestigationState.FAILED
            context.limitations.append(f"Investigation terminated early due to error: {str(e)}")

        # 3. Build & Return Audit Report
        report = InvestigationReportBuilder.build(plan, context)
        logger.info(f"INVESTIGATION_COMPLETE: ID={report.investigation_id} Findings={len(report.findings)} Drivers={len(report.drivers)}")
        return report

    # ── Pipeline Step Implementations ─────────────────────────────────────────

    async def _run_baseline_collection(self, context: InvestigationContext) -> None:
        InvestigationStateMachine.transition(context.current_state, InvestigationState.COLLECTING_BASELINE, context.step_count)
        context.record_step(InvestigationState.COLLECTING_BASELINE, {"period": context.baseline_period.model_dump() if context.baseline_period else None})

        if not context.baseline_period:
            return

        res = await self.sql_tool.execute(
            step_id="base_spend",
            operation=ToolOperation.GET_VENDOR_TOTAL_SPEND,
            arguments={
                "vendor_id": context.vendor_id,
                "vendor_name": context.vendor_name,
                "start_date": context.baseline_period.start_date,
                "end_date": context.baseline_period.end_date,
            },
            organization_id=context.organization_id,
        )
        if res.success and res.data:
            context.baseline_spend = Decimal(res.data.get("total_spend", "0.00"))
            context.baseline_invoice_count = res.data.get("invoice_count", 0)
            context.evidence.extend(res.evidence)

        # Retrieve baseline invoices & line items
        inv_res = await self.sql_tool.execute(
            step_id="base_invs",
            operation=ToolOperation.GET_INVOICES_FOR_PERIOD,
            arguments={
                "vendor_id": context.vendor_id,
                "start_date": context.baseline_period.start_date,
                "end_date": context.baseline_period.end_date,
            },
            organization_id=context.organization_id,
        )
        if inv_res.success and inv_res.data:
            context.baseline_invoice_ids = [i["invoice_id"] for i in inv_res.data.get("invoices", [])]
            if context.baseline_invoice_ids:
                lines_res = await self.sql_tool.execute(
                    step_id="base_lines",
                    operation=ToolOperation.GET_INVOICE_LINE_ITEMS,
                    arguments={"invoice_ids": context.baseline_invoice_ids},
                    organization_id=context.organization_id,
                )
                if lines_res.success and lines_res.data:
                    context.baseline_line_items = lines_res.data.get("line_items", [])

    async def _run_target_collection(self, context: InvestigationContext) -> None:
        InvestigationStateMachine.transition(context.current_state, InvestigationState.COLLECTING_TARGET_PERIOD, context.step_count)
        context.record_step(InvestigationState.COLLECTING_TARGET_PERIOD, {"period": context.target_period.model_dump() if context.target_period else None})

        if not context.target_period:
            return

        res = await self.sql_tool.execute(
            step_id="target_spend",
            operation=ToolOperation.GET_VENDOR_TOTAL_SPEND,
            arguments={
                "vendor_id": context.vendor_id,
                "vendor_name": context.vendor_name,
                "start_date": context.target_period.start_date,
                "end_date": context.target_period.end_date,
            },
            organization_id=context.organization_id,
        )
        if res.success and res.data:
            context.target_spend = Decimal(res.data.get("total_spend", "0.00"))
            context.target_invoice_count = res.data.get("invoice_count", 0)
            context.evidence.extend(res.evidence)

        inv_res = await self.sql_tool.execute(
            step_id="target_invs",
            operation=ToolOperation.GET_INVOICES_FOR_PERIOD,
            arguments={
                "vendor_id": context.vendor_id,
                "start_date": context.target_period.start_date,
                "end_date": context.target_period.end_date,
            },
            organization_id=context.organization_id,
        )
        if inv_res.success and inv_res.data:
            context.target_invoice_ids = [i["invoice_id"] for i in inv_res.data.get("invoices", [])]
            if context.target_invoice_ids:
                lines_res = await self.sql_tool.execute(
                    step_id="target_lines",
                    operation=ToolOperation.GET_INVOICE_LINE_ITEMS,
                    arguments={"invoice_ids": context.target_invoice_ids},
                    organization_id=context.organization_id,
                )
                if lines_res.success and lines_res.data:
                    context.target_line_items = lines_res.data.get("line_items", [])

    def _run_comparison(self, context: InvestigationContext) -> None:
        InvestigationStateMachine.transition(context.current_state, InvestigationState.COMPARING, context.step_count)
        delta_info = SpendDeltaAnalyzer.analyze(context)
        context.record_step(InvestigationState.COMPARING, delta_info)

    def _run_line_item_analysis(self, context: InvestigationContext) -> None:
        InvestigationStateMachine.transition(context.current_state, InvestigationState.CHECKING_LINE_ITEMS, context.step_count)
        matched_result = LineItemMatcher.match(context.baseline_line_items, context.target_line_items)
        context.record_step(InvestigationState.CHECKING_LINE_ITEMS, {
            "matched_pairs_count": len(matched_result["matched_pairs"]),
            "new_items_count": len(matched_result["new_items"]),
            "removed_items_count": len(matched_result["removed_items"]),
        })

        # Price changes
        InvestigationStateMachine.transition(context.current_state, InvestigationState.CHECKING_PRICE_CHANGE, context.step_count)
        price_findings = PriceChangeAnalyzer.analyze(matched_result["matched_pairs"])
        context.findings.extend(price_findings)
        context.record_step(InvestigationState.CHECKING_PRICE_CHANGE, {"price_findings_count": len(price_findings)})

        # Quantity changes & new items
        InvestigationStateMachine.transition(context.current_state, InvestigationState.CHECKING_QUANTITY_CHANGE, context.step_count)
        qty_findings = QuantityChangeAnalyzer.analyze(matched_result["matched_pairs"], matched_result["new_items"])
        context.findings.extend(qty_findings)
        context.record_step(InvestigationState.CHECKING_QUANTITY_CHANGE, {"qty_findings_count": len(qty_findings)})

    def _run_duplicate_check(self, context: InvestigationContext) -> None:
        InvestigationStateMachine.transition(context.current_state, InvestigationState.CHECKING_DUPLICATES, context.step_count)
        db: Session = self.session_factory()
        try:
            dup_findings = DuplicateChecker.check(db, context.organization_id, context.target_invoice_ids)
            context.findings.extend(dup_findings)
            context.record_step(InvestigationState.CHECKING_DUPLICATES, {"dup_findings_count": len(dup_findings)})
        finally:
            db.close()

    def _run_rule_check(self, context: InvestigationContext) -> None:
        InvestigationStateMachine.transition(context.current_state, InvestigationState.CHECKING_RULES, context.step_count)
        db: Session = self.session_factory()
        try:
            rule_findings, raw_violations = RuleChecker.check(db, context.organization_id, context.target_invoice_ids)
            context.findings.extend(rule_findings)
            context.rule_violations.extend(raw_violations)
            context.record_step(InvestigationState.CHECKING_RULES, {"rule_findings_count": len(rule_findings)})
        finally:
            db.close()

    def _run_anomaly_check(self, context: InvestigationContext) -> None:
        InvestigationStateMachine.transition(context.current_state, InvestigationState.CHECKING_ANOMALIES, context.step_count)
        db: Session = self.session_factory()
        try:
            anom_findings, raw_anomalies = AnomalyChecker.check(
                db, context.organization_id, context.vendor_id, context.target_invoice_ids
            )
            context.findings.extend(anom_findings)
            context.anomalies.extend(raw_anomalies)
            context.record_step(InvestigationState.CHECKING_ANOMALIES, {"anom_findings_count": len(anom_findings)})
        finally:
            db.close()

    async def _run_relationship_check(self, context: InvestigationContext) -> None:
        InvestigationStateMachine.transition(context.current_state, InvestigationState.CHECKING_RELATIONSHIPS, context.step_count)
        if context.vendor_id:
            res = await self.graph_tool.execute(
                step_id="graph_check",
                operation=ToolOperation.GET_VENDOR_NETWORK,
                arguments={"vendor_id": context.vendor_id},
                organization_id=context.organization_id,
            )
            if res.success and res.data:
                context.evidence.extend(res.evidence)
        context.record_step(InvestigationState.CHECKING_RELATIONSHIPS, {"graph_traced": bool(context.vendor_id)})

    async def _run_vector_evidence_collection(self, context: InvestigationContext) -> None:
        InvestigationStateMachine.transition(context.current_state, InvestigationState.COLLECTING_EVIDENCE, context.step_count)
        # Search for semantic context surrounding vendor items
        v_res = await self.vector_tool.execute(
            step_id="vector_ev",
            operation=ToolOperation.LINE_ITEM_SEARCH,
            arguments={"query": "infrastructure usage computing software services", "vendor_id": context.vendor_id, "top_k": 5},
            organization_id=context.organization_id,
        )
        if v_res.success and v_res.evidence:
            context.evidence.extend(v_res.evidence)
        context.record_step(InvestigationState.COLLECTING_EVIDENCE, {"evidence_count": len(context.evidence)})

    def _run_findings_synthesis(self, context: InvestigationContext) -> None:
        InvestigationStateMachine.transition(context.current_state, InvestigationState.GENERATING_FINDINGS, context.step_count)
        FindingEngine.synthesize(context)
        context.record_step(InvestigationState.GENERATING_FINDINGS, {
            "drivers_count": len(context.drivers),
            "unexplained_amount": str(context.unexplained_amount),
        })
