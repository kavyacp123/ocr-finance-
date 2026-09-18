from app.investigations.analyzers.line_item_matcher import LineItemMatcher


def test_line_item_matcher_by_product_code():
    base = [
        {"product_code": "SKU-GPU-01", "description": "Compute Unit A", "quantity": 10, "unit_price": 100},
        {"product_code": "SKU-S3-01", "description": "Cloud Storage", "quantity": 50, "unit_price": 2},
    ]
    target = [
        {"product_code": "SKU-S3-01", "description": "Cloud Storage - US West", "quantity": 70, "unit_price": 2},
        {"product_code": "SKU-GPU-01", "description": "Compute Unit A", "quantity": 25, "unit_price": 120},
    ]

    res = LineItemMatcher.match(base, target)
    assert len(res["matched_pairs"]) == 2
    assert len(res["new_items"]) == 0
    assert len(res["removed_items"]) == 0


def test_line_item_matcher_by_description_and_new_items():
    base = [
        {"product_code": None, "description": "EC2 Standard Compute", "quantity": 10, "unit_price": 50},
    ]
    target = [
        {"product_code": None, "description": "ec2 standard compute", "quantity": 15, "unit_price": 50},
        {"product_code": "NEW-SRV", "description": "Enterprise Support Plan", "quantity": 1, "unit_price": 5000, "total": 5000},
    ]

    res = LineItemMatcher.match(base, target)
    assert len(res["matched_pairs"]) == 1
    assert len(res["new_items"]) == 1
    assert res["new_items"][0]["description"] == "Enterprise Support Plan"
