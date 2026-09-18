from decimal import Decimal
from app.investigations.context import InvestigationContext
from app.investigations.analyzers.spend_delta import SpendDeltaAnalyzer
from app.investigations.analyzers.price_change import PriceChangeAnalyzer
from app.investigations.analyzers.quantity_change import QuantityChangeAnalyzer
from app.investigations.schemas import DriverType


def test_spend_delta_analyzer():
    ctx = InvestigationContext(
        investigation_id="inv_test",
        organization_id="org_test",
        baseline_spend=Decimal("820000.00"),
        target_spend=Decimal("1270000.00"),
    )
    delta_data = SpendDeltaAnalyzer.analyze(ctx)
    assert ctx.spend_delta == Decimal("450000.00")
    assert ctx.spend_delta_percentage == Decimal("54.88")
    assert delta_data["direction"] == "INCREASE"


def test_price_change_analyzer():
    matched = [
        (
            {"description": "Compute Units", "unit_price": "100.00", "quantity": "10"},
            {"description": "Compute Units", "unit_price": "125.00", "quantity": "100"},
        )
    ]
    findings = PriceChangeAnalyzer.analyze(matched)
    assert len(findings) == 1
    f = findings[0]
    assert f.finding_type == DriverType.UNIT_PRICE_CHANGE.value
    # (125 - 100) * 100 = 2500
    assert f.impact_amount == "2500.00"
    assert "25.00%" in f.impact_percentage


def test_quantity_change_analyzer():
    matched = [
        (
            {"description": "GPU Hours", "unit_price": "200.00", "quantity": "20"},
            {"description": "GPU Hours", "unit_price": "200.00", "quantity": "50"},
        )
    ]
    new_items = [
        {"description": "Support Plan", "unit_price": "10000.00", "quantity": "1", "total": "10000.00"}
    ]
    findings = QuantityChangeAnalyzer.analyze(matched, new_items)
    assert len(findings) == 2

    qty_f = next(f for f in findings if f.finding_type == DriverType.QUANTITY_CHANGE.value)
    # (50 - 20) * 200 = 6000
    assert qty_f.impact_amount == "6000.00"

    new_f = next(f for f in findings if f.finding_type == DriverType.NEW_LINE_ITEM.value)
    assert new_f.impact_amount == "10000.00"
