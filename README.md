# Wiring Instruction Extractor

FastAPI service that sends wire-instruction documents to Azure AI Foundry and returns an Excel workbook containing structured extraction results. It accepts a single document or a ZIP archive; archive documents are processed concurrently and become separate workbook rows.

Supported documents are PDF, TIFF, PNG, JPEG, GIF, and WebP; other types (including `.docx`/`.xlsx`) are rejected with HTTP 422. PDF and TIFF uploads are rendered to ordered PNG page images in memory before being sent to the model. The service does not perform OCR or extract PDF text locally.

## Requirements

- Python 3.10 or newer
- An Azure AI Foundry or Azure OpenAI deployment that supports file input through the Responses API
- An Azure AI Foundry API key

## Quick Start

1. Extract the project archive and open a terminal in the extracted `wiring-instruction` directory.
2. Create and activate a virtual environment.

   Windows PowerShell:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   macOS or Linux:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Install the application dependencies.

   ```powershell
   py -m pip install -r requirements.txt
   ```

4. Create the local configuration file and provide Azure credentials.

   Windows PowerShell:

   ```powershell
   Copy-Item .env.example .env
   ```

   macOS or Linux:

   ```bash
   cp .env.example .env
   ```

5. Edit `.env` and replace `AZURE_AI_FOUNDRY_BASE_URL` and `AZURE_AI_FOUNDRY_API_KEY` with real values.
6. Start the application.

   ```powershell
   py -m uvicorn app.main:app --reload
   ```

7. Open `http://127.0.0.1:8000/demo` to use the upload page. API documentation is at `http://127.0.0.1:8000/docs`.

## Configuration

`.env.example` documents every supported setting. Do not commit the generated `.env` file because it contains credentials.

| Setting | Purpose | Default |
| --- | --- | --- |
| `AZURE_AI_FOUNDRY_BASE_URL` | Azure OpenAI endpoint, OpenAI-compatible v1 base URL, or full Foundry Responses URL | Required |
| `AZURE_AI_FOUNDRY_API_KEY` | Azure AI Foundry API key | Required |
| `AZURE_AI_FOUNDRY_DEPLOYMENT` | Name of a model deployment in your resource (not the model name). It must exist, or requests fail with `DeploymentNotFound`. | `gpt-6-luna` |
| `MANUAL_REVIEW_CONFIDENCE_THRESHOLD` | Highlight fields below this confidence, from 0 to 1 | `0.80` |
| `MAX_UPLOAD_BYTES` | Maximum uploaded file and individual archive-member size | `20971520` (20 MiB) |
| `MAX_ARCHIVE_FILES` | Maximum non-directory files in a ZIP | `100` |
| `MAX_ARCHIVE_UNCOMPRESSED_BYTES` | Maximum total uncompressed ZIP content | `104857600` (100 MiB) |
| `MAX_PDF_PAGES` | Maximum pages rendered from one PDF or TIFF; longer files get HTTP 422 | `25` |
| `MAX_CONCURRENT_EXTRACTIONS` | Maximum simultaneous model calls while processing a ZIP | `8` |
| `REQUEST_TIMEOUT_SECONDS` | Timeout for each model call | `90` |
| `REQUEST_DEADLINE_SECONDS` | Overall budget for one `/extract` request. ZIP members not finished in time become "Not processed" rows; a single document gets HTTP 504. Keep it below the Azure Functions HTTP limit (~230 s). | `200` |
| `EXTRACTION_PASSES` | Independent model reads per document (1-3). With 2 or more, any field whose reads disagree is highlighted and noted. Multiplies cost and latency; set `1` only for cheap experiments. | `2` |
| `LOG_MODEL_RESPONSES` | Write raw LLM responses to the server console. Enable only for local debugging because responses contain banking data. | `false` |

The application normalizes Azure endpoints in these forms: resource endpoint (`https://YOUR-RESOURCE.openai.azure.com/`), OpenAI-compatible v1 base URL, or full Foundry Responses endpoint with an `api-version` query parameter.

## Usage

Use the browser upload page at `/demo`, or submit directly to `POST /extract`:

```powershell
curl.exe -X POST http://127.0.0.1:8000/extract `
  -F "file=@C:\documents\wire-instruction.pdf" `
  -F "source_url=https://storage.example.net/wires/wire-instruction.pdf" `
  -o wire-instruction-results.xlsx
```

To process a ZIP archive, submit it to the same endpoint:

```powershell
curl.exe -X POST http://127.0.0.1:8000/extract `
  -F "file=@C:\documents\wire-instructions.zip" `
  -o wire-instruction-results.xlsx
```

Nested ZIPs are expanded (up to 3 levels) and count toward the same file and size limits. Encrypted archives are rejected. macOS metadata (`__MACOSX/`, `._*`, `.DS_Store`) is ignored. If one document in an archive fails, the workbook still contains every other row; the failed row is marked for manual review with the reason in the `Notes` column. Routing numbers that are not valid 9-digit ABA numbers (checksum) are highlighted and noted too, because vision models can drop or swap digits with high stated confidence. Model confidence is not calibrated (wrong values have been seen at 95%), so by default each document is read twice (`EXTRACTION_PASSES=2`) to flag fields such as account numbers, which have no checksum, whenever two reads disagree. `source_url`, when supplied, must be an absolute http(s) URL. The service does not extract files to disk; it reads archive members in memory and sends each member to the model.

## Excel Output

The downloaded `wire-instruction-results.xlsx` contains a `Results` sheet with one row per input document. It includes:

- Document source
- Beneficiary name and address
- Bank name and address
- Routing number (ABA)
- Account number
- Manual-review indicator

Cells with a missing value or confidence below the configured threshold are amber. Hover over a field cell to view its confidence and source page. The workbook header includes a legend and the active confidence threshold.

## Tests

Install development dependencies and run the suite:

```powershell
py -m pip install -r requirements-dev.txt
py -m pytest
```

## Azure Functions

`function_app.py` exposes the same FastAPI application through Azure Functions. For local Functions development, copy `local.settings.json.example` to `local.settings.json`, set the same Azure credentials, and run Azure Functions Core Tools. For deployment, configure the settings listed above as Function App application settings. The HTTP endpoint is anonymous until authentication is added.
