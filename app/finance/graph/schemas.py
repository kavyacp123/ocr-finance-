from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field


class GraphNode(BaseModel):
    """
    Representation of an entity node in the Financial Knowledge Graph.
    """
    id: str
    label: str
    properties: Dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    """
    Representation of a directed relationship edge in the Financial Knowledge Graph.
    """
    source_id: str
    target_id: str
    relation_type: str
    properties: Dict[str, Any] = Field(default_factory=dict)


class GraphSubgraph(BaseModel):
    """
    A connected component or subgraph returned from a graph query or path trace.
    """
    nodes: List[GraphNode] = Field(default_factory=list)
    edges: List[GraphEdge] = Field(default_factory=list)


class GraphStats(BaseModel):
    """
    High-level metrics on graph size and density.
    """
    total_nodes: int
    total_edges: int
    nodes_by_label: Dict[str, int] = Field(default_factory=dict)
    edges_by_type: Dict[str, int] = Field(default_factory=dict)


class SharedEntityResult(BaseModel):
    """
    Flags where multiple entities (e.g. Vendors) share a single identifier or bank account.
    """
    shared_node_id: str
    shared_label: str
    shared_properties: Dict[str, Any] = Field(default_factory=dict)
    connected_entity_ids: List[str] = Field(default_factory=list)
    connected_entity_names: List[str] = Field(default_factory=list)
