import pytest
from app.models import Region, BoundingBox
from app.engine.deduplication import DeduplicationAnalyzer, normalize_for_comparison


def test_normalize_for_comparison():
    raw1 = "  For  SONAL  ENTERPRISES!  \n"
    raw2 = "for sonal enterprises"
    assert normalize_for_comparison(raw1) == normalize_for_comparison(raw2)


def test_exact_duplicate_with_spatial_proximity():
    analyzer = DeduplicationAnalyzer(proximity_px=40.0)
    # Two overlapping text regions with exact same normalized text
    r1 = Region(
        id="r1", page_number=1, region_type="text", reading_order=1,
        bbox=BoundingBox(x1=1000, y1=1900, x2=1500, y2=1940),
        clean_content="For SONAL ENTERPRISES", confidence=0.8, processing_status="success"
    )
    r2 = Region(
        id="r2", page_number=1, region_type="text", reading_order=2,
        bbox=BoundingBox(x1=1005, y1=1902, x2=1498, y2=1938),
        clean_content="FOR SONAL ENTERPRISES", confidence=0.6, processing_status="success"
    )

    decisions = analyzer.analyze_page_deduplication([r1, r2])
    d_map = {d.region_id: d for d in decisions}

    assert d_map["r1"].render_suppressed is False
    assert d_map["r2"].render_suppressed is True
    assert d_map["r2"].duplicate_of == "r1"
    assert d_map["r2"].reason == "exact_duplicate_with_spatial_proximity"

    # Verify canonical regions were NOT mutated
    assert r1.clean_content == "For SONAL ENTERPRISES"
    assert r2.clean_content == "FOR SONAL ENTERPRISES"


def test_exact_duplicate_distant_not_suppressed():
    analyzer = DeduplicationAnalyzer(proximity_px=40.0)
    # Identical text at top (y=100) and bottom (y=2000) of page (far apart, no spatial overlap)
    r_top = Region(
        id="r_top", page_number=1, region_type="text", reading_order=1,
        bbox=BoundingBox(x1=100, y1=100, x2=400, y2=140),
        clean_content="SONAL ENTERPRISES", confidence=0.9, processing_status="success"
    )
    r_bot = Region(
        id="r_bot", page_number=1, region_type="text", reading_order=5,
        bbox=BoundingBox(x1=100, y1=2000, x2=400, y2=2040),
        clean_content="SONAL ENTERPRISES", confidence=0.85, processing_status="success"
    )

    decisions = analyzer.analyze_page_deduplication([r_top, r_bot])
    d_map = {d.region_id: d for d in decisions}

    # Distant identical text MUST NOT be suppressed!
    assert d_map["r_top"].render_suppressed is False
    assert d_map["r_bot"].render_suppressed is False


def test_substring_containment_seal_and_signatory():
    analyzer = DeduplicationAnalyzer(geometric_containment_threshold=0.70)
    # Region A: Seal stamp box containing full text
    r_seal = Region(
        id="r_seal", page_number=1, region_type="other", reading_order=1,
        bbox=BoundingBox(x1=1200, y1=1900, x2=1500, y2=2100),
        clean_content="SONAL ENTERPRISES Authorised Signatory", confidence=0.85, processing_status="success"
    )
    # Region B: Text box inside seal box containing substring "Authorised Signatory"
    r_sig = Region(
        id="r_sig", page_number=1, region_type="text", reading_order=2,
        bbox=BoundingBox(x1=1220, y1=2070, x2=1490, y2=2098),
        clean_content="Authorised Signatory", confidence=0.70, processing_status="success"
    )

    decisions = analyzer.analyze_page_deduplication([r_seal, r_sig])
    d_map = {d.region_id: d for d in decisions}

    assert d_map["r_seal"].render_suppressed is False
    assert d_map["r_sig"].render_suppressed is True
    assert d_map["r_sig"].duplicate_of == "r_seal"
    assert d_map["r_sig"].reason == "overlapping_substring"


def test_table_safety_rule():
    analyzer = DeduplicationAnalyzer()
    # Two table regions with identical row text far apart (IoU < 0.85)
    t1 = Region(
        id="t1", page_number=1, region_type="table", reading_order=1,
        bbox=BoundingBox(x1=100, y1=200, x2=900, y2=500),
        clean_content="| Item | Qty |\n| Bush | 100 |", confidence=0.9, processing_status="success"
    )
    t2 = Region(
        id="t2", page_number=1, region_type="table", reading_order=2,
        bbox=BoundingBox(x1=100, y1=600, x2=900, y2=900),
        clean_content="| Item | Qty |\n| Bush | 100 |", confidence=0.9, processing_status="success"
    )

    decisions = analyzer.analyze_page_deduplication([t1, t2])
    d_map = {d.region_id: d for d in decisions}

    # Tables MUST NOT be suppressed based on text alone!
    assert d_map["t1"].render_suppressed is False
    assert d_map["t2"].render_suppressed is False
