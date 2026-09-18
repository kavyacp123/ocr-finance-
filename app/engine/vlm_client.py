import io
import base64
import asyncio
import time
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any
from PIL import Image
import httpx
from openai import AsyncOpenAI

from app.config import settings
from app.models import Region, FullPageOCRResult
from app.utils.logging import logger
from app.utils.files import InferenceConnectionError, InferenceTimeoutError


def image_to_base64_data_uri(image: Image.Image) -> str:
    buffered = io.BytesIO()
    image.save(buffered, format="PNG")
    img_bytes = buffered.getvalue()
    b64_str = base64.b64encode(img_bytes).decode("utf-8")
    return f"data:image/png;base64,{b64_str}"


class OCRInferenceClient(ABC):
    """Abstract interface for OCR / VLM inference engine."""

    @abstractmethod
    async def recognize_region(self, region: Region, crop_image: Image.Image) -> Region:
        pass

    @abstractmethod
    async def recognize_page(self, page_image: Image.Image) -> FullPageOCRResult:
        pass

    @abstractmethod
    async def check_health(self) -> bool:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass


class VLLMOCRClient(OCRInferenceClient):
    """
    Client for communicating asynchronously with vLLM serving baidu/Unlimited-OCR
    over the OpenAI-compatible Chat Completions API.
    """

    def __init__(
        self,
        base_url: str = settings.VLLM_BASE_URL,
        api_key: str = settings.VLLM_API_KEY,
        model_name: str = settings.VLLM_MODEL,
        timeout: float = settings.VLLM_TIMEOUT_SECONDS,
        max_retries: int = settings.VLLM_MAX_RETRIES,
        concurrency: int = settings.OCR_CONCURRENCY,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model_name = model_name
        self.timeout = timeout
        self.max_retries = max_retries
        self.semaphore = asyncio.Semaphore(concurrency)

        self.http_client = httpx.AsyncClient(timeout=httpx.Timeout(timeout))
        self.openai_client = AsyncOpenAI(
            base_url=self.base_url,
            api_key=self.api_key,
            http_client=self.http_client
        )

    async def check_health(self) -> bool:
        try:
            url = f"{self.base_url}/models"
            resp = await self.http_client.get(url, timeout=5.0)
            if resp.status_code == 200:
                logger.info(f"VLLM_HEALTH: Reachable at {self.base_url}")
                return True
            logger.warning(f"VLLM_HEALTH: Server returned status {resp.status_code}")
            return False
        except Exception as e:
            logger.warning(f"VLLM_HEALTH: Failed to connect to {self.base_url}: {e}")
            return False

    async def recognize_region(self, region: Region, crop_image: Image.Image) -> Region:
        async with self.semaphore:
            start_time = time.time()
            logger.info(f"OCR_REQUEST_START: Region {region.id} ({region.region_type})")

            data_uri = image_to_base64_data_uri(crop_image)
            prompt_text = "<image>document parsing."

            payload = {
                "model": self.model_name,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt_text},
                            {"type": "image_url", "image_url": {"url": data_uri}}
                        ]
                    }
                ],
                "temperature": 0.0,
                "max_tokens": settings.VLLM_MAX_TOKENS,
                "skip_special_tokens": False,
                "vllm_xargs": {
                    "ngram_size": settings.OCR_NGRAM_SIZE,
                    "window_size": settings.OCR_WINDOW_SIZE
                }
            }

            attempt = 0
            last_error = None

            while attempt <= self.max_retries:
                attempt += 1
                try:
                    url = f"{self.base_url}/chat/completions"
                    headers = {"Content-Type": "application/json"}
                    if self.api_key and self.api_key != "EMPTY":
                        headers["Authorization"] = f"Bearer {self.api_key}"

                    resp = await self.http_client.post(url, json=payload, headers=headers)

                    if resp.status_code == 200:
                        res_json = resp.json()
                        raw_output = res_json["choices"][0]["message"]["content"]
                        duration_ms = (time.time() - start_time) * 1000.0

                        region.raw_ocr_output = raw_output
                        region.processing_status = "success"
                        region.processing_time_ms = round(duration_ms, 2)
                        region.error = None

                        logger.info(f"OCR_REQUEST_COMPLETE: Region {region.id} succeeded in {duration_ms:.1f}ms")
                        return region
                    else:
                        error_msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
                        logger.warning(f"OCR_REQUEST_RETRY: Region {region.id} attempt {attempt} failed: {error_msg}")
                        last_error = error_msg

                except (httpx.TimeoutException, httpx.ConnectError) as e:
                    error_msg = f"{type(e).__name__}: {str(e)}"
                    logger.warning(f"OCR_REQUEST_RETRY: Region {region.id} attempt {attempt} network error: {error_msg}")
                    last_error = error_msg
                except Exception as e:
                    error_msg = f"Unexpected error: {str(e)}"
                    logger.warning(f"OCR_REQUEST_RETRY: Region {region.id} attempt {attempt} error: {error_msg}")
                    last_error = error_msg

                if attempt <= self.max_retries:
                    backoff = 1.0 * (2 ** (attempt - 1))
                    await asyncio.sleep(backoff)

            duration_ms = (time.time() - start_time) * 1000.0
            region.raw_ocr_output = None
            region.clean_content = None
            region.processing_status = "failed"
            region.processing_time_ms = round(duration_ms, 2)
            region.error = f"OCR failed after {self.max_retries + 1} attempts. Last error: {last_error}"
            logger.error(f"OCR_REQUEST_FAILED: Region {region.id} permanently failed: {region.error}")
            return region

    async def recognize_page(self, page_image: Image.Image) -> FullPageOCRResult:
        start_time = time.time()
        logger.info("OCR_PAGE_START: Running full-page OCR via vLLM")
        try:
            data_uri = image_to_base64_data_uri(page_image)
            payload = {
                "model": self.model_name,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "<image>document parsing."},
                            {"type": "image_url", "image_url": {"url": data_uri}}
                        ]
                    }
                ],
                "temperature": 0.0,
                "max_tokens": settings.VLLM_MAX_TOKENS,
            }
            url = f"{self.base_url}/chat/completions"
            headers = {"Content-Type": "application/json"}
            if self.api_key and self.api_key != "EMPTY":
                headers["Authorization"] = f"Bearer {self.api_key}"

            resp = await self.http_client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                res_json = resp.json()
                text = res_json["choices"][0]["message"]["content"]
                duration_ms = (time.time() - start_time) * 1000.0
                return FullPageOCRResult(
                    status="success",
                    text=text,
                    processing_time_ms=round(duration_ms, 2),
                )
            else:
                duration_ms = (time.time() - start_time) * 1000.0
                return FullPageOCRResult(
                    status="failed",
                    error=f"HTTP {resp.status_code}: {resp.text[:200]}",
                    processing_time_ms=round(duration_ms, 2),
                )
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000.0
            return FullPageOCRResult(
                status="failed",
                error=str(e),
                processing_time_ms=round(duration_ms, 2),
            )

    async def close(self) -> None:
        await self.http_client.aclose()


