import json
import time
import asyncio
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any
from PIL import Image

from app.config import settings, PipelineMode
from app.models import (
    DocumentResult,
    PageResult,
    Region,
    BoundingBox,
    EngineMetadata,
    ProcessingMetadata,
    PipelineDecision,
    DedupDecision,
    FullPageOCRResult,
)
from app.engine.document_loader import DocumentLoader
from app.engine.layout_detector import LayoutDetector
from app.engine.cropper import RegionCropper
from app.engine.vlm_client import OCRInferenceClient, get_ocr_client
from app.engine.coverage_analyzer import CoverageAnalyzer
from app.engine.deduplication import DeduplicationAnalyzer
from app.engine.postprocessor import Postprocessor
from app.engine.reconstructor import DocumentReconstructor
from app.engine.visualization import draw_layout_overlay
from app.utils.files import generate_document_id, create_document_output_dirs, sanitize_filename
from app.utils.logging import logger


class OCREngine:
    """
    Two-Stage Hybrid Layout-Preserving OCR Pipeline Orchestrator
    with Coverage-Aware Auto Routing and Page-Local Deduplication.
    """

    def __init__(
        self,
        loader: Optional[DocumentLoader] = None,
        detector: Optional[LayoutDetector] = None,
        cropper: Optional[RegionCropper] = None,
        vlm_client: Optional[OCRInferenceClient] = None,
        coverage_analyzer: Optional[CoverageAnalyzer] = None,
        dedup_analyzer: Optional[DeduplicationAnalyzer] = None,
        postprocessor: Optional[Postprocessor] = None,
        reconstructor: Optional[DocumentReconstructor] = None,
    ):
        self.loader = loader or DocumentLoader()
        self.detector = detector or LayoutDetector()
        self.cropper = cropper or RegionCropper()
        self.vlm_client = vlm_client or get_ocr_client()
        self.coverage_analyzer = coverage_analyzer or CoverageAnalyzer()
        self.dedup_analyzer = dedup_analyzer or DeduplicationAnalyzer()
        self.postprocessor = postprocessor or Postprocessor()
        self.reconstructor = reconstructor or DocumentReconstructor()

    async def process_document(
        self,
        file_path: str,
        output_dir: str = settings.OUTPUT_DIR,
        save_debug: bool = settings.SAVE_DEBUG_ARTIFACTS,
        page_numbers: Optional[List[int]] = None,
        pipeline_mode: PipelineMode = settings.OCR_PIPELINE_MODE,
    ) -> DocumentResult:
        doc_start_time = time.time()
        doc_id = generate_document_id()
        filename = sanitize_filename(file_path)

        logger.info(f"==================================================")
        logger.info(
            f"OCR ENGINE START: processing '{filename}' [doc_id={doc_id}] "
            f"(mode={pipeline_mode}, pages={page_numbers or 'all'})"
        )
        logger.info(f"==================================================")

        # Setup directory paths
        base_dir, pages_dir, overlays_dir, crops_dir = create_document_output_dirs(output_dir, doc_id)
        analysis_dir = base_dir / "analysis"
        if save_debug and settings.SAVE_PIPELINE_DECISIONS:
            analysis_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: Render Document Pages
        render_start = time.time()
        page_tuples = self.loader.load_document(file_path, page_numbers=page_numbers)
        pdf_render_ms = (time.time() - render_start) * 1000.0
        page_count = len(page_tuples)

        # Initialize layout detector model ONCE
        self.detector.initialize()

        # Step 2: Stage 1 Layout Detection & Coverage Analysis per page
        layout_start = time.time()
        page_results: List[PageResult] = []
        hybrid_crops: List[Tuple[Region, Image.Image]] = []
        full_page_requests: List[Tuple[PageResult, Image.Image]] = []

        recognized_types = settings.recognized_region_types
        total_regions_count = 0
        fallback_count = 0

        for page_num, img in page_tuples:
            width, height = img.size

            # Save page image artifact
            if save_debug and settings.SAVE_PAGE_IMAGES:
                img.save(pages_dir / f"page_{page_num:03d}.png", format="PNG")

            # ── 1. Layout Detection (PP-DocLayoutV3) ───────────────────────
            # Layout model ALWAYS runs and detections are always preserved!
            regions = self.detector.detect(page_num, img)

            # ── 2. Coverage Analysis & Auto Decision ───────────────────────
            decision = self.coverage_analyzer.analyze_page(
                page_num, img, regions, requested_mode=pipeline_mode
            )

            if decision.fallback_used:
                fallback_count += 1

            # Save pipeline decision debug artifact
            if save_debug and settings.SAVE_PIPELINE_DECISIONS:
                dec_path = analysis_dir / f"page_{page_num:03d}_decision.json"
                with open(dec_path, "w", encoding="utf-8") as f:
                    json.dump(decision.model_dump(), f, indent=2)

            # Draw layout overlay artifact
            if save_debug and settings.SAVE_LAYOUT_OVERLAYS:
                overlay_path = overlays_dir / f"page_{page_num:03d}_layout.png"
                draw_layout_overlay(img, regions, overlay_path)

            page_res = PageResult(
                page_number=page_num,
                width=width,
                height=height,
                pipeline_decision=decision,
                regions=regions,
                fallback_used=decision.fallback_used,
                fallback_reason=decision.reason if decision.fallback_used else None,
            )

            # ── 3. Queue OCR Strategy Based on Decision ────────────────────
            if decision.selected_mode == "full_page":
                full_page_requests.append((page_res, img))
            else:
                # Hybrid mode: crop regions for region OCR
                for region in regions:
                    total_regions_count += 1
                    if region.region_type.lower() not in recognized_types:
                        region.processing_status = "skipped"
                        continue

                    crop_path = crops_dir / f"{region.id}_{region.region_type}.png" if save_debug else None
                    crop_img = self.cropper.crop_region(img, region, save_path=crop_path)
                    if crop_img is not None:
                        hybrid_crops.append((region, crop_img))

            page_results.append(page_res)

        layout_detection_ms = (time.time() - layout_start) * 1000.0

        # Step 3: Stage 2 OCR Execution
        ocr_start = time.time()
        logger.info(
            f"[Stage 2] Executing OCR (hybrid_crops={len(hybrid_crops)}, "
            f"full_pages={len(full_page_requests)}, concurrency={settings.OCR_CONCURRENCY})..."
        )

        # ── Execute Full-Page OCR Requests ───────────────────────────────────
        for p_res, p_img in full_page_requests:
            fp_res = await self.vlm_client.recognize_page(p_img)
            p_res.full_page_ocr = fp_res

        # ── Execute Hybrid Region OCR Requests ──────────────────────────────
        async def _ocr_task(region: Region, crop_img: Image.Image):
            return await self.vlm_client.recognize_region(region, crop_img)

        ocr_tasks = [_ocr_task(r, c_img) for r, c_img in hybrid_crops]
        if ocr_tasks:
            await asyncio.gather(*ocr_tasks)

        ocr_inference_ms = (time.time() - ocr_start) * 1000.0

        # Step 4: Postprocess Outputs & Run Page-Local Presentation Deduplication
        successful_count = 0
        failed_count = 0
        skipped_count = 0
        total_latency_sum = 0.0

        for page_res in page_results:
            mode = page_res.pipeline_decision.selected_mode if page_res.pipeline_decision else "hybrid"

            if mode == "hybrid":
                for region in page_res.regions:
                    if region.processing_status == "success":
                        self.postprocessor.process_region(region)
                        successful_count += 1
                        if region.processing_time_ms:
                            total_latency_sum += region.processing_time_ms
                    elif region.processing_status == "failed":
                        failed_count += 1
                    elif region.processing_status == "skipped":
                        skipped_count += 1

                # Page-local presentation deduplication (raw regions remain untouched)
                dedup_decisions = self.dedup_analyzer.analyze_page_deduplication(page_res.regions)
                page_res.dedup_decisions = dedup_decisions

            elif mode == "full_page":
                if page_res.full_page_ocr and page_res.full_page_ocr.status == "success":
                    successful_count += 1

        avg_region_latency = (total_latency_sum / successful_count) if successful_count > 0 else 0.0

        # Step 5: Reconstruct layout-preserving Markdown
        final_markdown = self.reconstructor.reconstruct_markdown(page_results)

        total_doc_ms = (time.time() - doc_start_time) * 1000.0

        # Build processing metadata
        meta = ProcessingMetadata(
            processing_time_ms=round(total_doc_ms, 2),
            pdf_rendering_time_ms=round(pdf_render_ms, 2),
            layout_detection_time_ms=round(layout_detection_ms, 2),
            ocr_inference_time_ms=round(ocr_inference_ms, 2),
            page_count=page_count,
            total_regions=total_regions_count,
            successful_regions=successful_count,
            failed_regions=failed_count,
            skipped_regions=skipped_count,
            fallback_count=fallback_count,
            avg_region_latency_ms=round(avg_region_latency, 2),
        )

        doc_result = DocumentResult(
            document_id=doc_id,
            filename=filename,
            page_count=page_count,
            processing_time_ms=round(total_doc_ms, 2),
            engine=EngineMetadata(
                layout_model=settings.LAYOUT_MODEL,
                ocr_model=settings.VLLM_MODEL,
                inference_engine="vLLM" if not settings.OCR_MOCK_MODE else "MockEngine"
            ),
            pages=page_results,
            markdown=final_markdown,
            metadata=meta
        )

        # Save output JSON and Markdown artifacts
        if save_debug:
            json_path = base_dir / "document.json"
            md_path = base_dir / "document.md"

            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(doc_result.model_dump(), f, indent=2)

            with open(md_path, "w", encoding="utf-8") as f:
                f.write(final_markdown)

            logger.info(f"OUTPUT_SAVED: JSON -> {json_path}")
            logger.info(f"OUTPUT_SAVED: Markdown -> {md_path}")

        logger.info(f"==================================================")
        logger.info(
            f"OCR ENGINE COMPLETE: {doc_id} in {total_doc_ms/1000.0:.2f}s "
            f"({page_count} pages processed)"
        )
        logger.info(f"==================================================")

        return doc_result
