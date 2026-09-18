# Two-Stage Hybrid Layout-Preserving OCR Engine

High-performance, two-stage layout-aware OCR engine that processes PDF documents and multi-format images (PNG/JPG), extracts layout structure and reading order via **PP-DocLayoutV3**, crops regions with polygon masking, executes async concurrent OCR calls to **baidu/Unlimited-OCR** served by **vLLM**, postprocesses outputs, and reconstructs canonical structured JSON and layout-preserving Markdown.

---

## 1. Architecture Overview

```mermaid
graph TD
    Client[Client / Swagger UI] -->|POST /ocr| FastAPI[FastAPI App / CLI]
    FastAPI --> DocLoader[Document Loader]
    DocLoader -->|PyMuPDF 200 DPI| PageImages[Page Images]
    PageImages --> Detector[PP-DocLayoutV3 Adapter]
    Detector -->|Geometry + Reading Order| Regions[Layout Regions & Polygons]
    Regions --> Cropper[Region Cropper]
    Cropper -->|Polygon Mask + Padding| Crops[Crop 1..N]
    
    subgraph Concurrent Async Pipeline
        Crops -->|Async Semaphore Concurrency=8| AsyncClient[VLLM OCR Client]
        AsyncClient -->|OpenAI HTTP API| vLLM[vLLM Inference Server]
        vLLM -->|Continuous Batching| Model[baidu/Unlimited-OCR]
    end
    
    Model -->|Raw Output| Post[Postprocessor]
    Post -->|Clean Content| Reconstructor[Document Reconstructor]
    Reconstructor -->|Reading-Order Sorting| FinalJSON[document.json]
    Reconstructor -->|Reading-Order Sorting| FinalMD[document.md]
```

---

## 2. Why Two-Stage?

* **Stage 1 (Layout Detection)**: Answers *"What is where?"* by identifying title, text, table, figure, equation, chart, and list region geometry along with reading order using PP-DocLayoutV3.
* **Stage 2 (VLM Transcription)**: Answers *"What does this region say?"* by sending cropped image regions in parallel to the specialized document VLM (`baidu/Unlimited-OCR`) served by vLLM with continuous batching.

This hybrid approach prevents full-page hallucination, preserves multi-column reading order, maintains complex table structures, and maximizes GPU utilization.

---

## 3. Technology Stack

* **Language**: Python 3.11+
* **API / Server**: FastAPI + Uvicorn
* **PDF Rendering**: PyMuPDF (`fitz`) @ 200 DPI (configurable)
* **Image Processing**: Pillow + OpenCV
* **Layout Detection**: PP-DocLayoutV3 (PaddleX / PaddleOCR adapter)
* **OCR / VLM Serving**: vLLM serving `baidu/Unlimited-OCR`
* **VLM Communication**: Async OpenAI API (`httpx`) with `<image>document parsing.` prompt
* **Config & Schemas**: Pydantic v2 + Pydantic Settings
* **Testing**: pytest + pytest-asyncio

---

## 4. Quick Start & Installation

### Step 1: Clone & Setup Virtual Environment
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Step 2: Environment Configuration
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

To run offline pipeline tests without an active vLLM GPU server, set in `.env`:
```env
OCR_MOCK_MODE=true
```

---

## 5. Running the vLLM Inference Server

vLLM requires a CUDA-compatible NVIDIA GPU (Linux environment).

```text
Laptop / Orchestrator Machine
        │
        │ HTTP (VLLM_BASE_URL)
        ▼
Linux NVIDIA GPU Server
        │
        ▼
vLLM + baidu/Unlimited-OCR
```

Launch command for vLLM:
```bash
python3 -m vllm.entrypoints.openai.api_server \
    --model baidu/Unlimited-OCR \
    --trust-remote-code \
    --port 8000 \
    --max-model-len 4096
```

---

## 6. Verification & Smoke Testing

### 1. Environment Health Check
```bash
python scripts/check_environment.py
```

### 2. Stage 1 Layout Detection Smoke Test
```bash
python scripts/test_layout.py samples/test.png
```

### 3. Stage 2 vLLM Inference Smoke Test
```bash
python scripts/test_vllm.py samples/test.png
```

### 4. End-to-End Pipeline Execution (CLI)
```bash
python scripts/run_sample.py samples/report.pdf
```

---

## 7. Running the FastAPI Server

Start the ASGI server:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Interactive API documentation available at:
`http://localhost:8000/docs`

### Example API Request (curl)
```bash
curl -X POST "http://localhost:8000/ocr?save_debug=true" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@samples/report.pdf"
```

---

## 8. Output Artifacts Structure

For each processed document, artifacts are organized in `./outputs/<document-id>/`:

```text
outputs/<document-id>/
│
├── document.json               # Canonical structured JSON schema
├── document.md                 # Layout-preserving reconstructed Markdown
│
├── pages/                      # Original rendered page images
│   ├── page_001.png
│   └── page_002.png
│
├── overlays/                   # Color-coded region layout visualization
│   ├── page_001_layout.png
│   └── page_002_layout.png
│
└── crops/                      # Extracted cropped region images
    ├── p1_r1_title.png
    ├── p1_r2_paragraph.png
    └── p1_r3_table.png
```

---

## 9. Automated Testing

Run unit & pipeline mock tests:
```bash
pytest tests/ -v
```

---

## 10. Future Cloud Production Architecture (Design Specification)

In production cloud deployment, this engine will be wrapped with high-availability infrastructure:

```text
                   API Gateway (Kong / NGINX)
                               │
                               ▼
                    FastAPI Ingestion Tier
                               │
                               ▼
                    Redis / Kafka Job Queue
                               │
                               ▼
              ┌───── OCR Worker Pool ──────┐
              │  (Kubernetes + KEDA)        │
              │                             │
              │  Layout -> Crop -> vLLM     │
              │            -> Reconstruct   │
              └──────────────┬──────────────┘
                             │
                    S3 / MinIO Storage
                             │
                Prometheus + Grafana + OpenTelemetry
```
