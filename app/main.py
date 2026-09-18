from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.config import settings
from app.api.routes import router
from app.engine.pipeline import OCREngine
from app.utils.logging import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("APP_STARTUP: Initializing Two-Stage Hybrid OCR Engine...")
    ocr_engine = OCREngine()
    app.state.ocr_engine = ocr_engine

    # Initialize Finance Intelligence Layer & Database
    from app.database.session import init_db
    from app.finance.classifier import DocumentClassifier
    from app.finance.extraction.extractor import FinanceExtractor
    from app.finance.extraction.po_extractor import PurchaseOrderExtractor
    from app.finance.entity_resolution.resolver import EntityResolver
    from app.finance.linking.document_linker import DocumentLinker
    from app.finance.analytics.rule_engine import RuleEngine
    from app.finance.analytics.duplicate_detector import DuplicateDetector
    from app.finance.analytics.anomaly_detector import AnomalyDetector

    from app.finance.graph.factory import get_graph_adapter
    from app.finance.graph.sync_service import GraphSyncService

    from app.finance.vector.chunker import DocumentChunker
    from app.finance.vector.store import VectorStore

    init_db()
    app.state.classifier = DocumentClassifier()
    app.state.finance_extractor = FinanceExtractor()
    app.state.po_extractor = PurchaseOrderExtractor()
    app.state.entity_resolver = EntityResolver()
    app.state.document_linker = DocumentLinker()
    app.state.rule_engine = RuleEngine()
    app.state.duplicate_detector = DuplicateDetector()
    app.state.anomaly_detector = AnomalyDetector()

    graph_adapter = get_graph_adapter()
    app.state.graph_adapter = graph_adapter
    app.state.graph_sync = GraphSyncService(graph_adapter)

    app.state.chunker = DocumentChunker()
    app.state.vector_store = VectorStore()

    from app.intelligence.copilot import FinanceCopilotService
    from app.investigations.engine import FinanceInvestigationEngine
    from app.intelligence.tools.sql_tool import FinanceSQLTool
    from app.intelligence.tools.graph_tool import FinanceGraphTool
    from app.intelligence.tools.vector_tool import FinanceVectorTool
    from app.intelligence.tools.rules_tool import FinanceRulesTool
    from app.intelligence.tools.anomaly_tool import FinanceAnomalyTool
    from app.database.session import SessionLocal

    app.state.copilot = FinanceCopilotService.create_default(
        graph_adapter=graph_adapter,
        vector_store=app.state.vector_store,
        rule_engine=app.state.rule_engine,
        anomaly_detector=app.state.anomaly_detector,
    )

    app.state.investigation_engine = FinanceInvestigationEngine(
        sql_tool=FinanceSQLTool(session_factory=SessionLocal),
        graph_tool=FinanceGraphTool(graph_adapter=graph_adapter),
        vector_tool=FinanceVectorTool(vector_store=app.state.vector_store),
        rules_tool=FinanceRulesTool(session_factory=SessionLocal, rule_engine=app.state.rule_engine),
        anomaly_tool=FinanceAnomalyTool(session_factory=SessionLocal, anomaly_detector=app.state.anomaly_detector),
    )

    logger.info("APP_STARTUP: OCR Engine & Finance Intelligence Platform (Phase 1 to 7) ready.")
    yield
    logger.info("APP_SHUTDOWN: Closing vLLM HTTP connections...")
    await ocr_engine.vlm_client.close()
    logger.info("APP_SHUTDOWN: OCR Engine shutdown complete.")


app = FastAPI(
    title="Finance Document Intelligence Platform",
    description="High-performance layout-preserving OCR, canonical finance extraction, validation, and analytics",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS for browser integration
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from pathlib import Path

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

# Mount frontend UI
frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/ui", StaticFiles(directory=str(frontend_path), html=True), name="ui")

    @app.get("/", include_in_schema=False)
    async def root_redirect():
        return RedirectResponse(url="/ui")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
