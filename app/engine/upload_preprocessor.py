import csv
import tempfile
import zipfile
from pathlib import Path
from typing import List, Tuple
from xml.etree import ElementTree

import fitz
from PIL import Image

from app.config import settings

DIRECT_TEXT_EXTENSIONS = {".csv", ".txt", ".xlsx", ".docx"}


class UploadCompressionError(ValueError):
    """Raised when an upload cannot be transformed under OCR.Space's limit."""


class PreparedUpload:
    def __init__(self, path: Path, temporary: bool):
        self.path = path
        self.temporary = temporary

    def cleanup(self) -> None:
        if self.temporary and self.path.exists():
            self.path.unlink()


def prepare_upload(path: Path) -> PreparedUpload:
    suffix = path.suffix.lower()
    if suffix in DIRECT_TEXT_EXTENSIONS:
        return _text_document_to_pdf(path)
    if suffix in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}:
        return _prepare_image(path)
    if suffix == ".pdf":
        return _prepare_pdf(path)
    raise UploadCompressionError(f"Unsupported upload format '{suffix}'.")


def _prepare_image(path: Path) -> PreparedUpload:
    if path.stat().st_size <= settings.OCR_SPACE_MAX_FILE_BYTES:
        return PreparedUpload(path, temporary=False)

    with Image.open(path) as image:
        image = image.convert("RGB")
        for max_dimension, quality in ((2200, 65), (1800, 55), (1400, 45), (1100, 35)):
            resized = image.copy()
            resized.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as output:
                resized.save(output, format="JPEG", quality=quality, optimize=True)
                candidate = Path(output.name)
            resized.close()
            if candidate.stat().st_size <= settings.OCR_SPACE_MAX_FILE_BYTES:
                return PreparedUpload(candidate, temporary=True)
            candidate.unlink()

    raise UploadCompressionError("The image could not be compressed below 1 MB without losing too much detail.")


def _prepare_pdf(path: Path) -> PreparedUpload:
    with fitz.open(path) as source:
        page_count = source.page_count
        if page_count > settings.OCR_SPACE_MAX_PDF_PAGES:
            raise UploadCompressionError(
                f"OCR.Space supports PDFs up to {settings.OCR_SPACE_MAX_PDF_PAGES} pages; received {page_count}."
            )
        if path.stat().st_size <= settings.OCR_SPACE_MAX_FILE_BYTES:
            return PreparedUpload(path, temporary=False)

        for dpi, quality in ((120, 60), (96, 50), (72, 40), (60, 30)):
            candidate = _rasterize_pdf(source, dpi, quality)
            if candidate.stat().st_size <= settings.OCR_SPACE_MAX_FILE_BYTES:
                return PreparedUpload(candidate, temporary=True)
            candidate.unlink()

    raise UploadCompressionError("The PDF could not be compressed below 1 MB.")


def _rasterize_pdf(source: fitz.Document, dpi: int, quality: int) -> Path:
    output = fitz.open()
    scale = dpi / 72.0
    for page in source:
        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as image_file:
            image.save(image_file, format="JPEG", quality=quality, optimize=True)
            image_path = Path(image_file.name)
        new_page = output.new_page(width=page.rect.width, height=page.rect.height)
        new_page.insert_image(new_page.rect, filename=str(image_path))
        image_path.unlink()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as pdf_file:
        output.save(pdf_file.name, deflate=True, garbage=4)
        result = Path(pdf_file.name)
    output.close()
    return result


def _text_document_to_pdf(path: Path) -> PreparedUpload:
    text = extract_text(path)
    if not text.strip():
        raise UploadCompressionError("The uploaded document contains no readable text.")

    output = fitz.open()
    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    line_height = 11
    lines_per_page = 65
    for start in range(0, len(lines), lines_per_page):
        page = output.new_page(width=612, height=792)
        page.insert_textbox(
            fitz.Rect(36, 36, 576, 756),
            "\n".join(lines[start:start + lines_per_page]),
            fontsize=8,
            fontname="courier",
            lineheight=line_height / 8,
        )

    if output.page_count > settings.OCR_SPACE_MAX_PDF_PAGES:
        output.close()
        raise UploadCompressionError(
            f"Converted documents must fit within {settings.OCR_SPACE_MAX_PDF_PAGES} pages for OCR.Space."
        )

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as pdf_file:
        output.save(pdf_file.name, deflate=True, garbage=4)
        result = Path(pdf_file.name)
    output.close()
    if result.stat().st_size > settings.OCR_SPACE_MAX_FILE_BYTES:
        result.unlink()
        raise UploadCompressionError("The converted document is larger than OCR.Space's 1 MB limit.")
    return PreparedUpload(result, temporary=True)


def extract_text(path: Path) -> str:
    if path.suffix.lower() == ".txt":
        return path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8", errors="replace") as source:
            return "\n".join(" | ".join(row) for row in csv.reader(source))
    if path.suffix.lower() == ".docx":
        with zipfile.ZipFile(path) as archive:
            root = ElementTree.fromstring(archive.read("word/document.xml"))
        namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        paragraphs = []
        for paragraph in root.iter(namespace + "p"):
            paragraphs.append("".join(node.text or "" for node in paragraph.iter(namespace + "t")))
        return "\n".join(paragraphs)
    if path.suffix.lower() == ".xlsx":
        return _extract_xlsx_text(path)
    return ""


def _extract_xlsx_text(path: Path) -> str:
    namespace = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(path) as archive:
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(node.text or "" for node in item.iter(namespace + "t")) for item in root]
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        rels = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
        rows: List[str] = []
        for sheet in workbook.find(namespace + "sheets") or []:
            relation = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            target = rel_map.get(relation, "").lstrip("/")
            target = target if target.startswith("xl/") else "xl/" + target
            if target not in archive.namelist():
                continue
            root = ElementTree.fromstring(archive.read(target))
            for row in root.iter(namespace + "row"):
                values = []
                for cell in row.findall(namespace + "c"):
                    value = cell.find(namespace + "v")
                    text = value.text if value is not None and value.text else ""
                    if cell.attrib.get("t") == "s" and text.isdigit() and int(text) < len(shared):
                        text = shared[int(text)]
                    values.append(text)
                if values:
                    rows.append(" | ".join(values))
    return "\n".join(rows)