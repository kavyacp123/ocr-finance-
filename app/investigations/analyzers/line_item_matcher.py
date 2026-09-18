"""
Line Item Matcher Service
=========================

WHY:   To explain why spending changed, we must compare the same products
       between periods.
       Matching priority:
         1. product_code (deterministic match)
         2. exact normalized description
         3. high-confidence token overlap
"""

import difflib
import re
from typing import Any, Dict, List, Optional, Tuple


def _normalize_desc(text: Optional[str]) -> str:
    if not text:
        return ""
    clean = re.sub(r'[^a-zA-Z0-9\s]', ' ', text.lower())
    return " ".join(clean.split())


class LineItemMatcher:
    """
    Pairs baseline items with target items.
    Returns:
      - matched_pairs: List[Tuple[Dict, Dict]] (baseline, target)
      - new_items: List[Dict] (present in target but not baseline)
      - removed_items: List[Dict] (present in baseline but not target)
    """

    @classmethod
    def match(
        cls,
        baseline_items: List[Dict[str, Any]],
        target_items: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        matched_pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
        unmatched_target = list(target_items)
        unmatched_base = list(baseline_items)

        # Pass 1: Match on product_code
        for b_item in list(unmatched_base):
            b_code = (b_item.get("product_code") or "").strip().lower()
            if not b_code:
                continue

            match_idx = -1
            for idx, t_item in enumerate(unmatched_target):
                t_code = (t_item.get("product_code") or "").strip().lower()
                if t_code and t_code == b_code:
                    match_idx = idx
                    break

            if match_idx != -1:
                matched_pairs.append((b_item, unmatched_target.pop(match_idx)))
                unmatched_base.remove(b_item)

        # Pass 2: Match on normalized description
        for b_item in list(unmatched_base):
            b_desc = _normalize_desc(b_item.get("description"))
            if not b_desc:
                continue

            match_idx = -1
            for idx, t_item in enumerate(unmatched_target):
                t_desc = _normalize_desc(t_item.get("description"))
                if t_desc and t_desc == b_desc:
                    match_idx = idx
                    break

            if match_idx != -1:
                matched_pairs.append((b_item, unmatched_target.pop(match_idx)))
                unmatched_base.remove(b_item)

        # Pass 3: Fuzzy token similarity (similarity >= 0.80)
        for b_item in list(unmatched_base):
            b_desc = _normalize_desc(b_item.get("description"))
            if not b_desc:
                continue

            best_score = 0.0
            best_idx = -1
            for idx, t_item in enumerate(unmatched_target):
                t_desc = _normalize_desc(t_item.get("description"))
                if not t_desc:
                    continue
                score = difflib.SequenceMatcher(None, b_desc, t_desc).ratio()
                if score > best_score:
                    best_score = score
                    best_idx = idx

            if best_idx != -1 and best_score >= 0.80:
                matched_pairs.append((b_item, unmatched_target.pop(best_idx)))
                unmatched_base.remove(b_item)

        return {
            "matched_pairs": matched_pairs,
            "new_items": unmatched_target,
            "removed_items": unmatched_base,
        }
