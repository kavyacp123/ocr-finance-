import json
import mimetypes
import time
from pathlib import Path
from typing import List, Optional

import fitz
import httpx
from PIL import Image

from app.config import settings
from app.engine.upload_preprocessor import UploadCompressionError, prepare_upload
from app.models import (
    BoundingBox,
    DocumentResult,
    EngineMetadata,
    FullPageOCRResult,
    PageResult,
    ProcessingMetadata,
    Region,
)
from app.utils.files import generate_document_id
from app.utils.logging import logger


class OCRSpaceError(RuntimeError):
    """Raised when OCR.Space rejects a document or returns an OCR error."""


class OCRSpaceClient:
    async def process_document(
        self,
        file_path: str,
        filename: Optional[str] = None,
        document_id: Optional[str] = None,
        output_dir: Optional[str] = None,
        save_debug: bool = False,
    ) -> DocumentResult:
        source_path = Path(file_path)
        prepared = prepare_upload(source_path)
        path = prepared.path
        file_size = path.stat().st_size
        if file_size > settings.OCR_SPACE_MAX_FILE_BYTES:
            raise OCRSpaceError(
                f"OCR.Space accepts files up to {settings.OCR_SPACE_MAX_FILE_BYTES} bytes; "
                f"received {file_size} bytes."
            )

        if not settings.OCR_SPACE_API_KEY:
            raise OCRSpaceError("OCR_SPACE_API_KEY is not configured.")

        page_sizes = self._page_sizes(path)
        started = time.perf_counter()
        payload = {
            "language": settings.OCR_SPACE_LANGUAGE,
            "isOverlayRequired": "false",
            "OCREngine": "2",
        }
        headers = {"apikey": settings.OCR_SPACE_API_KEY}
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        try:
            async with httpx.AsyncClient(timeout=settings.OCR_SPACE_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    settings.OCR_SPACE_URL,
                    headers=headers,
                    data=payload,
                    files={"file": (path.name, path.read_bytes(), content_type)},
                )
                if response.is_error:
                    detail = response.text[:500].strip()
                    raise OCRSpaceError(
                        f"OCR.Space returned HTTP {response.status_code}"
                        + (f": {detail}" if detail else ".")
                    )
                result = response.json()
        except httpx.HTTPError as exc:
            raise OCRSpaceError(f"OCR.Space request failed: {exc}") from exc
        except ValueError as exc:
            raise OCRSpaceError("OCR.Space returned invalid JSON.") from exc
        finally:
            prepared.cleanup()

        if result.get("IsErroredOnProcessing") or str(result.get("OCRExitCode", 1)) != "1":
            messages = result.get("ErrorMessage") or result.get("ErrorDetails") or "Unknown OCR.Space error"
            if isinstance(messages, list):
                messages = "; ".join(str(message) for message in messages)
            raise OCRSpaceError(f"OCR.Space rejected the document: {messages}")

        parsed_pages = result.get("ParsedResults") or []
        if not parsed_pages:
            raise OCRSpaceError("OCR.Space returned no parsed pages.")

        pages: List[PageResult] = []
        markdown_pages: List[str] = []
        for page_number, parsed_page in enumerate(parsed_pages, start=1):
            text = str(parsed_page.get("ParsedText") or "").strip()
            if not text:
                continue
            width, height = page_sizes[min(page_number - 1, len(page_sizes) - 1)]
            region = Region(
                id=f"p{page_number}_fullpage",
                page_number=page_number,
                region_type="text",
                reading_order=1,
                bbox=BoundingBox(x1=0, y1=0, x2=width, y2=height),
                raw_ocr_output=text,
                clean_content=text,
                processing_status="success",
            )
            pages.append(
                PageResult(
                    page_number=page_number,
                    width=width,
                    height=height,
                    full_page_ocr=FullPageOCRResult(text=text),
                    regions=[region],
                )
            )
            markdown_pages.append(text)

        if not pages:
            raise OCRSpaceError("OCR.Space returned no text for the document.")

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        logger.info("OCR_CLIENT: OCR.Space processed %s page(s).", len(pages))
        document_result = DocumentResult(
            document_id=document_id or generate_document_id(),
            filename=filename or path.name,
            page_count=len(pages),
            processing_time_ms=round(elapsed_ms, 2),
            engine=EngineMetadata(
                layout_model="OCR.Space",
                ocr_model=f"OCR.Space {settings.OCR_SPACE_LANGUAGE}",
                inference_engine="OCR.Space API",
            ),
            pages=pages,
            markdown="\n\n".join(markdown_pages),
            metadata=ProcessingMetadata(
                processing_time_ms=round(elapsed_ms, 2),
                ocr_inference_time_ms=round(elapsed_ms, 2),
                page_count=len(pages),
                total_regions=len(pages),
                successful_regions=len(pages),
            ),
        )
        if save_debug and output_dir:
            output_path = Path(output_dir) / document_result.document_id
            output_path.mkdir(parents=True, exist_ok=True)
            (output_path / "document.json").write_text(
                json.dumps(document_result.model_dump(), indent=2), encoding="utf-8"
            )
            (output_path / "document.md").write_text(document_result.markdown, encoding="utf-8")
        return document_result

    @staticmethod
    def _page_sizes(path: Path) -> List[tuple[int, int]]:
        if path.suffix.lower() == ".pdf":
            with fitz.open(path) as document:
                return [
                    (max(1, round(page.rect.width)), max(1, round(page.rect.height)))
                    for page in document
                ]

        with Image.open(path) as image:
            return [(max(1, image.width), max(1, image.height))]