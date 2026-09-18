from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from app.finance.graph.schemas import (
    GraphNode,
    GraphEdge,
    GraphSubgraph,
    GraphStats,
    SharedEntityResult,
)


class BaseGraphAdapter(ABC):
    """
    Abstract interface for financial knowledge graph storage and traversal engines.
    """

    @abstractmethod
    def upsert_node(self, node_id: str, label: str, properties: Dict[str, Any]) -> GraphNode:
        """
        Inserts or updates a node in the graph.
        """
        pass

    @abstractmethod
    def upsert_edge(
        self, source_id: str, target_id: str, relation_type: str, properties: Dict[str, Any]
    ) -> GraphEdge:
        """
        Inserts or updates a directed relationship edge between two nodes.
        """
        pass

    @abstractmethod
    def get_node(self, node_id: str) -> Optional[GraphNode]:
        """
        Retrieves a node by its identifier.
        """
        pass

    @abstractmethod
    def get_subgraph(self, root_node_id: str, max_depth: int = 2) -> GraphSubgraph:
        """
        Extracts the ego-graph (subgraph) centered at root_node_id up to max_depth hops.
        """
        pass

    @abstractmethod
    def find_paths(self, start_node_id: str, end_node_id: str, max_depth: int = 4) -> List[List[str]]:
        """
        Finds all simple paths between two nodes up to max_depth.
        """
        pass

    @abstractmethod
    def find_shared_entities(
        self, entity_label: str, shared_target_label: str, min_connections: int = 2
    ) -> List[SharedEntityResult]:
        """
        Finds target nodes of type shared_target_label that are connected to >= min_connections distinct entity_label nodes.
        """
        pass

    @abstractmethod
    def get_stats(self, organization_id: Optional[str] = None) -> GraphStats:
        """
        Returns graph size, node counts by label, and edge counts by type.
        """
        pass

    @abstractmethod
    def clear(self, organization_id: Optional[str] = None) -> None:
        """
        Clears all nodes and edges (optionally scoped to organization_id).
        """
        pass
