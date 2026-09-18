from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field


class VectorChunk(BaseModel):
    """
    An atomic searchable chunk with layout metadata and bounding box provenance.
    """
    chunk_id: str
    document_id: str
    organization_id: str
    chunk_type: str = Field(..., description="'DOCUMENT_TEXT', 'LINE_ITEM', or 'METADATA'")
    text: str
    page_number: int = 1
    region_id: Optional[str] = None
    bbox: Optional[List[int]] = Field(default=None, description="[x1, y1, x2, y2] on original page")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SearchResult(BaseModel):
    """
    Ranked search result with similarity score and visual evidence.
    """
    chunk_id: str
    document_id: str
    chunk_type: str
    text: str
    similarity_score: float
    page_number: int
    region_id: Optional[str] = None
    bbox: Optional[List[int]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EvidenceItem(BaseModel):
    """
    Exact visual provenance item proving an extracted or queried fact.
    """
    document_id: str
    page_number: int
    region_id: Optional[str] = None
    bbox: Optional[List[int]] = None
    matched_text: str
    similarity_score: float
    context: Optional[str] = None


class SemanticSearchRequest(BaseModel):
    """
    Query payload for semantic document and line-item search.
    """
    query: str
    organization_id: Optional[str] = None
    top_k: int = 10
    filters: Optional[Dict[str, Any]] = Field(default_factory=dict)
