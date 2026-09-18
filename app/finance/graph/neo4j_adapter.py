import json
from typing import Dict, Any, List, Optional
from app.config import settings
from app.finance.graph.base import BaseGraphAdapter
from app.finance.graph.schemas import (
    GraphNode,
    GraphEdge,
    GraphSubgraph,
    GraphStats,
    SharedEntityResult,
)
from app.utils.logging import logger


class Neo4jGraphAdapter(BaseGraphAdapter):
    """
    Neo4j Bolt driver adapter. Gracefully checks connectivity, handles Cypher queries,
    and falls back safely if Neo4j is unavailable or driver is not installed.
    """

    def __init__(self, uri: str = settings.NEO4J_URI, user: str = settings.NEO4J_USER, password: str = settings.NEO4J_PASSWORD):
        self.uri = uri
        self.user = user
        self.password = password
        self._driver = None
        self._available = False
        self._init_driver()

    def _init_driver(self):
        try:
            import neo4j
            self._driver = neo4j.GraphDatabase.driver(self.uri, auth=(self.user, self.password))
            self._driver.verify_connectivity()
            self._available = True
            logger.info("NEO4J_INIT: Connected to Neo4j graph database.")
        except Exception as e:
            self._available = False
            logger.warning(f"NEO4J_INIT: Neo4j not reachable ({e}). Will raise on direct use if active backend.")

    @property
    def is_available(self) -> bool:
        return self._available

    def upsert_node(self, node_id: str, label: str, properties: Dict[str, Any]) -> GraphNode:
        if not self._available:
            raise RuntimeError("Neo4j is not connected.")
        props = dict(properties)
        props["id"] = node_id
        cypher = f"MERGE (n:{label} {{id: $id}}) SET n += $props RETURN n"
        with self._driver.session() as session:
            session.run(cypher, id=node_id, props=props)
        return GraphNode(id=node_id, label=label, properties=props)

    def upsert_edge(
        self, source_id: str, target_id: str, relation_type: str, properties: Dict[str, Any]
    ) -> GraphEdge:
        if not self._available:
            raise RuntimeError("Neo4j is not connected.")
        cypher = (
            f"MATCH (s {{id: $source_id}}), (t {{id: $target_id}}) "
            f"MERGE (s)-[r:{relation_type}]->(t) "
            f"SET r += $props "
            f"RETURN r"
        )
        with self._driver.session() as session:
            session.run(cypher, source_id=source_id, target_id=target_id, props=properties)
        return GraphEdge(source_id=source_id, target_id=target_id, relation_type=relation_type, properties=properties)

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        if not self._available:
            raise RuntimeError("Neo4j is not connected.")
        cypher = "MATCH (n {id: $id}) RETURN labels(n) as labels, properties(n) as props"
        with self._driver.session() as session:
            res = session.run(cypher, id=node_id).single()
            if not res:
                return None
            labels = res["labels"]
            props = res["props"]
            label = labels[0] if labels else "Entity"
            return GraphNode(id=node_id, label=label, properties=props)

    def get_subgraph(self, root_node_id: str, max_depth: int = 2) -> GraphSubgraph:
        if not self._available:
            raise RuntimeError("Neo4j is not connected.")
        cypher = (
            f"MATCH path = (root {{id: $root_id}})-[*1..{max_depth}]-(other) "
            f"RETURN nodes(path) as nodes, relationships(path) as rels"
        )
        nodes_dict = {}
        edges_list = []
        with self._driver.session() as session:
            records = session.run(cypher, root_id=root_node_id)
            for rec in records:
                for n in rec["nodes"]:
                    nid = n["id"]
                    if nid not in nodes_dict:
                        lbl = list(n.labels)[0] if n.labels else "Entity"
                        nodes_dict[nid] = GraphNode(id=nid, label=lbl, properties=dict(n))
                for r in rec["rels"]:
                    edges_list.append(
                        GraphEdge(
                            source_id=r.start_node["id"],
                            target_id=r.end_node["id"],
                            relation_type=r.type,
                            properties=dict(r),
                        )
                    )
        return GraphSubgraph(nodes=list(nodes_dict.values()), edges=edges_list)

    def find_paths(self, start_node_id: str, end_node_id: str, max_depth: int = 4) -> List[List[str]]:
        if not self._available:
            raise RuntimeError("Neo4j is not connected.")
        cypher = (
            f"MATCH p = (s {{id: $start_id}})-[*1..{max_depth}]->(e {{id: $end_id}}) "
            f"RETURN [n in nodes(p) | n.id] as path_ids"
        )
        with self._driver.session() as session:
            records = session.run(cypher, start_id=start_node_id, end_id=end_node_id)
            return [r["path_ids"] for r in records]

    def find_shared_entities(
        self, entity_label: str, shared_target_label: str, min_connections: int = 2
    ) -> List[SharedEntityResult]:
        if not self._available:
            raise RuntimeError("Neo4j is not connected.")
        cypher = (
            f"MATCH (e:{entity_label})--(s:{shared_target_label}) "
            f"WITH s, collect(DISTINCT e.id) as entity_ids, collect(DISTINCT coalesce(e.canonical_name, e.name, e.id)) as entity_names "
            f"WHERE size(entity_ids) >= $min_conn "
            f"RETURN s.id as shared_id, labels(s) as labels, properties(s) as props, entity_ids, entity_names"
        )
        results = []
        with self._driver.session() as session:
            records = session.run(cypher, min_conn=min_connections)
            for r in records:
                lbl = r["labels"][0] if r["labels"] else shared_target_label
                results.append(
                    SharedEntityResult(
                        shared_node_id=r["shared_id"],
                        shared_label=lbl,
                        shared_properties=r["props"],
                        connected_entity_ids=r["entity_ids"],
                        connected_entity_names=r["entity_names"],
                    )
                )
        return results

    def get_stats(self, organization_id: Optional[str] = None) -> GraphStats:
        if not self._available:
            raise RuntimeError("Neo4j is not connected.")
        where_clause = "WHERE n.organization_id = $org_id" if organization_id else ""
        cypher = f"MATCH (n) {where_clause} RETURN count(n) as node_count"
        with self._driver.session() as session:
            total_nodes = session.run(cypher, org_id=organization_id).single()["node_count"]
            total_edges = session.run("MATCH ()-[r]->() RETURN count(r) as edge_count").single()["edge_count"]
        return GraphStats(total_nodes=total_nodes, total_edges=total_edges)

    def clear(self, organization_id: Optional[str] = None) -> None:
        if not self._available:
            return
        with self._driver.session() as session:
            if organization_id:
                session.run("MATCH (n {organization_id: $org}) DETACH DELETE n", org=organization_id)
            else:
                session.run("MATCH (n) DETACH DELETE n")
