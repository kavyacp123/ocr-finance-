from PIL import Image
from app.models import Region, BoundingBox
from app.engine.cropper import RegionCropper


def test_cropper_valid(tmp_path):
    img = Image.new("RGB", (500, 500), color="white")
    region = Region(
        id="r1",
        page_number=1,
        region_type="title",
        reading_order=1,
        bbox=BoundingBox(x1=50, y1=50, x2=200, y2=100)
    )

    cropper = RegionCropper(padding=8)
    save_path = tmp_path / "crop_r1.png"
    cropped = cropper.crop_region(img, region, save_path=save_path)

    assert cropped is not None
    # 200-50 + 16 padding = 166 width, 100-50 + 16 = 66 height
    assert cropped.size == (166, 66)
    assert save_path.exists()


def test_cropper_tiny_region_protection():
    img = Image.new("RGB", (500, 500), color="white")
    region = Region(
        id="r_tiny",
        page_number=1,
        region_type="text",
        reading_order=1,
        bbox=BoundingBox(x1=10, y1=10, x2=11, y2=11)
    )

    cropper = RegionCropper(padding=0)
    cropped = cropper.crop_region(img, region)

    assert cropped is None
    assert region.processing_status == "skipped"
