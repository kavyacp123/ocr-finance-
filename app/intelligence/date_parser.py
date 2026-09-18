"""
Deterministic Date Parser
=========================

WHY:   User questions contain relative dates like "last quarter", "August",
       "last 30 days".  These MUST be resolved to explicit ISO date boundaries
       BEFORE any tool is invoked.  Ambiguous dates cause wrong query results.

WHERE: Called by the QueryPlanner during entity extraction.

WHAT IT RECEIVES: A raw question string + optional reference date.

WHAT IT OUTPUTS:  A TimeRange(start_date, end_date) or None.

HOW:   Pure regex + calendar math.  No LLM.  No external dependencies.
"""

import re
import calendar
from datetime import date, timedelta
from typing import Optional, Tuple

from app.intelligence.schemas import TimeRange


# ── Month name lookup ─────────────────────────────────────────────────────────

_MONTH_NAMES = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}

_QUARTER_MAP = {
    "q1": (1, 3), "q2": (4, 6), "q3": (7, 9), "q4": (10, 12),
}


class DateParser:
    """
    Extracts explicit date ranges from natural language questions.

    Supports:
      - Relative:  today, yesterday, this week, last week, this month,
                   last month, this quarter, last quarter, this year, last year,
                   last N days
      - Named:     "August", "August 2026", "Aug 2026"
      - Quarter:   "Q1", "Q2 2026"
      - Year:      "2026", "2025"

    All boundaries are inclusive full-day ranges (start 00:00, end 23:59).
    """

    def __init__(self, reference_date: Optional[date] = None):
        self.reference = reference_date or date.today()

    def parse(self, text: str) -> Optional[TimeRange]:
        """
        Attempt to extract a date range from the text.
        Returns None if no temporal expression is found.
        """
        lower = text.lower().strip()

        # Try each parser in priority order
        for parser in [
            self._parse_relative,
            self._parse_last_n_days,
            self._parse_named_quarter,
            self._parse_named_month_year,
            self._parse_named_month,
            self._parse_year_only,
        ]:
            result = parser(lower)
            if result:
                return result
        return None

    # ── Relative expressions ──────────────────────────────────────────────

    def _parse_relative(self, text: str) -> Optional[TimeRange]:
        ref = self.reference

        if "today" in text:
            return self._range(ref, ref)

        if "yesterday" in text:
            d = ref - timedelta(days=1)
            return self._range(d, d)

        if "this week" in text:
            start = ref - timedelta(days=ref.weekday())  # Monday
            end = start + timedelta(days=6)               # Sunday
            return self._range(start, min(end, ref))

        if "last week" in text:
            start = ref - timedelta(days=ref.weekday() + 7)
            end = start + timedelta(days=6)
            return self._range(start, end)

        if "this month" in text:
            start = ref.replace(day=1)
            return self._range(start, ref)

        if "last month" in text:
            first_this = ref.replace(day=1)
            last_prev = first_this - timedelta(days=1)
            start = last_prev.replace(day=1)
            return self._range(start, last_prev)

        if "this quarter" in text:
            q_start_month = ((ref.month - 1) // 3) * 3 + 1
            start = date(ref.year, q_start_month, 1)
            return self._range(start, ref)

        if "last quarter" in text:
            q_start_month = ((ref.month - 1) // 3) * 3 + 1
            q_start = date(ref.year, q_start_month, 1)
            last_q_end = q_start - timedelta(days=1)
            last_q_start_month = ((last_q_end.month - 1) // 3) * 3 + 1
            last_q_start = date(last_q_end.year, last_q_start_month, 1)
            return self._range(last_q_start, last_q_end)

        if "this year" in text:
            start = date(ref.year, 1, 1)
            return self._range(start, ref)

        if "last year" in text:
            start = date(ref.year - 1, 1, 1)
            end = date(ref.year - 1, 12, 31)
            return self._range(start, end)

        return None

    # ── "last N days" ─────────────────────────────────────────────────────

    def _parse_last_n_days(self, text: str) -> Optional[TimeRange]:
        m = re.search(r"last\s+(\d+)\s+days?", text)
        if m:
            n = int(m.group(1))
            start = self.reference - timedelta(days=n)
            return self._range(start, self.reference)
        return None

    # ── Named quarter: "Q2", "Q2 2026" ───────────────────────────────────

    def _parse_named_quarter(self, text: str) -> Optional[TimeRange]:
        m = re.search(r"\bq([1-4])\s*(\d{4})?\b", text)
        if m:
            q = int(m.group(1))
            year = int(m.group(2)) if m.group(2) else self.reference.year
            start_month, end_month = _QUARTER_MAP[f"q{q}"]
            last_day = calendar.monthrange(year, end_month)[1]
            return self._range(date(year, start_month, 1), date(year, end_month, last_day))
        return None

    # ── Named month + year: "August 2026", "Aug 2026" ────────────────────

    def _parse_named_month_year(self, text: str) -> Optional[TimeRange]:
        for name, num in _MONTH_NAMES.items():
            pattern = rf"\b{name}\s+(\d{{4}})\b"
            m = re.search(pattern, text)
            if m:
                year = int(m.group(1))
                last_day = calendar.monthrange(year, num)[1]
                return self._range(date(year, num, 1), date(year, num, last_day))
        return None

    # ── Named month alone: "August", "in July" ───────────────────────────

    def _parse_named_month(self, text: str) -> Optional[TimeRange]:
        for name, num in _MONTH_NAMES.items():
            # Match the month name as a standalone word
            if re.search(rf"\b{name}\b", text):
                year = self.reference.year
                # If the month is in the future, assume last year
                if num > self.reference.month:
                    year -= 1
                last_day = calendar.monthrange(year, num)[1]
                return self._range(date(year, num, 1), date(year, num, last_day))
        return None

    # ── Bare year: "2025", "2026" ─────────────────────────────────────────

    def _parse_year_only(self, text: str) -> Optional[TimeRange]:
        # Must not match years embedded in invoice numbers etc.
        m = re.search(r"\bin\s+(20\d{2})\b|\bfor\s+(20\d{2})\b|\bduring\s+(20\d{2})\b|\byear\s+(20\d{2})\b", text)
        if m:
            year = int(next(g for g in m.groups() if g))
            return self._range(date(year, 1, 1), date(year, 12, 31))
        return None

    # ── Helper ────────────────────────────────────────────────────────────

    @staticmethod
    def _range(start: date, end: date) -> TimeRange:
        return TimeRange(
            start_date=start.isoformat(),
            end_date=end.isoformat(),
        )
