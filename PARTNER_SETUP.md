# LedgerLens Finance Intelligence Platform
## Partner Setup and Run Manual

This manual explains how to install, configure, start, test, and stop the project.

## 1. What This Project Does

LedgerLens accepts financial documents and produces structured, searchable finance data.

Supported uploads:

- PDF
- PNG, JPG, JPEG, BMP, TIFF, WEBP
- CSV
- TXT
- XLSX
- DOCX

The system performs:

1. OCR or direct structured-file parsing
2. Invoice classification
3. Field and line-item extraction
4. Validation and confidence scoring
5. SQLite persistence
6. Knowledge-graph synchronization
7. Vector indexing and semantic search
8. Finance Copilot answers
9. Financial investigations
10. Optional Gemini narration over verified evidence

## 2. Requirements

### Required

- macOS or Linux
- Python 3.11 or newer
- Git
- Internet access for OCR.Space and Gemini
- At least 4 GB free disk space for OCR/model dependencies

### Optional

- OCR.Space API key for image/PDF OCR
- Google Gemini API key for Copilot and Investigation narration
- NVIDIA Linux server with vLLM if using the original local VLM pipeline instead of OCR.Space

## 3. Get the Project

```bash
git clone <repository-url>
cd ocr
```

If the project was shared as a folder, simply enter the project directory:

```bash
cd /path/to/ocr
```

## 4. Create the Python Environment

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Every new terminal session needs the virtual environment activated again:

```bash
cd /path/to/ocr
source venv/bin/activate
```

## 5. Configure the Environment

Create the local environment file:

```bash
cp .env.example .env
```

Never commit `.env`. It contains private API keys.

### Recommended OCR.Space and Gemini configuration

Edit `.env` and set:

```env
OCR_PROVIDER=ocr_space
OCR_SPACE_API_KEY=your_ocr_space_api_key

LANGCHAIN_ENABLED=true
LANGCHAIN_MODEL_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_api_key
LANGCHAIN_MODEL=gemini-flash-latest
LANGCHAIN_TEMPERATURE=0
LANGCHAIN_REQUIRE_EVIDENCE=true
```

The application uses Gemini only to improve the wording of verified Copilot and Investigation results. The SQL, graph, vector, rule, anomaly, financial calculation, and evidence layers remain deterministic.

If Gemini is unavailable or rate-limited, the system automatically returns the deterministic answer.

### OCR.Space limits

The local integration enforces:

- Maximum upload size: 1,000,000 bytes
- Maximum PDF pages: 3

Oversized images and PDFs are compressed when possible.

CSV, TXT, XLSX, and DOCX files are parsed locally and do not use OCR.Space.

## 6. Start the Backend and Frontend

From the project root:

```bash
cd /path/to/ocr
source venv/bin/activate
PYTHONPATH=. uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Keep this terminal open. The FastAPI backend also serves the frontend files, so no separate frontend command or Node.js server is required.

Open the frontend in a browser:

```text
http://localhost:8000/ui/
```

The backend API is available at:

```text
http://localhost:8000
```

For API documentation, open:

```text
http://localhost:8000/docs
```

### Backend command only

```bash
cd /path/to/ocr
source venv/bin/activate
PYTHONPATH=. uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Frontend command

There is no separate frontend server. The frontend is automatically served by the backend command above from the `frontend/` directory.

Useful endpoints:

```text
http://localhost:8000/ui/
http://localhost:8000/health
http://localhost:8000/config
http://localhost:8000/docs
```

Keep this terminal open while using the application.

## 7. Verify the Backend

Open a second terminal and run:

```bash
cd /path/to/ocr
source venv/bin/activate
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/config
```

Expected configuration indicators:

```json
{
  "langchain_enabled": true,
  "langchain_provider": "gemini",
  "langchain_model": "gemini-flash-latest"
}
```

The `/config` response never exposes API keys.

## 8. Use the Web Interface

Open:

```text
http://localhost:8000/ui/
```

### Upload a document

1. Open the **Ingest** tab.
2. Choose Invoice or Purchase Order.
3. Select or drag in a file.
4. Click **Extract and store**.
5. Review vendor, document number, total, date, and line items.

The uploaded document is processed and persisted into the local database.

## 9. Test the Finance Copilot

Use the Copilot tab or call the API directly:

```bash
curl -X POST http://127.0.0.1:8000/copilot/ask \
  -H 'Content-Type: application/json' \
  -d '{
    "question": "How much did we spend with SONAL ENTERPRISES?",
    "organization_id": "org_default"
  }'
```

Example questions:

```text
How much did we spend with SONAL ENTERPRISES?
Show all unpaid invoices.
Which invoices have PO mismatches?
Show unusual invoices.
Find invoices mentioning MS BUSH.
Show the vendor network for SONAL ENTERPRISES.
```

The answer includes confidence, evidence, and the selected intent.

## 10. Test Investigations

