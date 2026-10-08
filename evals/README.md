# Model evals

Compares vision-language model deployments on synthetic wire instructions, using the service's own
extraction code (`WireExtractionService`: same prompt, schema and page rendering as production).

## Run

```bash
python -m evals.harness <deployment-name> [reads_per_doc]   # default 5 reads per document
python -m evals.harness mistral-document-ai-2512 5 --backend mistral-ocr [--image-only]
python -m evals.report                                       # rewrites every report.md and SCORECARD.md
```

The deployment must exist in the Azure AI Foundry resource configured in `.env`. Each run makes
6 x `reads_per_doc` model calls.

- Default backend (`responses`): the production code path; the model must accept the OpenAI Responses API with image input.
- `--backend mistral-ocr`: Mistral Document AI. `AZURE_AI_FOUNDRY_BASE_URL` must be the
  `https://<resource>.services.ai.azure.com/providers/mistral/azure/ocr` endpoint. Our schema and system prompt are
  sent as `document_annotation_format` / `document_annotation_prompt`.
- `--image-only`: strips the text layer by re-rendering every page as an image, like a scan. Results go to
  `<deployment>-image-only/`.

## Layout

- `harness.py` - the six test documents with ground truth, and the runner.
- `report.py` - scoring.
- `SCORECARD.md` - one row per model.
- `<deployment>/results.json` - raw reads (values, confidence, latency, tokens).
- `<deployment>/report.md` - scorecard, confidence per run, and every wrong value.
- `<deployment>/experiments/` - one-off experiments on that model.

## Test documents

| Doc | What it tests |
|---|---|
| `baseline` | The original one-page instruction |
| `repeated_digits` | Runs of repeated digits in ABA, account and address (`011000138`, `0001100223`) |
| `long_account` | 14-digit account number |
| `dense_table` | Small type in a bordered table with distractor rows |
| `blurry_scan` | Low-resolution grayscale JPEG with no text layer (fax-like) |
| `two_page` | Wiring details on page 2 |

All values are fictional except the routing numbers, which are chosen to pass the ABA checksum.

## Metrics

- **ABA+account accuracy**: the two fields that move money.
- **Mean confidence (right vs wrong)**: if these are close, the model's confidence cannot be used to flag errors.
- **Silent errors (2-pass)**: wrong values that two reads would agree on, and that pass the ABA checksum,
  so `EXTRACTION_PASSES=2` would not flag them. Consecutive reads of a document are paired to simulate it.

- `roi/` - Phase 1 ROI eval (replay through the real app + time/cost model); see `roi/README.md`.
