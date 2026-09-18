from app.config import settings
from app.finance.graph.base import BaseGraphAdapter
from app.finance.graph.memory_adapter import NetworkXGraphAdapter
from app.finance.graph.neo4j_adapter import Neo4jGraphAdapter
from app.utils.logging import logger


def get_graph_adapter() -> BaseGraphAdapter:
    """
    Factory creating the active graph engine adapter based on configuration.
    Falls back gracefully to NetworkXGraphAdapter if Neo4j is unavailable.
    """
    if settings.GRAPH_BACKEND.lower() == "neo4j":
        try:
            adapter = Neo4jGraphAdapter()
            if adapter.is_available:
                return adapter
            logger.warning("GRAPH_FACTORY: Neo4j backend requested but unavailable. Falling back to NetworkX.")
        except Exception as e:
            logger.warning(f"GRAPH_FACTORY: Neo4j initialization error: {e}. Falling back to NetworkX.")

    return NetworkXGraphAdapter()
