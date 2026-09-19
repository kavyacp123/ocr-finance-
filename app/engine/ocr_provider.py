import json
import time
from pathlib import Path
from typing import List, Optional

from app.config import settings
from app.engine.upload_preprocessor import DIRECT_TEXT_EXTENSIONS, extract_text
from app.engine.ocr_space_client import OCRSpaceClient
from app.engine.pipeline import OCREngine
from app.models import (
    BoundingBox,
    DocumentResult,
    EngineMetadata,
    FullPageOCRResult,
    PageResult,
    ProcessingMetadata,
    Region,
)


async def process_document(
    engine: OCREngine,
    file_path: str,
    filename: str,
    output_dir: str,
    save_debug: bool,
    document_id: Optional[str] = None,
) -> DocumentResult:
    suffix = Path(file_path).suffix.lower()
    if suffix in DIRECT_TEXT_EXTENSIONS:
        return _process_structured_text(
            file_path=file_path,
            filename=filename,
            output_dir=output_dir,
            save_debug=save_debug,
            document_id=document_id,
        )
    if settings.OCR_PROVIDER == "ocr_space":
        return await OCRSpaceClient().process_document(
            file_path=file_path,
            filename=filename,
            document_id=document_id,
            output_dir=output_dir,
            save_debug=save_debug,
        )
    return await engine.process_document(
        file_path=file_path,
        output_dir=output_dir,
        save_debug=save_debug,
    )


def _process_structured_text(
    file_path: str,
    filename: str,
    output_dir: str,
    save_debug: bool,
    document_id: Optional[str],
) -> DocumentResult:
    started = time.perf_counter()
    text = extract_text(Path(file_path)).strip()
    if not text:
        raise ValueError(f"The uploaded {Path(filename).suffix} file contains no readable text.")

    pages: List[PageResult] = []
    lines = text.splitlines()
    for page_number, start in enumerate(range(0, len(lines), 65), start=1):
        page_text = "\n".join(lines[start:start + 65]).strip()
        if not page_text:
            continue
        region = Region(
            id=f"p{page_number}_fullpage",
            page_number=page_number,
            region_type="text",
            reading_order=1,
            bbox=BoundingBox(x1=0, y1=0, x2=1200, y2=1600),
            raw_ocr_output=page_text,
            clean_content=page_text,
            processing_status="success",
        )
        pages.append(
            PageResult(
                page_number=page_number,
                width=1200,
                height=1600,
                full_page_ocr=FullPageOCRResult(text=page_text),
                regions=[region],
            )
        )

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    result = DocumentResult(
        document_id=document_id or f"direct_{int(time.time() * 1000)}",
        filename=filename,
        page_count=len(pages),
        processing_time_ms=round(elapsed_ms, 2),
        engine=EngineMetadata(
            layout_model="Direct text extraction",
            ocr_model="Structured document parser",
            inference_engine="Local parser",
        ),
        pages=pages,
        markdown="\n\n".join(page.full_page_ocr.text or "" for page in pages),
        metadata=ProcessingMetadata(
            processing_time_ms=round(elapsed_ms, 2),
            page_count=len(pages),
            total_regions=len(pages),
            successful_regions=len(pages),
        ),
    )
    if save_debug:
        output_path = Path(output_dir) / result.document_id
        output_path.mkdir(parents=True, exist_ok=True)
        (output_path / "document.json").write_text(
            json.dumps(result.model_dump(), indent=2), encoding="utf-8"
        )
        (output_path / "document.md").write_text(result.markdown, encoding="utf-8")
    return result