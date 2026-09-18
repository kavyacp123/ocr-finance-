from datetime import date
import pytest
from app.intelligence.date_parser import DateParser


def test_date_parser_relative_quarters():
    # Use fixed reference: 2026-08-15 (Q3)
    parser = DateParser(reference_date=date(2026, 8, 15))

    res = parser.parse("How much did we spend with AWS last quarter?")
    assert res is not None
    # Last quarter of Q3 is Q2 (April 1 to June 30)
    assert res.start_date == "2026-04-01"
    assert res.end_date == "2026-06-30"

    res_this_q = parser.parse("Total spend this quarter")
    assert res_this_q is not None
    assert res_this_q.start_date == "2026-07-01"
    assert res_this_q.end_date == "2026-08-15"


def test_date_parser_named_months():
    parser = DateParser(reference_date=date(2026, 8, 15))

    res_aug = parser.parse("Why did AWS spending increase in August?")
    assert res_aug is not None
    assert res_aug.start_date == "2026-08-01"
    assert res_aug.end_date == "2026-08-31"

    res_july = parser.parse("Compare AWS spending between July and August")
    assert res_july is not None
    # First matched month
    assert "2026-07" in res_july.start_date or "2026-08" in res_july.start_date


def test_date_parser_last_n_days():
    parser = DateParser(reference_date=date(2026, 8, 15))

    res = parser.parse("Show invoices from the last 30 days")
    assert res is not None
    assert res.end_date == "2026-08-15"
    assert res.start_date == "2026-07-16"


def test_date_parser_none():
    parser = DateParser(reference_date=date(2026, 8, 15))
    res = parser.parse("Find invoices mentioning GPU compute")
    assert res is None
