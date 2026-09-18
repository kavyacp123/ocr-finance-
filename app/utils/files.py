import uuid
import shutil
from pathlib import Path
from typing import Tuple, List, Optional
from PIL import Image


SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}


class UnsupportedDocumentError(Exception):
    pass


class DocumentRenderError(Exception):
    pass


class LayoutDetectionError(Exception):
    pass


class InferenceConnectionError(Exception):
    pass


class InferenceTimeoutError(Exception):
    pass


def validate_file_path(file_path: str) -> Path:
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    if not path.is_file():
        raise ValueError(f"Path is not a file: {file_path}")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise UnsupportedDocumentError(
            f"Unsupported file format '{path.suffix}'. Supported: {', '.join(SUPPORTED_EXTENSIONS)}"
        )
    return path


def generate_document_id() -> str:
    return str(uuid.uuid4())[:8]


def create_document_output_dirs(output_dir: str, doc_id: str) -> Tuple[Path, Path, Path, Path]:
    base_dir = Path(output_dir) / doc_id
    pages_dir = base_dir / "pages"
    overlays_dir = base_dir / "overlays"
    crops_dir = base_dir / "crops"

    for d in [base_dir, pages_dir, overlays_dir, crops_dir]:
        d.mkdir(parents=True, exist_ok=True)

    return base_dir, pages_dir, overlays_dir, crops_dir


def sanitize_filename(filename: str) -> str:
    # Remove any path traversal or unsafe characters
    return Path(filename).name
