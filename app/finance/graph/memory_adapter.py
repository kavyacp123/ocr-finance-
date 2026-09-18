import threading
from typing import Dict, Any, List, Optional
import networkx as nx

from app.finance.graph.base import BaseGraphAdapter
from app.finance.graph.schemas import (
    GraphNode,
    GraphEdge,
    GraphSubgraph,
    GraphStats,
    SharedEntityResult,
)


class NetworkXGraphAdapter(BaseGraphAdapter):
    """
    In-memory multi-directed knowledge graph implementation using NetworkX.
    Thread-safe with reentrant locking, supporting cycle-tolerant multi-hop traversals.
    """

    def __init__(self):
        self._graph = nx.MultiDiGraph()
        self._lock = threading.RLock()

    def upsert_node(self, node_id: str, label: str, properties: Dict[str, Any]) -> GraphNode:
        with self._lock:
            props = dict(properties)
            props["label"] = label
            props["id"] = node_id
            self._graph.add_node(node_id, **props)
            return GraphNode(id=node_id, label=label, properties=props)

    def upsert_edge(
        self, source_id: str, target_id: str, relation_type: str, properties: Dict[str, Any]
    ) -> GraphEdge:
        with self._lock:
            # Ensure endpoints exist as placeholder nodes if not already registered
            if not self._graph.has_node(source_id):
                self._graph.add_node(source_id, id=source_id, label="Entity")
            if not self._graph.has_node(target_id):
                self._graph.add_node(target_id, id=target_id, label="Entity")

            props = dict(properties)
            props["relation_type"] = relation_type
            props["source_id"] = source_id
            props["target_id"] = target_id

            # Check if this edge key exists, else add with relation_type as key
            self._graph.add_edge(source_id, target_id, key=relation_type, **props)
            return GraphEdge(source_id=source_id, target_id=target_id, relation_type=relation_type, properties=props)

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        with self._lock:
            if not self._graph.has_node(node_id):
                return None
            data = dict(self._graph.nodes[node_id])
            label = data.pop("label", "Entity")
            return GraphNode(id=node_id, label=label, properties=data)

    def get_subgraph(self, root_node_id: str, max_depth: int = 2) -> GraphSubgraph:
        with self._lock:
            if not self._graph.has_node(root_node_id):
                return GraphSubgraph()

            # Undirected view for symmetric neighborhood reachability up to max_depth
            undirected = self._graph.to_undirected(as_view=True)
            lengths = nx.single_source_shortest_path_length(undirected, root_node_id, cutoff=max_depth)
            sub_nodes = set(lengths.keys())

            nodes_list: List[GraphNode] = []
            for nid in sub_nodes:
                data = dict(self._graph.nodes[nid])
                lbl = data.pop("label", "Entity")
                nodes_list.append(GraphNode(id=nid, label=lbl, properties=data))

            edges_list: List[GraphEdge] = []
            sub_view = self._graph.subgraph(sub_nodes)
            for u, v, k, edata in sub_view.edges(data=True, keys=True):
                eprops = dict(edata)
                rel_type = eprops.pop("relation_type", str(k))
                edges_list.append(GraphEdge(source_id=u, target_id=v, relation_type=rel_type, properties=eprops))

            return GraphSubgraph(nodes=nodes_list, edges=edges_list)

    def find_paths(self, start_node_id: str, end_node_id: str, max_depth: int = 4) -> List[List[str]]:
        with self._lock:
            if not (self._graph.has_node(start_node_id) and self._graph.has_node(end_node_id)):
                return []
            try:
                # Convert to simple DiGraph to avoid multiedge duplicate path permutations
                simple_di = nx.DiGraph(self._graph)
                paths = list(nx.all_simple_paths(simple_di, source=start_node_id, target=end_node_id, cutoff=max_depth))
                return paths
            except nx.NetworkXNoPath:
                return []

    def find_shared_entities(
        self, entity_label: str, shared_target_label: str, min_connections: int = 2
    ) -> List[SharedEntityResult]:
        with self._lock:
            results: List[SharedEntityResult] = []

            # Identify all nodes with shared_target_label
            target_candidates = [
                nid for nid, data in self._graph.nodes(data=True)
                if data.get("label") == shared_target_label
            ]

            for tid in target_candidates:
                target_props = dict(self._graph.nodes[tid])
                tlabel = target_props.pop("label", shared_target_label)

                # Find all entities pointing to or connected to this target node with label == entity_label
                connected_entities: List[str] = []
                connected_names: List[str] = []

                # Look at in-edges (Entity -> SharedTarget) and out-edges (SharedTarget -> Entity)
                in_neighbors = set(self._graph.predecessors(tid))
                out_neighbors = set(self._graph.successors(tid))
                all_neighbors = in_neighbors.union(out_neighbors)

                for nid in all_neighbors:
                    ndata = self._graph.nodes[nid]
                    if ndata.get("label") == entity_label:
                        connected_entities.append(nid)
                        name = ndata.get("canonical_name") or ndata.get("name") or ndata.get("id") or nid
                        connected_names.append(name)

                if len(connected_entities) >= min_connections:
                    results.append(
                        SharedEntityResult(
                            shared_node_id=tid,
                            shared_label=tlabel,
                            shared_properties=target_props,
                            connected_entity_ids=connected_entities,
                            connected_entity_names=connected_names,
                        )
                    )

            return results

    def get_stats(self, organization_id: Optional[str] = None) -> GraphStats:
        with self._lock:
            nodes_by_label: Dict[str, int] = {}
            filtered_nodes = set()

            for nid, data in self._graph.nodes(data=True):
                if organization_id and data.get("organization_id") != organization_id:
                    continue
                filtered_nodes.add(nid)
                lbl = data.get("label", "Unknown")
                nodes_by_label[lbl] = nodes_by_label.get(lbl, 0) + 1

            edges_by_type: Dict[str, int] = {}
            total_edges = 0

            for u, v, k, data in self._graph.edges(data=True, keys=True):
                if organization_id:
                    u_org = self._graph.nodes[u].get("organization_id")
                    v_org = self._graph.nodes[v].get("organization_id")
                    if u_org != organization_id and v_org != organization_id:
                        continue
                total_edges += 1
                rtype = data.get("relation_type", str(k))
                edges_by_type[rtype] = edges_by_type.get(rtype, 0) + 1

            return GraphStats(
                total_nodes=len(filtered_nodes),
                total_edges=total_edges,
                nodes_by_label=nodes_by_label,
                edges_by_type=edges_by_type,
            )

    def clear(self, organization_id: Optional[str] = None) -> None:
        with self._lock:
            if not organization_id:
                self._graph.clear()
            else:
                nodes_to_remove = [
                    nid for nid, data in self._graph.nodes(data=True)
                    if data.get("organization_id") == organization_id
                ]
                self._graph.remove_nodes_from(nodes_to_remove)
