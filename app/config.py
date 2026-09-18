from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Literal

PipelineMode = Literal["auto", "hybrid", "full_page"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # APPLICATION
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    OUTPUT_DIR: str = "./outputs"
    SAVE_DEBUG_ARTIFACTS: bool = True

    # DOCUMENTS
    PDF_DPI: int = 200
    MAX_PAGES: int = 100

    # CROPPING
    CROP_PADDING: int = 8

    # LAYOUT
    LAYOUT_MODEL: str = "PP-DocLayoutV3"
    LAYOUT_DEVICE: str = "auto"

    # PIPELINE ROUTING
    OCR_PIPELINE_MODE: PipelineMode = "auto"

    # AUTO ROUTING THRESHOLDS
    AUTO_MIN_LAYOUT_COVERAGE: float = 0.55
    AUTO_MIN_CONTENT_COVERAGE: float = 0.80
    AUTO_WEAK_CONTENT_COVERAGE: float = 0.90
    AUTO_LARGE_REGION_RATIO: float = 0.70
    AUTO_LARGE_REGION_MIN_CONTENT_COVERAGE: float = 0.85
    AUTO_LAYOUT_DILATION_PX: int = 8
    AUTO_ENABLE_CONTENT_ANALYSIS: bool = True

    # DEDUPLICATION THRESHOLDS
    DEDUP_ENABLED: bool = True
    DEDUP_TEXT_SIMILARITY: float = 0.90
    DEDUP_GEOMETRIC_CONTAINMENT: float = 0.70
    DEDUP_IOU_THRESHOLD: float = 0.65
    DEDUP_PROXIMITY_PX: float = 40.0

    # DEBUG ARTIFACTS
    SAVE_PAGE_IMAGES: bool = True
    SAVE_LAYOUT_OVERLAYS: bool = True
    SAVE_REGION_CROPS: bool = True
    SAVE_PIPELINE_DECISIONS: bool = True

    # VLLM
    VLLM_BASE_URL: str = "http://localhost:8000/v1"
    VLLM_API_KEY: str = "EMPTY"
    VLLM_MODEL: str = "baidu/Unlimited-OCR"
    VLLM_TIMEOUT_SECONDS: float = 300.0
    VLLM_MAX_RETRIES: int = 2
    VLLM_MAX_TOKENS: int = 4096

    # OCR / INFERENCE PIPELINE
    OCR_CONCURRENCY: int = 8
    OCR_NGRAM_SIZE: int = 35
    OCR_WINDOW_SIZE: int = 128
    ENABLE_FULL_PAGE_FALLBACK: bool = True
    OCR_MOCK_MODE: bool = False

    # RECOGNIZED REGION TYPES TO PROCESS
    OCR_REGION_TYPES: str = "title,text,paragraph,table,chart,figure,equation,list,caption,header,footer,page_number,other"

    # FINANCE PLATFORM SETTINGS
    DATABASE_URL: str = "sqlite:///./finance.db"
    DEFAULT_ORGANIZATION_ID: str = "org_default"
    FINANCE_VALIDATION_TOLERANCE: str = "1.00"
    FINANCE_MIN_EXTRACTION_CONFIDENCE: float = 0.60
    FINANCE_EXTRACTOR_VERSION: str = "1.0.0"
    FINANCE_SCHEMA_VERSION: str = "1.0.0"

    # ENTITY RESOLUTION SETTINGS (PHASE 2)
    ENTITY_AUTO_MERGE_THRESHOLD: float = 0.88
    ENTITY_POSSIBLE_MATCH_THRESHOLD: float = 0.65

    # ANALYTICS SETTINGS (PHASE 3)
    ANALYTICS_ANOMALY_ZSCORE_THRESHOLD: float = 2.5   # flag if |z| > this
    ANALYTICS_ANOMALY_MIN_SAMPLE_SIZE: int = 5         # need at least N historical invoices
    DUPLICATE_DATE_WINDOW_DAYS: int = 30               # probable-dup window (not used in MVP exact-only)

    # KNOWLEDGE GRAPH SETTINGS (PHASE 4)
    GRAPH_BACKEND: str = "networkx"                    # "networkx" or "neo4j"
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "password"

    # VECTOR INDEX & SEMANTIC SEARCH SETTINGS (PHASE 5)
    VECTOR_EMBEDDING_PROVIDER: str = "fast"            # "fast" or "openai"
    VECTOR_DIMENSION: int = 128
    VECTOR_TOP_K_DEFAULT: int = 10
    VECTOR_INDEX_PATH: str = "./outputs/vector_index.json"

    # FINANCE COPILOT SETTINGS (PHASE 6)
    COPILOT_LLM_BACKEND: str = "deterministic"
    COPILOT_LLM_BASE_URL: str = "http://localhost:8000/v1"
    COPILOT_LLM_MODEL: str = "gpt-4o"
    COPILOT_MAX_CONTEXT_RESULTS: int = 10
    COPILOT_CONFIDENCE_THRESHOLD: float = 0.5

    @property
    def finance_validation_tolerance_decimal(self):
        from decimal import Decimal
        return Decimal(self.FINANCE_VALIDATION_TOLERANCE)

    @property
    def recognized_region_types(self) -> List[str]:
        return [t.strip().lower() for t in self.OCR_REGION_TYPES.split(",") if t.strip()]

    def get_output_dir(self) -> Path:
        p = Path(self.OUTPUT_DIR)
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
