# Phase 1 ROI eval (Initial Funding)

Shows what Phase 1 automation saves against the client's baseline of **~4 person-hours per funding package**,
and which extraction setup is safe enough to credit with those savings. No Azure credentials needed.

```bash
python -m evals.roi.replay 100   # ~8 min: 3 configs x 100 packages through the real /extract endpoint
python -m evals.roi.roi          # writes REPORT.md, roi.json, roi.html (client one-pager)
python -m evals.roi.charts       # writes dashboard.html: cost, accuracy, safety, speed and value charts per config
python -m evals.roi.client_report  # writes Phase1_Benefits.pdf, the client-facing summary
```

## Design

| Eval | Question | How | Measured or assumed |
|---|---|---|---|
| 1. Quality and review load | Of the values the workbook hands Accounting, how many are wrong, and is every wrong one flagged? How many fields must a reviewer touch? | `replay.py` posts a 100-document ZIP to the real FastAPI app with production settings (2 passes, ABA checksum, disagreement flags, 8-way concurrency, 200 s deadline). The model client is replaced by one that returns reads the model actually produced in earlier live evals (`evals/<config>/results.json`) and sleeps for their recorded latency. The returned workbook is scored cell by cell, including its highlight colour, against ground truth. | Measured |
| 2. Minutes per package | How long does a package take a person, today vs. now vs. Phase 1 complete? | `roi.py`: the 4 h is split across the five Phase 1 tasks. Wire extraction is replaced by measured review load (verify each row + fix each flagged field + key failed rows by hand). The other tasks keep an assumed residual share once automated. | Review load measured; task split, residuals and review minutes assumed |
| 3. Annual value | Hours, FTE and net dollars per year, and how sensitive that is | Minutes saved x volume x loaded rate, minus model and hosting cost; grid over volume and residual work | Assumed (`assumptions.json`) |

Configs compared: `gpt-6-luna` (production today), `mistral-document-ai-2512-image-only` (scanned input),
`mistral-ocr+gpt-6-luna` (Mistral OCR then luna on the text, disagreement flags). The two Mistral configs are not
wired into the service yet; replaying their reads through it shows what the workbook would look like if they were.

A config is recommended only if it left **no wrong value unflagged** and no failed rows. Wrong account or ABA
numbers are not costed in dollars: they are a stop condition, not a saving.

## Prices

Model prices come from the Azure Retail Prices API (East US 2, Global Standard, 2026-10-08): gpt-6-luna $0.10 / 1M
input and $0.50 / 1M output tokens; Mistral Document AI 2512 $3.00 / 1,000 pages. Volume (~100 loans/month and growing)
comes from the Treasury use-case diagram.

## Replacing assumptions

Every non-measured number is in `assumptions.json` with its source. During the pilot (design doc section 14),
log each package in `time_study_template.csv` both ways (manual and assisted), put the medians into
`assumptions.json`, and re-run `python -m evals.roi.roi`. To re-measure quality on real documents, record live
reads of the held-out real wire set with `python -m evals.harness` and add a config here.
