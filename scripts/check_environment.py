import sys
import os
import asyncio
from pathlib import Path

# Ensure app package is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.engine.vlm_client import VLLMOCRClient


def check_python():
    v = sys.version_info
    print(f"✓ Python {v.major}.{v.minor}.{v.micro}")


def check_packages():
    required = ["fitz", "PIL", "pydantic", "fastapi", "uvicorn", "httpx", "cv2"]
    missing = []
    for pkg in required:
        try:
            __import__(pkg)
            print(f"✓ Package '{pkg}' installed")
        except ImportError:
            missing.append(pkg)
            print(f"✗ Package '{pkg}' NOT installed")
    if missing:
        print(f"WARNING: Missing packages: {missing}")


def check_layout_model():
    try:
        from app.engine.layout_detector import LayoutDetector
        detector = LayoutDetector()
        detector.initialize()
        print(f"✓ Layout model '{settings.LAYOUT_MODEL}' initialized successfully")
    except Exception as e:
        print(f"⚠ Layout model note: {e}")


async def check_vllm():
    client = VLLMOCRClient()
    print(f"Checking vLLM reachability at {settings.VLLM_BASE_URL}...")
    reachable = await client.check_health()
    await client.close()

    if reachable:
        print(f"✓ vLLM inference server reachable at {settings.VLLM_BASE_URL}")
        print(f"✓ Configured OCR model: '{settings.VLLM_MODEL}'")
    else:
        print(f"⚠ vLLM inference server NOT reachable at {settings.VLLM_BASE_URL}")
        print(f"  Note: Enable OCR_MOCK_MODE=true for local testing without GPU server.")


def main():
    print("==================================================")
    print("ENVIRONMENT CHECK")
    print("==================================================")
    check_python()
    check_packages()
    check_layout_model()
    asyncio.run(check_vllm())
    print("==================================================")


if __name__ == "__main__":
    main()
