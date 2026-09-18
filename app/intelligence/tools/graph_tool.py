"""
Finance Knowledge Graph Tool
============================

WHY:   Relationship questions ("Which payments belong to invoices from AWS?",
       "Show POs connected to INV-100", "What bank account is used?") require
       graph traversal, NOT SQL JOINs and NOT LLM guesswork.

WHERE: Called by QueryExecutor when step.tool == ToolName.GRAPH.

WHAT IT RECEIVES: Operation name + arguments + authenticated organization_id.

WHAT IT OUTPUTS:  ToolResult containing nodes, edges, paths + Evidence objects.
"""

from typing import Any, Dict, List, Optional, Set

from app.finance.graph.base import BaseGraphAdapter
from app.finance.graph.schemas import GraphSubgraph
from app.intelligence.schemas import (
    ToolName,
    ToolOperation,
    ToolResult,
    Evidence,
    EvidenceSourceType,
)
from app.intelligence.tools.base import BaseFinanceTool
from app.utils.logging import logger


class FinanceGraphTool(BaseFinanceTool):
    """
    Approved Graph operations wrapping the Knowledge Graph adapter.
    """

    tool_name = ToolName.GRAPH
    supported_operations: Set[ToolOperation] = {
        ToolOperation.GET_INVOICE_RELATIONSHIPS,
        ToolOperation.GET_VENDOR_NETWORK,
        ToolOperation.GET_INVOICE_PO,
        ToolOperation.GET_INVOICE_PAYMENTS,
        ToolOperation.GET_VENDOR_BANK_ACCOUNTS,
        ToolOperation.GET_CONNECTED_DOCUMENTS,
        ToolOperation.GET_ENTITY_NEIGHBORHOOD,
        ToolOperation.FIND_PATH,
    }

    def __init__(self, graph_adapter: Optional[BaseGraphAdapter] = None):
        self.graph_adapter = graph_adapter

    async def _execute(
        self,
        step_id: str,
        operation: ToolOperation,
        arguments: dict,
        organization_id: str,
    ) -> ToolResult:
        if not self.graph_adapter:
            return ToolResult(
                step_id=step_id,
                tool=self.tool_name,
                operation=operation,
                success=False,
                error="Graph adapter not configured or unavailable",
                execution_time_ms=0,
            )

        if operation == ToolOperation.GET_INVOICE_RELATIONSHIPS:
            return self._get_invoice_relationships(step_id, arguments, organization_id)
        elif operation == ToolOperation.GET_VENDOR_NETWORK:
            return self._get_vendor_network(step_id, arguments, organization_id)
        elif operation == ToolOperation.GET_INVOICE_PO:
            return self._get_invoice_po(step_id, arguments, organization_id)
        elif operation == ToolOperation.GET_INVOICE_PAYMENTS:
            return self._get_invoice_payments(step_id, arguments, organization_id)
        elif operation == ToolOperation.GET_VENDOR_BANK_ACCOUNTS:
            return self._get_vendor_bank_accounts(step_id, arguments, organization_id)
        elif operation == ToolOperation.GET_CONNECTED_DOCUMENTS:
            return self._get_connected_documents(step_id, arguments, organization_id)
        elif operation == ToolOperation.GET_ENTITY_NEIGHBORHOOD:
            return self._get_neighborhood(step_id, arguments, organization_id)
        elif operation == ToolOperation.FIND_PATH:
            return self._find_path(step_id, arguments, organization_id)
        else:
            return ToolResult(
                step_id=step_id,
                tool=self.tool_name,
                operation=operation,
                success=False,
                error=f"Unhandled Graph operation: {operation.value}",
                execution_time_ms=0,
            )

    # ── Handlers ──────────────────────────────────────────────────────────

    def _get_invoice_relationships(self, step_id: str, args: dict, organization_id: str) -> ToolResult:
        inv_id = args.get("invoice_id")
        if not inv_id:
            return ToolResult(
                step_id=step_id,
                tool=self.tool_name,
                operation=ToolOperation.GET_INVOICE_RELATIONSHIPS,
                success=False,
                error="invoice_id required",
                execution_time_ms=0,
            )

        subgraph = self._get_scoped_subgraph(inv_id, 2, organization_id)
        if not subgraph.nodes:
            subgraph = self._get_scoped_subgraph(f"inv_{inv_id}", 2, organization_id)

        data = {
            "root": inv_id,
            "nodes": [n.model_dump() for n in subgraph.nodes],
            "edges": [e.model_dump() for e in subgraph.edges],
        }

        evidence = [
            Evidence(
                evidence_id=self._make_evidence_id(),
                source_type=EvidenceSourceType.GRAPH_PATH,
                invoice_id=inv_id,
                graph_path={
                    "nodes": [n.id for n in subgraph.nodes],
                    "edges": [f"{e.source_id}->{e.target_id}:{e.relation_type}" for e in subgraph.edges],
                },
                confidence=1.0,
                source_operation=ToolOperation.GET_INVOICE_RELATIONSHIPS.value,
            )
        ]

        return ToolResult(
            step_id=step_id,
            tool=self.tool_name,
            operation=ToolOperation.GET_INVOICE_RELATIONSHIPS,
            success=True,
            data=data,
            evidence=evidence,
            record_count=len(subgraph.nodes),
            execution_time_ms=0,
        )

    def _get_vendor_network(self, step_id: str, args: dict, organization_id: str) -> ToolResult:
        vendor_id = args.get("vendor_id")
        if not vendor_id:
            return ToolResult(
                step_id=step_id,
                tool=self.tool_name,
                operation=ToolOperation.GET_VENDOR_NETWORK,
                success=False,
                error="vendor_id required",
                execution_time_ms=0,
            )
        depth = args.get("depth", 2)
        subgraph = self._get_scoped_subgraph(vendor_id, depth, organization_id)
        if not subgraph.nodes and not vendor_id.startswith("vendor_"):
            subgraph = self._get_scoped_subgraph(f"vendor_{vendor_id}", depth, organization_id)

        data = {
            "vendor_id": vendor_id,
            "nodes": [n.model_dump() for n in subgraph.nodes],
            "edges": [e.model_dump() for e in subgraph.edges],
        }
        evidence = [
            Evidence(
                evidence_id=self._make_evidence_id(),
                source_type=EvidenceSourceType.GRAPH_PATH,
                vendor_id=vendor_id,
                graph_path={"node_count": len(subgraph.nodes), "edge_count": len(subgraph.edges)},
                confidence=1.0,
                source_operation=ToolOperation.GET_VENDOR_NETWORK.value,
            )
        ]
        return ToolResult(
            step_id=step_id,
            tool=self.tool_name,
            operation=ToolOperation.GET_VENDOR_NETWORK,
            success=True,
            data=data,
            evidence=evidence,
            record_count=len(subgraph.nodes),
            execution_time_ms=0,
        )

    def _get_invoice_po(self, step_id: str, args: dict, organization_id: str) -> ToolResult:
        inv_id = args.get("invoice_id")
        node_id = f"inv_{inv_id}" if not inv_id.startswith("inv_") else inv_id
        subgraph = self._get_scoped_subgraph(node_id, 1, organization_id)

        po_nodes = [n for n in subgraph.nodes if n.label in ("PurchaseOrder", "PO")]
        return ToolResult(
            step_id=step_id,
            tool=self.tool_name,
            operation=ToolOperation.GET_INVOICE_PO,
            success=True,
            data={"invoice_id": inv_id, "purchase_orders": [n.model_dump() for n in po_nodes]},
            evidence=[
                Evidence(
                    evidence_id=self._make_evidence_id(),
                    source_type=EvidenceSourceType.GRAPH_PATH,
                    invoice_id=inv_id,
                    po_id=po_nodes[0].id if po_nodes else None,
                    graph_path={"po_nodes": [n.id for n in po_nodes]},
                    confidence=1.0,
                    source_operation=ToolOperation.GET_INVOICE_PO.value,
                )
            ] if po_nodes else [],
            record_count=len(po_nodes),
            execution_time_ms=0,
        )

    def _get_invoice_payments(self, step_id: str, args: dict, organization_id: str) -> ToolResult:
        inv_id = args.get("invoice_id")
        node_id = f"inv_{inv_id}" if not inv_id.startswith("inv_") else inv_id
        subgraph = self._get_scoped_subgraph(node_id, 1, organization_id)

        pmt_nodes = [n for n in subgraph.nodes if n.label in ("Payment", "PMT")]
        return ToolResult(
            step_id=step_id,
            tool=self.tool_name,
            operation=ToolOperation.GET_INVOICE_PAYMENTS,
            success=True,
            data={"invoice_id": inv_id, "payments": [n.model_dump() for n in pmt_nodes]},
            evidence=[
                Evidence(
                    evidence_id=self._make_evidence_id(),
                    source_type=EvidenceSourceType.GRAPH_PATH,
                    invoice_id=inv_id,
                    payment_id=pmt_nodes[0].id if pmt_nodes else None,
                    graph_path={"payment_nodes": [n.id for n in pmt_nodes]},
                    confidence=1.0,
                    source_operation=ToolOperation.GET_INVOICE_PAYMENTS.value,
                )
            ] if pmt_nodes else [],
            record_count=len(pmt_nodes),
            execution_time_ms=0,
        )

    def _get_vendor_bank_accounts(self, step_id: str, args: dict, organization_id: str) -> ToolResult:
        vendor_id = args.get("vendor_id")
        node_id = f"vendor_{vendor_id}" if not vendor_id.startswith("vendor_") else vendor_id
        subgraph = self._get_scoped_subgraph(vendor_id, 1, organization_id)
        if not subgraph.nodes:
            subgraph = self._get_scoped_subgraph(node_id, 1, organization_id)

        bank_nodes = [n for n in subgraph.nodes if n.label in ("BankAccount", "Bank")]
        return ToolResult(
            step_id=step_id,
            tool=self.tool_name,
            operation=ToolOperation.GET_VENDOR_BANK_ACCOUNTS,
            success=True,
            data={"vendor_id": vendor_id, "bank_accounts": [n.model_dump() for n in bank_nodes]},
            record_count=len(bank_nodes),
            execution_time_ms=0,
        )

    def _get_connected_documents(self, step_id: str, args: dict, organization_id: str) -> ToolResult:
        entity_id = args.get("entity_id")
        depth = args.get("depth", 2)
        subgraph = self._get_scoped_subgraph(entity_id, depth, organization_id)
        return ToolResult(
            step_id=step_id,
            tool=self.tool_name,
            operation=ToolOperation.GET_CONNECTED_DOCUMENTS,
            success=True,
            data={
                "entity_id": entity_id,
                "nodes": [n.model_dump() for n in subgraph.nodes],
                "edges": [e.model_dump() for e in subgraph.edges],
            },
            record_count=len(subgraph.nodes),
            execution_time_ms=0,
        )

    def _get_neighborhood(self, step_id: str, args: dict, organization_id: str) -> ToolResult:
        node_id = args.get("node_id")
        depth = args.get("depth", 1)
        subgraph = self._get_scoped_subgraph(node_id, depth, organization_id)
        return ToolResult(
            step_id=step_id,
            tool=self.tool_name,
            operation=ToolOperation.GET_ENTITY_NEIGHBORHOOD,
            success=True,
            data={"node_id": node_id, "subgraph": subgraph.model_dump()},
            record_count=len(subgraph.nodes),
            execution_time_ms=0,
        )

    def _find_path(self, step_id: str, args: dict, organization_id: str) -> ToolResult:
        start_id = args.get("start_node_id")
        end_id = args.get("end_node_id")
        max_depth = args.get("max_depth", 4)
        paths = [
            path for path in self.graph_adapter.find_paths(start_id, end_id, max_depth=max_depth)
            if all(self._node_belongs_to_org(node_id, organization_id) for node_id in path)
        ]
        return ToolResult(
            step_id=step_id,
            tool=self.tool_name,
            operation=ToolOperation.FIND_PATH,
            success=True,
            data={"start": start_id, "end": end_id, "paths": paths},
            record_count=len(paths),
            execution_time_ms=0,
        )

    def _get_scoped_subgraph(self, node_id: str, depth: int, organization_id: str) -> GraphSubgraph:
        if not self._node_belongs_to_org(node_id, organization_id):
            return GraphSubgraph()
        subgraph = self.graph_adapter.get_subgraph(node_id, max_depth=depth)
        allowed_ids = {
            node.id
            for node in subgraph.nodes
            if node.properties.get("organization_id") == organization_id
        }
        return GraphSubgraph(
            nodes=[node for node in subgraph.nodes if node.id in allowed_ids],
            edges=[
                edge for edge in subgraph.edges
                if edge.source_id in allowed_ids and edge.target_id in allowed_ids
            ],
        )

    def _node_belongs_to_org(self, node_id: str, organization_id: str) -> bool:
        node = self.graph_adapter.get_node(node_id)
        return bool(node and node.properties.get("organization_id") == organization_id)