```bash
curl -X POST http://127.0.0.1:8000/investigate \
  -H 'Content-Type: application/json' \
  -d '{
    "question": "Why did SONAL ENTERPRISES spending increase in August 2025?",
    "organization_id": "org_default",
    "include_trace": true
  }'
```

An investigation compares periods, line items, prices, quantities, duplicates, rules, anomalies, graph relationships, and document evidence.

## 11. Test Vector Search and the Knowledge Graph

Vector index statistics:

```bash
curl http://127.0.0.1:8000/search/stats
```

Semantic search:

```bash
curl -X POST 'http://127.0.0.1:8000/search/semantic?organization_id=org_default' \
  -H 'Content-Type: application/json' \
  -d '{
    "query": "MS BUSH invoice",
    "organization_id": "org_default",
    "top_k": 5
  }'
```

Knowledge-graph statistics:

```bash
curl 'http://127.0.0.1:8000/graph/stats?organization_id=org_default'
```

## 12. Run the Tests

Run the full test suite:

```bash
source venv/bin/activate
pytest -q
```

Run the most important current integration tests:

```bash
pytest -q \
  tests/test_langchain_narrator.py \
  tests/test_copilot_api.py \
  tests/test_investigation_api.py \
  tests/test_finance_extraction.py \
  tests/test_vector_store.py \
  tests/test_ocr_space_client.py \
  tests/test_vector_chunker.py
```

The current focused suite has been verified with 20 passing tests.

## 13. Run Environment Checks

```bash
python scripts/check_environment.py
```

Other available smoke tests may require their own sample files or a vLLM server:

```bash
python scripts/test_layout.py
python scripts/test_vllm.py
```

## 14. vLLM Note

The recommended configuration uses OCR.Space for image/PDF OCR, so a local vLLM server is not required.

The FastAPI application uses port `8000`. Do not start vLLM on the same port.

If using vLLM separately, start it on another port, for example `8001`, and set:

```env
VLLM_BASE_URL=http://localhost:8001/v1
```

The current OCR.Space setup does not need this step.

## 15. Stop the Backend

In the terminal running Uvicorn, press:

```text
Ctrl+C
```

If the terminal is unavailable, stop the process listening on port 8000:

```bash
pid=$(lsof -tiTCP:8000 -sTCP:LISTEN | head -n 1)
if [ -n "$pid" ]; then kill "$pid"; fi
```

Verify that the port is clear:

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
```

No output means the backend is stopped.

## 16. Important Files

```text
app/main.py                         Application startup and service wiring
app/config.py                       Environment configuration
app/api/routes.py                   API endpoints
app/engine/ocr_space_client.py      OCR.Space integration
app/engine/ocr_provider.py          OCR provider routing
app/engine/upload_preprocessor.py  File conversion and compression
app/finance/extraction/             Finance extraction logic
app/finance/vector/                 Vector chunking and storage
app/intelligence/                   Copilot and grounded narration
app/investigations/                 Investigation engine
frontend/                           Browser interface
outputs/                            OCR artifacts and vector index
finance.db                          Local SQLite database
.env                                Private local configuration
```

## 17. Troubleshooting

### `command not found: uvicorn`

Activate the virtual environment:

```bash
source venv/bin/activate
```

If it still fails:

```bash
pip install -r requirements.txt
```

### Port 8000 is already in use

```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
kill <PID>
```

### OCR.Space rejects the upload

Check:

- file is below 1 MB after compression
- PDF has no more than 3 pages
- `OCR_SPACE_API_KEY` is set
- `OCR_PROVIDER=ocr_space`

### Gemini is unavailable

The application will fall back to deterministic answers. Check:

```bash
LANGCHAIN_ENABLED=true
LANGCHAIN_MODEL_PROVIDER=gemini
GEMINI_API_KEY=your_key
LANGCHAIN_MODEL=gemini-flash-latest
```

Gemini quota limits or temporary provider outages do not stop OCR or finance extraction.

### The UI shows old extraction results

Old database records are not automatically reprocessed. Upload the document again after changing extraction code.

### Vector results are empty for an old document

Older records may have been created before vector indexing was fixed. Reprocess the document to create fresh vector chunks.

## 18. Security Rules

- Never commit `.env`.
- Never paste API keys into source files.
- Do not upload confidential documents to a public OCR provider without approval.
- Keep organization IDs consistent for tenant isolation.
- Treat OCR text as untrusted input.
- Do not expose the SQLite database publicly.
- Rotate any API key that has been shared publicly.

## 19. Daily Start Checklist

```text
[ ] Open Terminal
[ ] cd into the project
[ ] source venv/bin/activate
[ ] Confirm .env exists
[ ] Start Uvicorn on port 8000
[ ] Open http://localhost:8000/ui/
[ ] Check /health
[ ] Upload a small test invoice
[ ] Verify line items and total
[ ] Test Copilot if Gemini is enabled
```

## 20. Daily Stop Checklist

```text
[ ] Stop Uvicorn with Ctrl+C
[ ] Confirm port 8000 is clear
[ ] Do not commit .env
[ ] Keep outputs and finance.db backed up if needed
```
