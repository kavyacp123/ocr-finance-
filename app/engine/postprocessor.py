import re
from typing import Optional
from app.models import Region
from app.utils.logging import logger


class Postprocessor:
    """
    Postprocessor cleans raw OCR model outputs into clean Markdown/text content while
    preserving the original raw output untouched in region.raw_ocr_output.
    """

    # Regex patterns for Unlimited-OCR special grounding tags
    DET_PATTERN = re.compile(r"<\|det\|>.*?<\|/det\|>", re.DOTALL)
    DET_TAG_ONLY = re.compile(r"<\|/?det\|>")
    REF_START = re.compile(r"<\|ref\|>")
    REF_END = re.compile(r"<\|/ref\|>")
    BOX_PATTERN = re.compile(r"\[\[\d+,\s*\d+,\s*\d+,\s*\d+\]\]")

    def process_region(self, region: Region) -> Region:
        """
        Processes a region's raw_ocr_output and populates region.clean_content.
        """
        if not region.raw_ocr_output or region.processing_status != "success":
            region.clean_content = None
            return region

        clean_text = self.clean_ocr_text(region.raw_ocr_output)
        region.clean_content = clean_text
        return region

    @classmethod
    def clean_ocr_text(cls, text: str) -> str:
        if not text:
            return ""

        s = text

        # 1. Remove detection coordinate blocks (<|det|>...<|/det|>)
        s = cls.DET_PATTERN.sub("", s)
        s = cls.DET_TAG_ONLY.sub("", s)

        # 2. Remove isolated box coordinate tags like [[10, 20, 100, 200]]
        s = cls.BOX_PATTERN.sub("", s)

        # 3. Unwrap reference tags <|ref|>content<|/ref|> -> content
        s = cls.REF_START.sub("", s)
        s = cls.REF_END.sub("", s)

        # 4. Clean up trailing spaces on lines while preserving line breaks
        lines = [line.rstrip() for line in s.split("\n")]
        cleaned = "\n".join(lines).strip()

        return cleaned
