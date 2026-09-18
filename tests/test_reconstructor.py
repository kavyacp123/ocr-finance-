from app.models import PageResult, Region, BoundingBox
from app.engine.reconstructor import DocumentReconstructor


def test_reconstructor_reading_order():
    # Input regions in scrambled completion order: 4, 2, 1, 3
    r4 = Region(id="r4", page_number=1, region_type="text", reading_order=4, bbox=BoundingBox(x1=0, y1=0, x2=10, y2=10), clean_content="Fourth section", processing_status="success")
    r2 = Region(id="r2", page_number=1, region_type="text", reading_order=2, bbox=BoundingBox(x1=0, y1=0, x2=10, y2=10), clean_content="Second section", processing_status="success")
    r1 = Region(id="r1", page_number=1, region_type="title", reading_order=1, bbox=BoundingBox(x1=0, y1=0, x2=10, y2=10), clean_content="First Title", processing_status="success")
    r3 = Region(id="r3", page_number=1, region_type="text", reading_order=3, bbox=BoundingBox(x1=0, y1=0, x2=10, y2=10), clean_content="Third section", processing_status="success")

    page = PageResult(
        page_number=1,
        width=500,
        height=500,
        regions=[r4, r2, r1, r3]  # Scrambled
    )

    reconstructor = DocumentReconstructor()
    markdown = reconstructor.reconstruct_markdown([page])

    lines = [line.strip() for line in markdown.split("\n") if line.strip() and not line.startswith("<!--")]

    assert lines[0] == "# First Title"
    assert lines[1] == "Second section"
    assert lines[2] == "Third section"
    assert lines[3] == "Fourth section"
