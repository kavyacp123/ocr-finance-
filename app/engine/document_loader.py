import fitz  # PyMuPDF
from PIL import Image
import io
from pathlib import Path
from typing import List, Tuple
from app.config import settings
from app.utils.files import validate_file_path, DocumentRenderError
from app.utils.logging import logger


class DocumentLoader:
    """
    Loads PDF documents or image files into a list of PIL Images (1 per page).
    Configured by PDF_DPI and MAX_PAGES.
    """

    def __init__(self, dpi: int = settings.PDF_DPI, max_pages: int = settings.MAX_PAGES):
        self.dpi = dpi
        self.max_pages = max_pages

    def load_document(self, file_path: str, page_numbers: Optional[List[int]] = None) -> List[Tuple[int, Image.Image]]:
        """
        Loads document file and returns a list of tuples: (page_number, PIL.Image).
        Page numbers start at 1. If page_numbers is provided, only those pages are loaded.
        """
        path = validate_file_path(file_path)
        logger.info(f"DOCUMENT_LOAD_START: {path.name} (dpi={self.dpi}, page_filter={page_numbers or 'all'})")

        ext = path.suffix.lower()
        if ext == ".pdf":
            return self._load_pdf(path, page_numbers=page_numbers)
        else:
            return self._load_image(path)

    def _load_pdf(self, path: Path, page_numbers: Optional[List[int]] = None) -> List[Tuple[int, Image.Image]]:
        try:
            doc = fitz.open(str(path))
        except Exception as e:
            raise DocumentRenderError(f"Failed to open PDF document '{path.name}': {e}")

        total_pages = len(doc)
        if total_pages == 0:
            raise DocumentRenderError(f"PDF document '{path.name}' contains zero pages.")

        pages: List[Tuple[int, Image.Image]] = []
        zoom = self.dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)

        target_pages = set(page_numbers) if page_numbers else set(range(1, total_pages + 1))

        for i, page in enumerate(doc):
            page_num = i + 1
            if page_num not in target_pages:
                continue
            try:
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                pages.append((page_num, img))
                logger.info(f"PAGE_RENDERED: Page {page_num}/{total_pages} ({pix.width}x{pix.height} @ {self.dpi} DPI)")
            except Exception as e:
                raise DocumentRenderError(f"Failed to render page {page_num} of '{path.name}': {e}")

        doc.close()
        return pages

    def _load_image(self, path: Path) -> List[Tuple[int, Image.Image]]:
        try:
            img = Image.open(path)
            # Normalize orientation if EXIF present
            try:
                from PIL import ImageOps
                img = ImageOps.exif_transpose(img)
            except Exception:
                pass

            # Convert mode to RGB if needed
            if img.mode != "RGB":
                img = img.convert("RGB")

            logger.info(f"PAGE_RENDERED: Image page 1/1 ({img.width}x{img.height})")
            return [(1, img)]
        except Exception as e:
            raise DocumentRenderError(f"Failed to load image file '{path.name}': {e}")
