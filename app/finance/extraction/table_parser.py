import re
import itertools
from typing import List, Optional, Tuple, Dict
from decimal import Decimal
from app.models import Region
from app.finance.schemas import InvoiceLineItem, SourceReference
from app.finance.normalizer import normalize_amount
from app.utils.logging import logger

HEADER_KEYWORDS = {
    "desc": ["description", "item", "particulars", "product", "service", "details"],
    "qty": ["qty", "quantity", "qnty", "units", "nos"],
    "rate": ["rate", "unit price", "price", "mrp", "unit cost"],
    "tax": ["tax", "gst", "cgst", "sgst", "igst", "vat"],
    "total": ["amount", "total", "line total", "net amount", "value"],
}


class TableParser:
    """
    Mini-pipeline for line-item extraction from table regions.
    Supports markdown tables and line-by-line whitespace-delimited rows.
    """

    def parse_line_items(
        self, document_id: str, regions: List[Region]
    ) -> List[InvoiceLineItem]:
        table_regions = [r for r in regions if r.region_type == "table" and r.clean_content]
        if not table_regions:
            # Fallback: scan text regions for table-like content if no region was labelled 'table'
            table_regions = [
                r for r in regions
                if r.clean_content and ("|" in r.clean_content or re.search(r"\b(qty|quantity)\b", r.clean_content, re.I))
            ]

        line_items: List[InvoiceLineItem] = []
        line_num = 1

        for t_reg in table_regions:
            text = t_reg.clean_content or ""
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            if not lines:
                continue

            if t_reg.id.endswith("_fullpage") and not any(line.count("|") >= 2 for line in lines):
                lines = self._extract_full_page_table_window(lines)
                if not lines:
                    continue

            # ── Check if Markdown Pipe Table ─────────────────────────────────
            if any(l.count("|") >= 2 for l in lines):
                items = self._parse_pipe_table(document_id, t_reg, lines, start_line_num=line_num)
                line_items.extend(items)
                line_num += len(items)
            else:
                items = self._parse_plaintext_table(document_id, t_reg, lines, start_line_num=line_num)
                if not items and t_reg.id.endswith("_fullpage"):
                    items = self._parse_fragmented_full_page_table(
                        document_id, t_reg, lines, start_line_num=line_num
                    )
                line_items.extend(items)
                line_num += len(items)

        logger.debug(f"[TABLE_PARSER] Extracted {len(line_items)} line item(s) from document {document_id}")
        return line_items

    def _parse_pipe_table(
        self, document_id: str, region: Region, lines: List[str], start_line_num: int
    ) -> List[InvoiceLineItem]:
        items: List[InvoiceLineItem] = []
        header_map: Dict[int, str] = {}
        header_found = False

        source = SourceReference(
            document_id=document_id,
            page_number=region.page_number,
            region_id=region.id,
            bbox=[region.bbox.x1, region.bbox.y1, region.bbox.x2, region.bbox.y2],
            polygon=region.polygon or [],
            original_text=region.clean_content or "",
        )

        for line in lines:
            # Skip separator line like |---|---|
            if re.match(r"^\|?[\s\-:|]+\|?$", line):
                continue

            cells = [c.strip() for c in line.split("|")]
            if cells and not cells[0]:
                cells.pop(0)
            if cells and not cells[-1]:
                cells.pop()

            if len(cells) < 2:
                continue

            # Check if this row is header
            if not header_found:
                header_map = self._map_columns(cells)
                if header_map:
                    header_found = True
                    continue

            # Data Row
            desc = ""
            qty: Optional[Decimal] = None
            rate: Optional[Decimal] = None
            tax: Optional[Decimal] = None
            total: Optional[Decimal] = None

            for col_idx, cell_val in enumerate(cells):
                col_type = header_map.get(col_idx, "unknown")
                if col_type == "desc":
                    desc = cell_val
                elif col_type == "qty":
                    qty = normalize_amount(cell_val)
                elif col_type == "rate":
                    rate = normalize_amount(cell_val)
                elif col_type == "tax":
                    tax = normalize_amount(cell_val)
                elif col_type == "total":
                    total = normalize_amount(cell_val)

            # If no header mapped or incomplete, fallback heuristics based on last columns
            if not desc and cells:
                desc = cells[0]
            if total is None and len(cells) >= 2:
                total = normalize_amount(cells[-1])
            if qty is None and len(cells) >= 3:
                qty = normalize_amount(cells[1])
            if rate is None and len(cells) >= 4:
                rate = normalize_amount(cells[2])

            if total is not None or rate is not None or desc:
                # Calculate total if missing
                if total is None and qty is not None and rate is not None:
                    total = (qty * rate).quantize(Decimal("0.01"))

                items.append(
                    InvoiceLineItem(
                        line_number=start_line_num + len(items),
                        description=desc if desc else f"Line Item {start_line_num + len(items)}",
                        quantity=qty,
                        unit_price=rate,
                        tax_amount=tax,
                        total=total,
                        confidence=region.confidence or 0.85,
                        source=source,
                    )
                )

        return items

    def _parse_fragmented_full_page_table(
        self, document_id: str, region: Region, lines: List[str], start_line_num: int
    ) -> List[InvoiceLineItem]:
        """Recover a single row whose columns were emitted as adjacent OCR lines."""
        numeric_values: List[Decimal] = []
        description_candidates: List[str] = []
        quantity_hint: Optional[Decimal] = None
        numeric_pattern = r"(?<![A-Za-z0-9])[0-9][0-9,]*(?:\.[0-9]+)?(?![A-Za-z0-9])"
        for line in lines:
            if re.search(r"\b(?:gstin|state\s+code|company['’]?s|bank|ifsc|total|cgst|sgst|rupees|only)\b", line, re.I):
                continue
            quantity_match = re.search(rf"\bNo\s+({numeric_pattern})\s+No\b", line, re.I)
            if quantity_match:
                quantity_hint = normalize_amount(quantity_match.group(1))

            for raw in re.findall(numeric_pattern, line):
                value = normalize_amount(raw)
                if value is not None and value > 0:
                    numeric_values.append(value)

            dimensioned_description = bool(
                re.search(r"\d+(?:\.\d+)?\s*(?:mm|cm|mtr|inch|in)\b", line, re.I)
            )
            cleaned = line if dimensioned_description else re.sub(numeric_pattern, " ", line)
            cleaned = re.sub(r"\b(?:sr|no|description|code|hsn|sac|quantity|qty|unit|rate|amount)\b", " ", cleaned, flags=re.I)
            cleaned = re.sub(r"\s+", " ", cleaned).strip(" -|:")
            if len(cleaned) >= 4 and re.search(r"[A-Za-z]", cleaned):
                description_candidates.append(cleaned)

        match = None
        for quantity, rate, total in itertools.permutations(numeric_values, 3):
            if quantity_hint is not None and quantity != quantity_hint:
                continue
            tolerance = max(Decimal("1.00"), total * Decimal("0.01"))
            if abs((quantity * rate) - total) <= tolerance:
                match = (quantity, rate, total)
                break
        if not match or not description_candidates:
            return []

        description = max(description_candidates, key=len)
        source = SourceReference(
            document_id=document_id,
            page_number=region.page_number,
            region_id=region.id,
            bbox=[region.bbox.x1, region.bbox.y1, region.bbox.x2, region.bbox.y2],
            polygon=region.polygon or [],
            original_text=region.clean_content or "",
        )
        quantity, rate, total = match
        return [
            InvoiceLineItem(
                line_number=start_line_num,
                description=description,
                quantity=quantity,
                unit_price=rate,
                total=total,
                confidence=min(region.confidence or 0.8, 0.75),
                source=source,
            )
        ]

    @staticmethod
    def _extract_full_page_table_window(lines: List[str]) -> List[str]:
        """Restrict plaintext parsing to the invoice's item table."""
        start = None
        header_start = None
        header_end = None
        description_index = next(
            (
                index
                for index, line in enumerate(lines)
                if re.search(r"\b(?:description|particulars|item\s+name)\b", line, re.I)
            ),
            None,
        )
        candidate_indexes = [description_index] if description_index is not None else range(len(lines))
        for index in candidate_indexes:
            line = lines[index]
            window = " ".join(lines[index:min(index + 8, len(lines))]).lower()
            header_hits = sum(
                keyword in window
                for keyword in ("description", "quantity", "rate", "amount")
            )
            if description_index is not None or header_hits >= 3:
                header_start = index
                header_end = next(
                    (
                        candidate
                        for candidate in range(index, min(index + 8, len(lines)))
                        if "amount" in lines[candidate].lower()
                    ),
                    index,
                )
                start = header_start
                break
        if start is None:
            return []

        end = len(lines)
        for index in range(start, len(lines)):
            if re.match(r"^(?:sub\s*)?total\b|^grand\s+total\b", lines[index], re.I):
                end = index
                break
        return lines[start:end]

    def _parse_plaintext_table(
        self, document_id: str, region: Region, lines: List[str], start_line_num: int
    ) -> List[InvoiceLineItem]:
        items: List[InvoiceLineItem] = []
        source = SourceReference(
            document_id=document_id,
            page_number=region.page_number,
            region_id=region.id,
            bbox=[region.bbox.x1, region.bbox.y1, region.bbox.x2, region.bbox.y2],
            polygon=region.polygon or [],
            original_text=region.clean_content or "",
        )

        for line in lines:
            # Skip lines that are just headers
            if any(k in line.lower() for k in ["description", "particulars", "sl no", "item name"]):
                continue
            if re.search(r"\b(?:gstin|state\s+code|company['’]?s|bank|ifsc|total|cgst|sgst)\b", line, re.I):
                continue

            # Regex: match description followed by 1 or more amounts at the end of line
            # e.g.: "Product A 10 150.00 1500.00"
            tokens = line.split()
            if len(tokens) < 2:
                continue

            # Identify numerical amounts from right to left
            amounts: List[Decimal] = []
            non_numeric_tokens: List[str] = []

            for tok in reversed(tokens):
                amt = normalize_amount(tok)
                if amt is not None and len(amounts) < 3:
                    amounts.append(amt)
                else:
                    non_numeric_tokens.insert(0, tok)

            if len(amounts) >= 2:
                amounts.reverse()
                desc = " ".join(non_numeric_tokens).strip()
                total = amounts[-1] if amounts else None
                rate = amounts[-2] if len(amounts) >= 2 else None
                qty = amounts[0] if len(amounts) == 3 else None

                if desc and re.search(r"[A-Za-z]", desc):
                    items.append(
                        InvoiceLineItem(
                            line_number=start_line_num + len(items),
                            description=desc if desc else f"Item {start_line_num + len(items)}",
                            quantity=qty,
                            unit_price=rate,
                            total=total,
                            confidence=region.confidence or 0.80,
                            source=source,
                        )
                    )

        return items

    def _map_columns(self, header_cells: List[str]) -> Dict[int, str]:
        col_map: Dict[int, str] = {}
        for idx, cell in enumerate(header_cells):
            c_low = cell.lower()
            for col_type, keywords in HEADER_KEYWORDS.items():
                if any(kw in c_low for kw in keywords):
                    col_map[idx] = col_type
                    break
        return col_map
