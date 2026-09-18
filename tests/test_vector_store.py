import pytest
from app.finance.vector.schemas import VectorChunk
from app.finance.vector.store import VectorStore
from app.finance.vector.embeddings import FastEmbeddingProvider


def test_vector_store_add_and_search():
    embedder = FastEmbeddingProvider(dimension=128)
    store = VectorStore(embedder=embedder)

    c1 = VectorChunk(
        chunk_id="c1",
        document_id="doc_1",
        organization_id="org_a",
        chunk_type="LINE_ITEM",
        text="Kubernetes Cluster Control Plane Management Fee",
        page_number=1,
        bbox=[10, 20, 300, 50],
        metadata={"category": "infrastructure"},
    )
    c2 = VectorChunk(
        chunk_id="c2",
        document_id="doc_2",
        organization_id="org_a",
        chunk_type="LINE_ITEM",
        text="Office desk ergonomic chairs and furniture",
        page_number=1,
        bbox=[20, 50, 400, 100],
        metadata={"category": "office_supplies"},
    )
    c3 = VectorChunk(
        chunk_id="c3",
        document_id="doc_3",
        organization_id="org_b",
        chunk_type="LINE_ITEM",
        text="Cloud Database Storage Volume",
        page_number=1,
        bbox=[50, 50, 500, 100],
        metadata={"category": "infrastructure"},
    )

    added = store.add_chunks([c1, c2, c3])
    assert added == 3

    # 1. Search for cloud kubernetes infrastructure
    res = store.search(query="kubernetes cloud", organization_id="org_a")
    assert len(res) >= 1
    assert res[0].chunk_id == "c1"
    assert res[0].similarity_score > 0.3

    # 2. Metadata filter check
    res_filtered = store.search(
        query="cloud storage",
        organization_id="org_b",
    )
    assert len(res_filtered) == 1
    assert res_filtered[0].chunk_id == "c3"

    # 3. Evidence retrieval
    evidence = store.get_evidence(document_id="doc_1", query="kubernetes")
    assert len(evidence) == 1
    assert evidence[0].bbox == [10, 20, 300, 50]
    assert "Kubernetes" in evidence[0].matched_text


def test_vector_store_restores_persisted_chunks(tmp_path):
    index_path = tmp_path / "vector_index.json"
    chunk = VectorChunk(
        chunk_id="persisted_1",
        document_id="doc_persisted",
        organization_id="org_persisted",
        chunk_type="DOCUMENT_TEXT",
        text="Sonal Enterprises invoice 107",
        page_number=1,
    )
    VectorStore(
        embedder=FastEmbeddingProvider(dimension=128),
        persist_path=str(index_path),
    ).add_chunks([chunk])

    restored = VectorStore(
        embedder=FastEmbeddingProvider(dimension=128),
        persist_path=str(index_path),
    )

    assert restored.get_stats()["total_chunks"] == 1
    results = restored.search("invoice 107", organization_id="org_persisted")
    assert results[0].chunk_id == "persisted_1"
