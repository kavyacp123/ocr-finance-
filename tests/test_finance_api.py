import io
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings
from app.database.session import init_db


@pytest.fixture(scope="module", autouse=True)
def setup_test_environment():
    old_provider = settings.OCR_PROVIDER
    old_mock = settings.OCR_MOCK_MODE
    settings.OCR_PROVIDER = "local"
    settings.OCR_MOCK_MODE = True
    init_db()
    yield
    settings.OCR_PROVIDER = old_provider
    settings.OCR_MOCK_MODE = old_mock


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_health_check_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("ok", "degraded")
    assert "layout_engine" in data
    assert "inference_engine" in data
    assert isinstance(data["vllm_reachable"], bool)


def test_config_endpoint(client):
    resp = client.get("/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "pdf_dpi" in data


def test_list_invoices_endpoint(client):
    resp = client.get("/invoices?organization_id=test_api_org")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_count" in data
    assert "invoices" in data
    assert isinstance(data["invoices"], list)


def test_finance_process_endpoint_mock(client):
    # Create a small blank image in memory
    img = Image.new("RGB", (600, 800), color=(255, 255, 255))
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format="PNG")
    img_bytes = img_byte_arr.getvalue()

    response = client.post(
        "/finance/process?organization_id=test_api_org",
        files={"file": ("invoice_sample.png", img_bytes, "image/png")},
    )
    assert response.status_code == 200
    data = response.json()

    assert "document_id" in data
    assert data["organization_id"] == "test_api_org"
    assert "validation" in data
    assert "line_items" in data

    # Verify that the invoice was persisted and is returned in GET /invoices
    list_resp = client.get("/invoices?organization_id=test_api_org")
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert list_data["total_count"] >= 1

    # Verify GET /invoices/{id}
    saved_inv_id = list_data["invoices"][0]["id"]
    detail_resp = client.get(f"/invoices/{saved_inv_id}?organization_id=test_api_org")
    assert detail_resp.status_code == 200
    detail_data = detail_resp.json()
    assert detail_data["id"] == saved_inv_id
    assert "line_items" in detail_data
    assert "validation_issues" in detail_data