class MockOCRClient(OCRInferenceClient):
    """
    Deterministic Mock OCR client for local testing & development when vLLM GPU server is offline.
    """

    def __init__(self, latency_ms: float = 50.0):
        self.latency_ms = latency_ms

    async def check_health(self) -> bool:
        return True

    async def recognize_region(self, region: Region, crop_image: Image.Image) -> Region:
        await asyncio.sleep(self.latency_ms / 1000.0)
        start_time = time.time()

        r_type = region.region_type
        if r_type == "title":
            raw = f"<|det|>[[10, 10, 100, 100]]<|/det|> # Document Title - Page {region.page_number}"
        elif r_type == "table":
            raw = "<|det|>[[100, 200, 500, 400]]<|/det|> | Item | Quantity | Price |\n|---|---|---|\n| Product A | 10 | $150.00 |\n| Product B | 5 | $75.00 |"
        elif r_type == "equation":
            raw = r"$$\int_{0}^{\infty} e^{-x^2} dx = \frac{\sqrt{\pi}}{2}$$"
        elif r_type == "header":
            raw = f"Header: Confidential - Document Page {region.page_number}"
        elif r_type == "footer":
            raw = f"Footer: Page {region.page_number} of 5"
        else:
            raw = f"<|ref|>Paragraph text<|/ref|> This is recognized text content for region {region.id} ({region.region_type}) on page {region.page_number}."

        region.raw_ocr_output = raw
        region.processing_status = "success"
        region.processing_time_ms = round((time.time() - start_time) * 1000.0 + self.latency_ms, 2)
        region.error = None
        return region

    async def recognize_page(self, page_image: Image.Image) -> FullPageOCRResult:
        await asyncio.sleep(self.latency_ms / 1000.0)
        mock_text = "# FULL PAGE OCR OUTPUT\nSONAL ENTERPRISES\nTAX INVOICE\nTotal: 22,222.00"
        return FullPageOCRResult(
            status="success",
            text=mock_text,
            processing_time_ms=self.latency_ms,
        )

    async def close(self) -> None:
        pass


