from app.models import Region, BoundingBox
from app.engine.postprocessor import Postprocessor


def test_postprocessor_clean_tags():
    raw = "<|det|>[[10, 20, 100, 200]]<|/det|> # Header Title\n<|ref|>This is paragraph content.<|/ref|>"
    cleaned = Postprocessor.clean_ocr_text(raw)

    assert "<|det|>" not in cleaned
    assert "<|ref|>" not in cleaned
    assert "[[10, 20, 100, 200]]" not in cleaned
    assert "# Header Title" in cleaned
    assert "This is paragraph content." in cleaned


def test_postprocessor_region_processing():
    region = Region(
        id="r1",
        page_number=1,
        region_type="title",
        reading_order=1,
        bbox=BoundingBox(x1=0, y1=0, x2=10, y2=10),
        raw_ocr_output="<|ref|>Title Content<|/ref|>",
        processing_status="success"
    )

    post = Postprocessor()
    post.process_region(region)

    assert region.clean_content == "Title Content"
