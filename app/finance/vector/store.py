import threading
from typing import List, Dict, Any, Optional
import numpy as np

from app.finance.vector.schemas import VectorChunk, SearchResult, EvidenceItem
from app.finance.vector.embeddings import BaseEmbeddingProvider, get_embedding_provider
from app.utils.logging import logger


class VectorStore:
    """
    Thread-safe in-memory vector index supporting incremental upserts,
    metadata filtering, and cosine similarity nearest-neighbor retrieval.
    """

    def __init__(self, embedder: Optional[BaseEmbeddingProvider] = None):
        self.embedder = embedder or get_embedding_provider()
        self._chunks: Dict[str, VectorChunk] = {}
        self._embeddings: List[np.ndarray] = []
        self._chunk_ids: List[str] = []
        self._matrix: Optional[np.ndarray] = None
        self._lock = threading.RLock()

    def add_chunks(self, chunks: List[VectorChunk]) -> int:
        if not chunks:
            return 0

        with self._lock:
            # Filter out chunks already present or replace them
            new_chunks = []
            for c in chunks:
                if c.chunk_id in self._chunks:
                    # Remove existing entry to update cleanly
                    idx = self._chunk_ids.index(c.chunk_id)
                    del self._chunk_ids[idx]
                    del self._embeddings[idx]
                self._chunks[c.chunk_id] = c
                new_chunks.append(c)

            if not new_chunks:
                return 0

            texts = [c.text for c in new_chunks]
            new_vectors = self.embedder.embed_texts(texts)

            for i, c in enumerate(new_chunks):
                self._chunk_ids.append(c.chunk_id)
                self._embeddings.append(new_vectors[i])

            if self._embeddings:
                self._matrix = np.vstack(self._embeddings)
            else:
                self._matrix = None

            logger.info(f"VECTOR_STORE: Indexed {len(new_chunks)} chunks (Total: {len(self._chunks)}).")
            return len(new_chunks)

    def search(
        self,
        query: str,
        organization_id: Optional[str] = None,
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[SearchResult]:
        with self._lock:
            if not self._chunks or self._matrix is None or len(self._chunk_ids) == 0:
                return []

            # 1. Embed query
            q_vec = self.embedder.embed_query(query)
            q_norm = np.linalg.norm(q_vec)
            if q_norm > 1e-9:
                q_vec = q_vec / q_norm

            # 2. Compute cosine similarities (matrix is normalized)
            # Dot product gives cosine similarity
            sims = np.dot(self._matrix, q_vec)

            # 3. Sort indices descending
            sorted_indices = np.argsort(-sims)

            results: List[SearchResult] = []
            for idx in sorted_indices:
                cid = self._chunk_ids[idx]
                chunk = self._chunks[cid]
                score = float(sims[idx])

                # Threshold filtering: score must be positive
                if score <= 0.0:
                    continue

                # Org filtering
                if organization_id and chunk.organization_id != organization_id:
                    continue

                # Metadata attribute filtering
                if filters:
                    match = True
                    for k, v in filters.items():
                        if k == "chunk_type" and chunk.chunk_type != v:
                            match = False
                            break
                        elif k == "document_id" and chunk.document_id != v:
                            match = False
                            break
                        elif k in chunk.metadata and chunk.metadata[k] != v:
                            match = False
                            break
                    if not match:
                        continue

                results.append(
                    SearchResult(
                        chunk_id=chunk.chunk_id,
                        document_id=chunk.document_id,
                        chunk_type=chunk.chunk_type,
                        text=chunk.text,
                        similarity_score=round(score, 4),
                        page_number=chunk.page_number,
                        region_id=chunk.region_id,
                        bbox=chunk.bbox,
                        metadata=chunk.metadata,
                    )
                )

                if len(results) >= top_k:
                    break

            return results

    def get_evidence(self, document_id: str, query: str, top_k: int = 5) -> List[EvidenceItem]:
        """
        Retrieves top visual evidence chunks matching query within a specific document.
        """
        results = self.search(
            query=query,
            top_k=top_k,
            filters={"document_id": document_id},
        )
        evidence: List[EvidenceItem] = []
        for r in results:
            if r.bbox:
                evidence.append(
                    EvidenceItem(
                        document_id=r.document_id,
                        page_number=r.page_number,
                        region_id=r.region_id,
                        bbox=r.bbox,
                        matched_text=r.text,
                        similarity_score=r.similarity_score,
                        context=f"{r.chunk_type}: {r.text[:120]}",
                    )
                )
        return evidence

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            doc_ids = {c.document_id for c in self._chunks.values()}
            return {
                "total_chunks": len(self._chunks),
                "total_indexed_documents": len(doc_ids),
                "dimension": self.embedder.dimension if hasattr(self.embedder, "dimension") else 0,
            }

    def clear(self) -> None:
        with self._lock:
            self._chunks.clear()
            self._embeddings.clear()
            self._chunk_ids.clear()
            self._matrix = None
