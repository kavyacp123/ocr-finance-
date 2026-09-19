import json

import pytest
from PIL import Image

from app.config import settings
from app.engine.ocr_space_client import OCRSpaceClient, OCRSpaceError
from app.engine.upload_preprocessor import UploadCompressionError


class FakeResponse:
    is_error = False

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "OCRExitCode": 1,
            "IsErroredOnProcessing": False,
            "ParsedResults": [
                {"ParsedText": "TAX INVOICE\nInvoice No: INV-1\nTotal: 100"}
            ],
        }


class FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, *args, **kwargs):
        return FakeResponse()


@pytest.mark.asyncio
async def test_ocr_space_response_is_adapted(monkeypatch, tmp_path):
    image_path = tmp_path / "invoice.png"
    Image.new("RGB", (800, 1000), "white").save(image_path)
    monkeypatch.setattr(settings, "OCR_SPACE_API_KEY", "test-key")
    monkeypatch.setattr("app.engine.ocr_space_client.httpx.AsyncClient", FakeAsyncClient)

    result = await OCRSpaceClient().process_document(str(image_path), "invoice.png")

    assert result.page_count == 1
    assert result.pages[0].regions[0].clean_content.startswith("TAX INVOICE")
    assert result.engine.inference_engine == "OCR.Space API"


def test_ocr_space_rejects_files_over_limit(monkeypatch, tmp_path):
    image_path = tmp_path / "large.png"
    Image.new("RGB", (20, 20), "white").save(image_path)
    monkeypatch.setattr(settings, "OCR_SPACE_MAX_FILE_BYTES", 10)

    with pytest.raises(UploadCompressionError, match="could not be compressed"):
        import asyncio
        asyncio.run(OCRSpaceClient().process_document(str(image_path), "large.png"))
