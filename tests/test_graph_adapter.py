import pytest
from app.finance.graph.memory_adapter import NetworkXGraphAdapter


def test_memory_adapter_node_and_edge_upsert():
    adapter = NetworkXGraphAdapter()

    # Add Nodes
    n1 = adapter.upsert_node(
        node_id="ven_1",
        label="Vendor",
        properties={"canonical_name": "CloudScale Inc", "organization_id": "test_org"},
    )
    assert n1.id == "ven_1"
    assert n1.label == "Vendor"

    n2 = adapter.upsert_node(
        node_id="inv_1",
        label="Invoice",
        properties={"invoice_number": "INV-100", "total_amount": 5000.0, "organization_id": "test_org"},
    )
    assert n2.id == "inv_1"

    # Add Edge
    edge = adapter.upsert_edge(
        source_id="ven_1",
        target_id="inv_1",
        relation_type="ISSUED",
        properties={"organization_id": "test_org"},
    )
    assert edge.source_id == "ven_1"
    assert edge.target_id == "inv_1"
    assert edge.relation_type == "ISSUED"

    stats = adapter.get_stats(organization_id="test_org")
    assert stats.total_nodes == 2
    assert stats.total_edges == 1
    assert stats.nodes_by_label.get("Vendor") == 1
    assert stats.nodes_by_label.get("Invoice") == 1
    assert stats.edges_by_type.get("ISSUED") == 1


def test_memory_adapter_subgraph_extraction():
    adapter = NetworkXGraphAdapter()

    # Vendor -> Invoice -> PO
    adapter.upsert_node("ven_a", "Vendor", {"canonical_name": "Vendor A"})
    adapter.upsert_node("inv_a", "Invoice", {"invoice_number": "INV-A"})
    adapter.upsert_node("po_a", "PurchaseOrder", {"po_number": "PO-A"})

    adapter.upsert_edge("ven_a", "inv_a", "ISSUED", {})
    adapter.upsert_edge("inv_a", "po_a", "REFERENCES_PO", {})

    # Ego-subgraph from inv_a with depth=1 should capture all 3 nodes
    subgraph = adapter.get_subgraph("inv_a", max_depth=1)
    node_ids = {n.id for n in subgraph.nodes}
    assert node_ids == {"ven_a", "inv_a", "po_a"}
    assert len(subgraph.edges) == 2


def test_memory_adapter_path_finding_and_cycles():
    adapter = NetworkXGraphAdapter()

    # A -> B -> C and cycle C -> A
    adapter.upsert_node("A", "Node", {})
    adapter.upsert_node("B", "Node", {})
    adapter.upsert_node("C", "Node", {})

    adapter.upsert_edge("A", "B", "NEXT", {})
    adapter.upsert_edge("B", "C", "NEXT", {})
    adapter.upsert_edge("C", "A", "CYCLE", {})

    paths = adapter.find_paths("A", "C", max_depth=3)
    assert len(paths) == 1
    assert paths[0] == ["A", "B", "C"]


def test_memory_adapter_shared_entities():
    adapter = NetworkXGraphAdapter()

    # Two vendors sharing one BankAccount node
    adapter.upsert_node("ven_1", "Vendor", {"canonical_name": "Vendor 1"})
    adapter.upsert_node("ven_2", "Vendor", {"canonical_name": "Vendor 2"})
    adapter.upsert_node("bank_shared", "BankAccount", {"account_number": "9988776655"})

    adapter.upsert_edge("ven_1", "bank_shared", "USES_BANK_ACCOUNT", {})
    adapter.upsert_edge("ven_2", "bank_shared", "USES_BANK_ACCOUNT", {})

    shared = adapter.find_shared_entities(
        entity_label="Vendor",
        shared_target_label="BankAccount",
        min_connections=2,
    )
    assert len(shared) == 1
    assert shared[0].shared_node_id == "bank_shared"
    assert set(shared[0].connected_entity_ids) == {"ven_1", "ven_2"}
