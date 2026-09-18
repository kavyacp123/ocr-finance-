from typing import List, Set
from app.models import PageResult, Region
from app.utils.logging import logger


class DocumentReconstructor:
    """
    Reconstructs layout-preserving Markdown document text from PageResult objects.

    For pages in 'full_page' OCR mode: renders full-page OCR text directly.
    For pages in 'hybrid' OCR mode: renders regions in reading_order, skipping
    regions marked as render_suppressed in page.dedup_decisions.
    """

    def reconstruct_markdown(self, pages: List[PageResult], include_page_breaks: bool = True) -> str:
        logger.info("RECONSTRUCTION_START: Reconstructing Markdown document.")
        md_parts: List[str] = []

        # Sort pages sequentially by page_number
        sorted_pages = sorted(pages, key=lambda p: p.page_number)

        for page in sorted_pages:
            if include_page_breaks:
                md_parts.append(f"<!-- Page {page.page_number} -->\n")

            mode = page.pipeline_decision.selected_mode if page.pipeline_decision else "hybrid"

            if mode == "full_page" and page.full_page_ocr and page.full_page_ocr.text:
                md_parts.append(f"{page.full_page_ocr.text.strip()}\n")
            else:
                # Hybrid mode: filter suppressed regions based on presentation dedup decisions
                suppressed_ids: Set[str] = {
                    d.region_id for d in page.dedup_decisions if d.render_suppressed
                }

                sorted_regions = sorted(page.regions, key=lambda r: r.reading_order)
                for region in sorted_regions:
                    if region.id in suppressed_ids:
                        logger.debug(f"RECONSTRUCT: Skipping suppressed region {region.id} from Markdown")
                        continue

                    if not region.clean_content:
                        if region.processing_status == "failed":
                            md_parts.append(f"<!-- Region {region.id} ({region.region_type}) failed: {region.error} -->\n")
                        continue

                    formatted_block = self._format_region_to_markdown(region)
                    if formatted_block:
                        md_parts.append(formatted_block)

            md_parts.append("\n")  # Space between pages

        final_markdown = "\n".join(md_parts).strip()
        logger.info(f"DOCUMENT_COMPLETE: Reconstruction generated {len(final_markdown)} characters.")
        return final_markdown

    def _format_region_to_markdown(self, region: Region) -> str:
        text = (region.clean_content or "").strip()
        if not text:
            return ""

        r_type = region.region_type.lower()

        if r_type == "title":
            if text.startswith("#"):
                return f"{text}\n"
            return f"# {text}\n"

        elif r_type == "header":
            return f"<!-- Header: {text} -->\n"

        elif r_type == "footer":
            return f"<!-- Footer: {text} -->\n"

        elif r_type == "page_number":
            return f"<!-- Page Number: {text} -->\n"

        elif r_type == "caption":
            if text.startswith("*") or text.startswith("_"):
                return f"{text}\n"
            return f"*{text}*\n"

        elif r_type in ("table", "paragraph", "text", "list", "equation"):
            return f"{text}\n"

        elif r_type in ("chart", "figure", "image"):
            if text.startswith("![") or text.startswith("<!--"):
                return f"{text}\n"
            return f"![{r_type.capitalize()}: {text}](#)\n"

        else:
            return f"{text}\n"
