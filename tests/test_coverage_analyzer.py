import pytest
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from app.config import settings
from app.models import Region, BoundingBox
from app.engine.coverage_analyzer import CoverageAnalyzer


def create_test_image(width=1000, height=1000, draw_header=False, draw_body=True):
    img = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(img)

    if draw_header:
        # Draw text header at top (outside detected body box)
        draw.text((100, 50), "SONAL ENTERPRISES - COMPANY HEADER", fill="black")
        draw.text((100, 80), "Mobile: 9876543210 Email: test@example.com", fill="black")

    if draw_body:
        # Draw main body content
        draw.rectangle([100, 200, 900, 800], outline="black", fill="white")
        draw.text((150, 250), "ITEM 1: MS BUSH 12MM QTY: 5000", fill="black")

    return img


def test_coverage_raster_union():
    analyzer = CoverageAnalyzer()
    # 2 overlapping boxes (500x500 each, overlapping by 250x500)
    r1 = Region(
        id="r1", page_number=1, region_type="text", reading_order=1,
        bbox=BoundingBox(x1=0, y1=0, x2=500, y2=500)
    )
    r2 = Region(
        id="r2", page_number=1, region_type="text", reading_order=2,
        bbox=BoundingBox(x1=250, y1=0, x2=750, y2=500)
    )
    img = Image.new("RGB", (1000, 1000), "white")
    mask, layout_cov, largest_ratio = analyzer.calculate_layout_coverage(1000, 1000, [r1, r2])

    # Union rectangle (x: 0..750, y: 0..500) -> 751 * 501 = 376,251 pixels out of 1,000,000 -> ~0.376
    assert layout_cov == pytest.approx(0.376, abs=1e-2)
    assert largest_ratio == pytest.approx(0.251, abs=1e-2)


def test_auto_routing_undetected_header_triggers_full_page():
    analyzer = CoverageAnalyzer(min_content_coverage=0.80)
    img = create_test_image(1000, 1000, draw_header=True, draw_body=True)

    # Detected region ONLY covers the body box (100, 200, 900, 800)
    # Header at top (y=50..80) is NOT covered
    r_body = Region(
        id="r1", page_number=1, region_type="table", reading_order=1,
        bbox=BoundingBox(x1=100, y1=200, x2=900, y2=800)
    )

    decision = analyzer.analyze_page(1, img, [r_body], requested_mode="auto")
    assert decision.selected_mode == "full_page"
    assert decision.reason in ("significant_uncovered_content", "large_region_plus_uncovered_content")


def test_auto_routing_blank_margin_remains_hybrid():
    analyzer = CoverageAnalyzer(min_content_coverage=0.80)
    # Image has body content ONLY (no header at top, bottom 200px is blank paper margin)
    img = create_test_image(1000, 1000, draw_header=False, draw_body=True)

    # Region covers body content (100, 200, 900, 800)
    r_body = Region(
        id="r1", page_number=1, region_type="table", reading_order=1,
        bbox=BoundingBox(x1=95, y1=195, x2=905, y2=805)
    )

    decision = analyzer.analyze_page(1, img, [r_body], requested_mode="auto")
    # Low geometric coverage (0.49), BUT 100% of ink pixels are covered -> HYBRID!
    assert decision.content_coverage_ratio >= 0.95
    assert decision.selected_mode == "hybrid"


def test_auto_routing_zero_regions_triggers_full_page():
    analyzer = CoverageAnalyzer()
    img = Image.new("RGB", (500, 500), "white")
    decision = analyzer.analyze_page(1, img, [], requested_mode="auto")
    assert decision.selected_mode == "full_page"
    assert decision.reason == "no_layout_regions"
    assert decision.fallback_used is True
