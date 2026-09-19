import pytest
from PIL import Image
from pathlib import Path
from app.engine.document_loader import DocumentLoader
from app.utils.files import UnsupportedDocumentError


def test_load_image_sample(tmp_path):
    img_path = tmp_path / "test_sample.png"
    img = Image.new("RGB", (400, 300), color="white")
    img.save(img_path)

    loader = DocumentLoader(dpi=200, max_pages=5)
    pages = loader.load_document(str(img_path))

    assert len(pages) == 1
    page_num, page_img = pages[0]
    assert page_num == 1
    assert page_img.size == (400, 300)


def test_unsupported_file_extension(tmp_path):
    txt_path = tmp_path / "test.unsupported"
    txt_path.write_text("hello world")

    loader = DocumentLoader()
    with pytest.raises(UnsupportedDocumentError):
        loader.load_document(str(txt_path))
