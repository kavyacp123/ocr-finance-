import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.finance.vector.schemas import VectorChunk


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_vector_search_api_endpoints(client):
    v_store = app.state.vector_store
    v_store.clear()

    # Seed chunks directly into vector store
    c1 = VectorChunk(
        chunk_id="chk_gpu_test",
        document_id="doc_gpu_invoice_01",
        organization_id="org_test_vapi",
        chunk_type="LINE_ITEM",
        text="A100 Tensor Core GPU Virtual Workstation Server",
        page_number=1,
        bbox=[100, 200, 800, 250],
        metadata={"vendor": "Lambda Labs"},
    )
    c2 = VectorChunk(
        chunk_id="chk_catering_test",
        document_id="doc_food_invoice_02",
        organization_id="org_test_vapi",
        chunk_type="LINE_ITEM",
        text="Executive lunch buffet and refreshments",
        page_number=1,
        bbox=[50, 150, 500, 200],
        metadata={"vendor": "Gourmet Catering"},
    )
    v_store.add_chunks([c1, c2])

    # 1. Test POST /search/semantic
    payload = {
        "query": "GPU server virtual workstation",
        "organization_id": "org_test_vapi",
        "top_k": 5,
    }
    res_search = client.post("/search/semantic", json=payload)
    assert res_search.status_code == 200
    s_data = res_search.json()
    assert s_data["total_results"] >= 1
    top_hit = s_data["results"][0]
    assert top_hit["document_id"] == "doc_gpu_invoice_01"
    assert top_hit["bbox"] == [100, 200, 800, 250]
    assert "A100" in top_hit["text"]

    # 2. Test GET /search/evidence/{document_id}
    res_ev = client.get("/search/evidence/doc_gpu_invoice_01?query=GPU")
    assert res_ev.status_code == 200
    ev_data = res_ev.json()
    assert ev_data["evidence_count"] >= 1
    assert ev_data["evidence"][0]["bbox"] == [100, 200, 800, 250]

    # 3. Test GET /search/stats
    res_stats = client.get("/search/stats")
    assert res_stats.status_code == 200
    stats = res_stats.json()
    assert stats["total_chunks"] >= 2
    assert stats["total_indexed_documents"] >= 2
