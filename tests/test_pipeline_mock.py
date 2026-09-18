import pytest
import asyncio
from PIL import Image, ImageDraw
from pathlib import Path

from app.engine.pipeline import OCREngine
from app.engine.vlm_client import MockOCRClient


@pytest.mark.asyncio
async def test_pipeline_end_to_end_mock(tmp_path):
    # 1. Create a synthetic test image
    img_path = tmp_path / "sample_doc.png"
    img = Image.new("RGB", (600, 800), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((50, 50), "ANNUAL FINANCIAL REPORT", fill="black")
    draw.text((50, 150), "This is paragraph text in section one.", fill="black")
    img.save(img_path)

    # 2. Instantiate pipeline with MockOCRClient
    mock_client = MockOCRClient(latency_ms=10.0)
    engine = OCREngine(vlm_client=mock_client)

    out_dir = tmp_path / "outputs"
    res = await engine.process_document(
        file_path=str(img_path),
        output_dir=str(out_dir),
        save_debug=True
    )

    assert res.document_id is not None
    assert res.page_count == 1
    assert len(res.pages) == 1
    assert len(res.pages[0].regions) >= 1
    assert res.markdown != ""

    doc_base = out_dir / res.document_id
    assert (doc_base / "document.json").exists()
    assert (doc_base / "document.md").exists()
    assert (doc_base / "overlays").exists()
    assert (doc_base / "crops").exists()