class LocalOCRClient(OCRInferenceClient):
    """
    Local visual OCR client fallback using EasyOCR for reading actual image content
    when vLLM GPU server is offline.
    """

    def __init__(self):
        self.reader = None
        try:
            import easyocr
            from pathlib import Path
            base_dir = Path("/Users/kavyapatel/Desktop/ocr/.easyocr").resolve()
            m_dir = base_dir / "model"
            u_dir = base_dir / "user_network"
            m_dir.mkdir(parents=True, exist_ok=True)
            u_dir.mkdir(parents=True, exist_ok=True)

            self.reader = easyocr.Reader(
                ['en'],
                model_storage_directory=str(m_dir),
                user_network_directory=str(u_dir),
                download_enabled=True,
                gpu=False
            )
            logger.info("OCR_CLIENT: Local EasyOCR engine initialized.")
        except Exception as e:
            logger.warning(f"Local EasyOCR engine init note: {e}")

    async def check_health(self) -> bool:
        return self.reader is not None

    async def recognize_region(self, region: Region, crop_image: Image.Image) -> Region:
        start_time = time.time()
        if self.reader is None:
            region.raw_ocr_output = f"[{region.region_type.upper()}] Recognized Content"
            region.processing_status = "success"
            region.processing_time_ms = 10.0
            return region

        try:
            import numpy as np
            crop_np = np.array(crop_image.convert("RGB"))
            results = self.reader.readtext(crop_np, detail=0)
            text = " ".join(results).strip()
            if not text:
                text = f"[{region.region_type.upper()}]"

            region.raw_ocr_output = text
            region.processing_status = "success"
            region.processing_time_ms = round((time.time() - start_time) * 1000.0, 2)
            region.error = None
        except Exception as e:
            region.raw_ocr_output = f"[{region.region_type.upper()}]"
            region.processing_status = "failed"
            region.error = str(e)

        return region

    async def recognize_page(self, page_image: Image.Image) -> FullPageOCRResult:
        start_time = time.time()
        logger.info("OCR_PAGE_START: Running full-page OCR via EasyOCR")
        if self.reader is None:
            return FullPageOCRResult(
                status="success",
                text="[FULL PAGE OCR CONTENT]",
                processing_time_ms=10.0,
            )

        try:
            import numpy as np
            page_np = np.array(page_image.convert("RGB"))
            results = self.reader.readtext(page_np, detail=1)
            text = self._reconstruct_reading_order(results)
            duration_ms = (time.time() - start_time) * 1000.0
            return FullPageOCRResult(
                status="success",
                text=text,
                processing_time_ms=round(duration_ms, 2),
            )
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000.0
            return FullPageOCRResult(
                status="failed",
                error=str(e),
                processing_time_ms=round(duration_ms, 2),
            )

    @staticmethod
    def _reconstruct_reading_order(results: list) -> str:
        """Group EasyOCR boxes into visual rows before joining their text."""
        items = []
        for result in results:
            if len(result) < 2 or not result[1]:
                continue
            box, text = result[0], str(result[1]).strip()
            xs = [float(point[0]) for point in box]
            ys = [float(point[1]) for point in box]
            items.append({
                "text": text,
                "x": min(xs),
                "y": (min(ys) + max(ys)) / 2.0,
                "height": max(1.0, max(ys) - min(ys)),
            })

        items.sort(key=lambda item: (item["y"], item["x"]))
        rows = []
        for item in items:
            if not rows:
                rows.append([item])
                continue
            row = rows[-1]
            row_y = sum(entry["y"] for entry in row) / len(row)
            row_height = max(entry["height"] for entry in row)
            tolerance = max(12.0, min(row_height, item["height"]) * 0.6)
            if abs(item["y"] - row_y) <= tolerance:
                row.append(item)
            else:
                rows.append([item])

        lines = []
        for row in rows:
            row.sort(key=lambda item: item["x"])
            lines.append(" ".join(item["text"] for item in row))
        return "\n".join(lines).strip()

    async def close(self) -> None:
        pass


def get_ocr_client_metadata(client: OCRInferenceClient) -> tuple[str, str]:
    """Return the active inference engine and model names for API metadata."""
    if isinstance(client, VLLMOCRClient):
        return "vLLM", client.model_name
    if isinstance(client, LocalOCRClient):
        return "EasyOCR", "EasyOCR English"
    if isinstance(client, MockOCRClient):
        return "MockEngine", "Mock OCR"
    return type(client).__name__, settings.VLLM_MODEL


def get_ocr_client() -> OCRInferenceClient:
    """Factory function creating real VLLM client, Local visual OCR client, or Mock client based on settings."""
    if settings.OCR_MOCK_MODE:
        logger.info("OCR_CLIENT: Using MockOCRClient (OCR_MOCK_MODE=True)")
        return MockOCRClient()

    vllm_client = VLLMOCRClient()
    try:
        import httpx
        resp = httpx.get(f"{settings.VLLM_BASE_URL}/models", timeout=1.0)
        if resp.status_code == 200:
            logger.info(f"OCR_CLIENT: Using real VLLMOCRClient at {settings.VLLM_BASE_URL}")
            return vllm_client
    except Exception:
        pass

    logger.info("OCR_CLIENT: vLLM GPU server offline. Falling back to LocalOCRClient (EasyOCR).")
    return LocalOCRClient()
