import sys
import asyncio
import time
from pathlib import Path
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.models import Region, BoundingBox
from app.engine.vlm_client import get_ocr_client
from app.engine.postprocessor import Postprocessor


async def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/test_vllm.py <image_path>")
        sys.exit(1)

    image_path = Path(sys.argv[1])
    if not image_path.exists():
        print(f"File not found: {image_path}")
        sys.exit(1)

    print(f"Testing vLLM OCR on image: {image_path}")
    print(f"Base URL: {settings.VLLM_BASE_URL}")
    print(f"Model:    {settings.VLLM_MODEL}")

    img = Image.open(image_path).convert("RGB")
    w, h = img.size

    region = Region(
        id="test_r1",
        page_number=1,
        region_type="text",
        reading_order=1,
        bbox=BoundingBox(x1=0, y1=0, x2=w, y2=h)
    )

    client = get_ocr_client()
    try:
        start_time = time.time()
        res_region = await client.recognize_region(region, img)
        latency = (time.time() - start_time) * 1000.0

        print(f"\n--- INFERENCE RESULT (Latency: {latency:.1f}ms) ---")
        print(f"Status: {res_region.processing_status}")
        if res_region.error:
            print(f"Error:  {res_region.error}")
        else:
            print(f"\nRAW OCR OUTPUT:\n{res_region.raw_ocr_output}")

            post = Postprocessor()
            post.process_region(res_region)
            print(f"\nCLEANED CONTENT:\n{res_region.clean_content}")

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
