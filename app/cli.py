import sys
import argparse
import asyncio
from pathlib import Path
from app.config import settings, PipelineMode
from app.engine.pipeline import OCREngine


def main():
    parser = argparse.ArgumentParser(
        description="Two-Stage Hybrid Layout-Preserving OCR Engine CLI"
    )
    parser.add_argument("document", type=str, help="Path to PDF or image file")
    parser.add_argument(
        "--mode",
        type=str,
        choices=["auto", "hybrid", "full_page"],
        default=settings.OCR_PIPELINE_MODE,
        help="Pipeline OCR strategy mode (auto, hybrid, full_page)",
    )
    parser.add_argument(
        "--pages",
        type=int,
        nargs="+",
        default=None,
        help="Specific page numbers to process (e.g. --pages 1 10 17)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=settings.OUTPUT_DIR,
        help="Base output directory for artifacts",
    )

    args = parser.parse_args()
    engine = OCREngine()

    print("==================================================")
    print("TWO-STAGE HYBRID LAYOUT-PRESERVING OCR ENGINE")
    print("==================================================")
    print(f"Document: {args.document}")
    print(f"Pipeline Mode: {args.mode}")
    print(f"Page Filter: {args.pages or 'all'}")
    print(f"Layout Model: {settings.LAYOUT_MODEL}")
    print(f"Inference Endpoint: {settings.VLLM_BASE_URL}")
    print("--------------------------------------------------")

    try:
        doc_result = asyncio.run(
            engine.process_document(
                args.document,
                output_dir=args.output_dir,
                pipeline_mode=args.mode,
                page_numbers=args.pages,
            )
        )

        meta = doc_result.metadata
        output_base = Path(args.output_dir) / doc_result.document_id

        print("\n--------------------------------------------------")
        print(f"OCR PROCESSING COMPLETED in {doc_result.processing_time_ms / 1000.0:.2f}s")
        print("--------------------------------------------------")
        print(f"Pages Processed: {doc_result.page_count}")
        print(f"Total Regions: {meta.total_regions}")
        print(f"Successful Regions: {meta.successful_regions}")
        print(f"Failed Regions: {meta.failed_regions}")
        print(f"Fallback Count: {meta.fallback_count}")
        print("--------------------------------------------------")
        print("OUTPUT ARTIFACTS:")
        print(f"  JSON:      {output_base / 'document.json'}")
        print(f"  Markdown:  {output_base / 'document.md'}")
        print(f"  Overlays:  {output_base / 'overlays'}")
        print(f"  Crops:     {output_base / 'crops'}")
        print(f"  Decisions: {output_base / 'analysis'}")
        print("==================================================")

    except Exception as e:
        print(f"\nERROR: Failed to process document: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        asyncio.run(engine.vlm_client.close())


if __name__ == "__main__":
    main()
