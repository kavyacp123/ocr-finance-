from pydantic import BaseModel, Field
from typing import List, Optional, Tuple, Dict, Any, Literal

PipelineMode = Literal["auto", "hybrid", "full_page"]


class BoundingBox(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def width(self) -> int:
        return max(0, self.x2 - self.x1)

    @property
    def height(self) -> int:
        return max(0, self.y2 - self.y1)

    @property
    def area(self) -> int:
        return self.width * self.height


class Point(BaseModel):
    x: int
    y: int


class PipelineDecision(BaseModel):
    requested_mode: PipelineMode
    selected_mode: PipelineMode
    reason: str
    region_count: int
    layout_coverage_ratio: float
    content_coverage_ratio: Optional[float] = None
    largest_region_ratio: float
    fallback_used: bool = False


class DedupDecision(BaseModel):
    region_id: str
    render_suppressed: bool = False
    duplicate_of: Optional[str] = None
    reason: Optional[str] = None


class FullPageOCRResult(BaseModel):
    status: str = "success"  # success, failed
    text: Optional[str] = None
    processing_time_ms: Optional[float] = None
    error: Optional[str] = None


class Region(BaseModel):
    id: str
    page_number: int
    region_type: str
    native_label: Optional[str] = None
    confidence: Optional[float] = None
    reading_order: int
    bbox: BoundingBox
    polygon: List[List[int]] = Field(default_factory=list)
    crop_path: Optional[str] = None
    raw_ocr_output: Optional[str] = None
    clean_content: Optional[str] = None
    processing_status: str = "pending"  # pending, success, failed, skipped
    processing_time_ms: Optional[float] = None
    error: Optional[str] = None


class PageResult(BaseModel):
    page_number: int
    width: int
    height: int
    pipeline_decision: Optional[PipelineDecision] = None
    full_page_ocr: Optional[FullPageOCRResult] = None
    regions: List[Region] = Field(default_factory=list)
    dedup_decisions: List[DedupDecision] = Field(default_factory=list)
    fallback_used: bool = False
    fallback_reason: Optional[str] = None


class EngineMetadata(BaseModel):
    architecture: str = "two-stage-hybrid"
    layout_model: str = "PP-DocLayoutV3"
    ocr_model: str = "baidu/Unlimited-OCR"
    inference_engine: str = "vLLM"


class ProcessingMetadata(BaseModel):
    processing_time_ms: float = 0.0
    pdf_rendering_time_ms: float = 0.0
    layout_detection_time_ms: float = 0.0
    ocr_inference_time_ms: float = 0.0
    page_count: int = 0
    total_regions: int = 0
    successful_regions: int = 0
    failed_regions: int = 0
    skipped_regions: int = 0
    fallback_count: int = 0
    avg_region_latency_ms: float = 0.0


class DocumentResult(BaseModel):
    document_id: str
    filename: str
    page_count: int
    processing_time_ms: float
    engine: EngineMetadata = Field(default_factory=EngineMetadata)
    pages: List[PageResult] = Field(default_factory=list)
    markdown: str = ""
    metadata: ProcessingMetadata = Field(default_factory=ProcessingMetadata)
